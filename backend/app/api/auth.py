from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, get_current_user, get_current_user_jwt, get_principal
from ..domain.scopes import (
    ALL_SCOPES,
    SCOPE_DATA,
    SCOPE_DATASET_MANAGE,
    SCOPE_DEFINITIONS,
    SCOPE_EVALUATE,
    SCOPE_EXPERIMENT,
    SCOPE_READ,
    SCOPE_REVIEW_REQUEST,
    SCOPE_WRITE,
)
from ..models import ApiToken, User, as_utc, utcnow
from ..rate_limit import client_ip, rate_limiter
from ..schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    AuthContextOut,
    DeviceAuthorizationOut,
    DeviceCodeOut,
    DeviceCodeRequest,
    DeviceTokenOut,
    DeviceTokenRequest,
    DeviceUserCodeRequest,
    LoginRequest,
    ScopeOut,
    TokenOut,
    UserOut,
)
from ..security import create_access_token, verify_password
from ..services import auth_service
from ..services.auth_service import DeviceFlowError

router = APIRouter(prefix="/auth", tags=["认证"])


def _enforce_rate_limit(
    request: Request,
    key: str,
    *,
    limit: int | None = None,
    window_seconds: int = 60,
) -> None:
    settings = get_settings()
    retry_after = rate_limiter.hit(
        f"{key}:{client_ip(request)}",
        limit if limit is not None else settings.auth_rate_limit_per_minute,
        window_seconds,
    )
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )


def _device_error(exc: DeviceFlowError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "error_description": exc.description},
        headers={"Cache-Control": "no-store"},
    )


def _verification_uri(request: Request) -> str:
    settings = get_settings()
    base = settings.public_base_url.strip().rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/device"


@router.post("/login", response_model=TokenOut)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenOut:
    settings = get_settings()
    username = payload.username.strip()
    _enforce_rate_limit(request, f"login:{username}", limit=10)
    _enforce_rate_limit(request, "login-ip", limit=settings.auth_rate_limit_per_minute * 3)

    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该用户已停用")
    token, expires_in = create_access_token(user.id)
    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/context", response_model=AuthContextOut)
def auth_context(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> AuthContextOut:
    """插件启动时的单次自检：身份、凭证类型与可用能力。"""

    settings = get_settings()
    scopes = (
        list(ALL_SCOPES)
        if principal.auth_method == "jwt"
        else sorted(principal.scopes or [])
    )
    granted = set(scopes)
    return AuthContextOut(
        service=settings.app_name,
        version=request.app.version,
        api_prefix=settings.api_prefix,
        auth_method=principal.auth_method,
        scopes=scopes,
        capabilities={
            "read": SCOPE_READ in granted,
            "data": SCOPE_DATA in granted,
            "write": SCOPE_WRITE in granted,
            "experiment": SCOPE_EXPERIMENT in granted,
            "evaluate": SCOPE_EVALUATE in granted,
            "review_request": SCOPE_REVIEW_REQUEST in granted,
            "dataset_manage": SCOPE_DATASET_MANAGE in granted,
        },
        repo_key=principal.repo_key,
        user=UserOut.model_validate(principal.user),
    )


@router.get("/scopes", response_model=list[ScopeOut])
def list_scopes(_: User = Depends(get_current_user)) -> list[ScopeOut]:
    return [
        ScopeOut(code=code, name=item["name"], description=item["description"])
        for code, item in SCOPE_DEFINITIONS.items()
    ]


@router.get("/tokens", response_model=list[ApiTokenOut])
def list_tokens(
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> list[ApiTokenOut]:
    tokens = db.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
    ).all()
    return [ApiTokenOut.model_validate(token) for token in tokens]


@router.post("/tokens", response_model=ApiTokenCreated, status_code=201)
def create_token(
    payload: ApiTokenCreate,
    request: Request,
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> ApiTokenCreated:
    _enforce_rate_limit(request, f"token-create:{user.id}", limit=10)
    try:
        raw, token = auth_service.create_api_token(
            db,
            user,
            name=payload.name,
            scopes=payload.scopes,
            expires_in_days=payload.expires_in_days,
            source="manual",
            repo_key=payload.repo_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiTokenCreated(token=raw, info=ApiTokenOut.model_validate(token))


@router.post("/tokens/{token_id}/revoke", response_model=ApiTokenOut)
def revoke_token(
    token_id: str,
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> ApiTokenOut:
    token = db.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise HTTPException(status_code=404, detail="访问令牌不存在")
    auth_service.revoke_api_token(db, token)
    return ApiTokenOut.model_validate(token)


@router.delete("/tokens/{token_id}", status_code=204)
def delete_token(
    token_id: str,
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> Response:
    token = db.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise HTTPException(status_code=404, detail="访问令牌不存在")
    auth_service.delete_api_token(db, token)
    return Response(status_code=204)


@router.post("/device/code", response_model=DeviceCodeOut)
def create_device_code(
    payload: DeviceCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DeviceCodeOut:
    settings = get_settings()
    _enforce_rate_limit(request, "device-code", limit=10)
    try:
        authorization, device_code, user_code = auth_service.create_device_authorization(
            db,
            client_name=payload.client_name,
            scopes=payload.scopes,
            repo_key=payload.repo_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    verification_uri = _verification_uri(request)
    return DeviceCodeOut(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=f"{verification_uri}?user_code={user_code}",
        expires_in=settings.device_code_expire_seconds,
        interval=authorization.interval_seconds,
    )


@router.post("/device/token", response_model=DeviceTokenOut)
def poll_device_token(
    payload: DeviceTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DeviceTokenOut | JSONResponse:
    _enforce_rate_limit(request, "device-token", limit=60)
    try:
        raw_token, token, _ = auth_service.poll_device_authorization(db, payload.device_code)
    except DeviceFlowError as exc:
        return _device_error(exc)
    return DeviceTokenOut(
        access_token=raw_token,
        scope=" ".join(token.scopes),
        repo_key=token.repo_key or "",
        expires_at=token.expires_at,
        user=UserOut.model_validate(token.user),
    )


@router.post("/device/lookup", response_model=DeviceAuthorizationOut)
def lookup_device(
    payload: DeviceUserCodeRequest,
    request: Request,
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> DeviceAuthorizationOut:
    _enforce_rate_limit(request, f"device-lookup:{user.id}", limit=20)
    authorization = auth_service.find_device_by_user_code(db, payload.user_code)
    if authorization is None:
        raise HTTPException(status_code=404, detail="设备码不存在")
    if authorization.status == "pending":
        expires_at = as_utc(authorization.expires_at)
        if expires_at is not None and expires_at <= utcnow():
            return DeviceAuthorizationOut(
                client_name=authorization.client_name,
                repo_key=authorization.repo_key or "",
                scopes=list(authorization.scopes),
                status="expired",
                expires_at=authorization.expires_at,
            )
    return DeviceAuthorizationOut(
        client_name=authorization.client_name,
        repo_key=authorization.repo_key or "",
        scopes=list(authorization.scopes),
        status=authorization.status,
        expires_at=authorization.expires_at,
    )


@router.post("/device/approve", response_model=DeviceAuthorizationOut)
def approve_device(
    payload: DeviceUserCodeRequest,
    request: Request,
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> DeviceAuthorizationOut:
    _enforce_rate_limit(request, f"device-approve:{user.id}", limit=20)
    authorization = auth_service.find_device_by_user_code(db, payload.user_code)
    if authorization is None:
        raise HTTPException(status_code=404, detail="设备码不存在")
    try:
        auth_service.approve_device(db, authorization, user)
    except DeviceFlowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.description) from exc
    return DeviceAuthorizationOut(
        client_name=authorization.client_name,
        repo_key=authorization.repo_key or "",
        scopes=list(authorization.scopes),
        status=authorization.status,
        expires_at=authorization.expires_at,
    )


@router.post("/device/deny", response_model=DeviceAuthorizationOut)
def deny_device(
    payload: DeviceUserCodeRequest,
    request: Request,
    user: User = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
) -> DeviceAuthorizationOut:
    _enforce_rate_limit(request, f"device-deny:{user.id}", limit=20)
    authorization = auth_service.find_device_by_user_code(db, payload.user_code)
    if authorization is None:
        raise HTTPException(status_code=404, detail="设备码不存在")
    try:
        auth_service.deny_device(db, authorization)
    except DeviceFlowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.description) from exc
    return DeviceAuthorizationOut(
        client_name=authorization.client_name,
        repo_key=authorization.repo_key or "",
        scopes=list(authorization.scopes),
        status=authorization.status,
        expires_at=authorization.expires_at,
    )
