from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..domain.scopes import normalize_scopes
from ..models import ApiToken, DeviceAuthorization, User, as_utc, utcnow
from ..security import (
    generate_api_token,
    generate_device_code,
    generate_user_code,
    hash_api_token,
    hash_user_code,
    normalize_user_code,
)


class DeviceFlowError(Exception):
    """设备码流程错误，按 RFC 8628 返回 error / error_description。"""

    def __init__(self, code: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.code = code
        self.description = description
        self.status_code = status_code


def _expired(value: datetime | None) -> bool:
    converted = as_utc(value)
    return converted is not None and converted <= utcnow()


def create_api_token(
    db: Session,
    user: User,
    *,
    name: str,
    scopes: list[str],
    expires_in_days: int,
    source: str = "manual",
    client_name: str = "",
    repo_key: str = "",
) -> tuple[str, ApiToken]:
    settings = get_settings()
    day_count = max(1, min(expires_in_days, settings.api_token_max_expire_days))
    normalized = normalize_scopes(scopes)
    raw, prefix, digest = generate_api_token()
    token = ApiToken(
        user_id=user.id,
        name=name.strip()[:80] or "未命名令牌",
        prefix=prefix,
        token_hash=digest,
        scopes=normalized,
        source=source,
        repo_key=repo_key.strip()[:80],
        client_name=client_name.strip()[:120],
        expires_at=utcnow() + timedelta(days=day_count),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return raw, token


def revoke_api_token(db: Session, token: ApiToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        db.commit()


def delete_api_token(db: Session, token: ApiToken) -> None:
    """永久删除令牌记录；设备授权记录保留，但解除对令牌的引用。"""

    db.execute(
        update(DeviceAuthorization)
        .where(DeviceAuthorization.api_token_id == token.id)
        .values(api_token_id=None)
    )
    db.delete(token)
    db.commit()


def revoke_user_tokens(db: Session, user_id: str, *, except_token_id: str | None = None) -> int:
    """撤销用户全部访问令牌；用于停用账号、重置密码等安全事件。"""

    now = utcnow()
    query = (
        update(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if except_token_id:
        query = query.where(ApiToken.id != except_token_id)
    result = db.execute(query)
    db.commit()
    return int(result.rowcount or 0)


def authenticate_api_token(db: Session, raw_token: str) -> ApiToken | None:
    """校验 Bearer token 是否为有效 API 令牌；失败一律返回 None。"""

    if not raw_token or not raw_token.startswith("mps_"):
        return None
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_api_token(raw_token)))
    if token is None:
        return None
    if token.revoked_at is not None or _expired(token.expires_at):
        return None
    user = token.user
    if user is None or not user.is_active:
        return None

    # 高频轮询时避免每个请求都写库，最多每 5 分钟更新一次最近使用时间。
    last_used = as_utc(token.last_used_at)
    if last_used is None or (utcnow() - last_used).total_seconds() >= 300:
        token.last_used_at = utcnow()
        db.commit()
    return token


def create_device_authorization(
    db: Session,
    *,
    client_name: str,
    scopes: list[str],
    repo_key: str = "",
) -> tuple[DeviceAuthorization, str, str]:
    settings = get_settings()
    purge_expired_device_codes(db)

    normalized = normalize_scopes(scopes)
    device_code = generate_device_code()
    user_code = generate_user_code()
    digest = hash_user_code(user_code)
    while db.scalar(
        select(DeviceAuthorization.id).where(DeviceAuthorization.user_code_hash == digest)
    ):
        user_code = generate_user_code()
        digest = hash_user_code(user_code)

    authorization = DeviceAuthorization(
        device_code_hash=hash_api_token(device_code),
        user_code_hash=digest,
        client_name=client_name.strip()[:120] or "medpowers",
        repo_key=repo_key.strip()[:80],
        scopes=normalized,
        interval_seconds=settings.device_poll_interval_seconds,
        expires_at=utcnow() + timedelta(seconds=settings.device_code_expire_seconds),
    )
    db.add(authorization)
    db.commit()
    db.refresh(authorization)
    return authorization, device_code, user_code


def find_device_by_user_code(db: Session, user_code: str) -> DeviceAuthorization | None:
    normalized = normalize_user_code(user_code)
    if len(normalized) != 8:
        return None
    return db.scalar(
        select(DeviceAuthorization).where(
            DeviceAuthorization.user_code_hash == hash_user_code(normalized)
        )
    )


def find_device_by_device_code(db: Session, device_code: str) -> DeviceAuthorization | None:
    return db.scalar(
        select(DeviceAuthorization).where(
            DeviceAuthorization.device_code_hash == hash_api_token(device_code)
        )
    )


def approve_device(db: Session, authorization: DeviceAuthorization, user: User) -> None:
    if authorization.status == "denied":
        raise DeviceFlowError("access_denied", "该设备授权请求已被拒绝")
    if authorization.status == "consumed":
        raise DeviceFlowError("expired_token", "该设备码已被使用")
    if authorization.status != "pending":
        raise DeviceFlowError("invalid_grant", "该设备码当前不可批准", status_code=409)
    if _expired(authorization.expires_at):
        authorization.status = "expired"
        db.commit()
        raise DeviceFlowError("expired_token", "设备码已过期")

    authorization.status = "approved"
    authorization.user_id = user.id
    authorization.approved_at = utcnow()
    db.commit()


def deny_device(db: Session, authorization: DeviceAuthorization) -> None:
    if authorization.status != "pending":
        raise DeviceFlowError("invalid_grant", "该设备码当前不可拒绝", status_code=409)
    authorization.status = "denied"
    authorization.denied_at = utcnow()
    db.commit()


def poll_device_authorization(
    db: Session, device_code: str
) -> tuple[str, ApiToken, DeviceAuthorization]:
    authorization = find_device_by_device_code(db, device_code)
    if authorization is None:
        raise DeviceFlowError("invalid_grant", "device_code 无效")
    if _expired(authorization.expires_at) and authorization.status in {"pending", "approved"}:
        authorization.status = "expired"
        db.commit()
    if authorization.status == "denied":
        raise DeviceFlowError("access_denied", "用户已拒绝该设备授权请求")
    if authorization.status in {"expired", "consumed"}:
        raise DeviceFlowError("expired_token", "设备码已过期或已被使用")
    if authorization.status == "pending":
        now = utcnow()
        last_polled = as_utc(authorization.last_polled_at)
        if last_polled is not None:
            elapsed = (now - last_polled).total_seconds()
            if elapsed < authorization.interval_seconds:
                authorization.interval_seconds = min(30, authorization.interval_seconds + 5)
                authorization.last_polled_at = now
                db.commit()
                raise DeviceFlowError("slow_down", "轮询过于频繁，请降低轮询频率")
        authorization.last_polled_at = now
        db.commit()
        raise DeviceFlowError("authorization_pending", "用户尚未完成授权")

    user = db.get(User, authorization.user_id) if authorization.user_id else None
    if user is None or not user.is_active:
        raise DeviceFlowError("access_denied", "授权用户不存在或已停用")

    settings = get_settings()
    raw, token = create_api_token(
        db,
        user,
        name=f"{authorization.client_name}（设备授权）",
        scopes=list(authorization.scopes),
        expires_in_days=settings.api_token_default_expire_days,
        source="device",
        client_name=authorization.client_name,
        repo_key=authorization.repo_key or "",
    )

    # 条件更新保证并发轮询时只有一个请求能拿到 token。
    result = db.execute(
        update(DeviceAuthorization)
        .where(
            DeviceAuthorization.id == authorization.id,
            DeviceAuthorization.status == "approved",
        )
        .values(status="consumed", consumed_at=utcnow(), api_token_id=token.id)
    )
    db.commit()
    if int(result.rowcount or 0) != 1:
        token.revoked_at = utcnow()
        db.commit()
        raise DeviceFlowError("expired_token", "设备码已被其他请求使用")

    return raw, token, authorization


def purge_expired_device_codes(db: Session) -> None:
    cutoff = utcnow() - timedelta(days=1)
    db.execute(delete(DeviceAuthorization).where(DeviceAuthorization.expires_at < cutoff))
    db.commit()
