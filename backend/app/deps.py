from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .db import get_db
from .domain.constants import ROLE_ADMIN, ROLE_ANNOTATOR, ROLE_REVIEWER
from .domain.scopes import (
    SCOPE_DATA,
    SCOPE_DATASET_MANAGE,
    SCOPE_EVALUATE,
    SCOPE_EXPERIMENT,
    SCOPE_READ,
    SCOPE_REVIEW_REQUEST,
    SCOPE_WRITE,
)
from .models import User
from .security import decode_access_token
from .services.auth_service import authenticate_api_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# 二进制数据接口需要 studio:data；其余只读接口需要 studio:read。
_DATA_PATH_RE = re.compile(
    r"^/api/(?:"
    r"cases/[^/]+/slice"
    r"|exports/[^/]+/download"
    r"|tasks/[^/]+/annotations/[^/]+/mask(?:-slice)?"
    r"|datasets/[^/]+/cases/[^/]+/preview"
    r"|datasets/[^/]+/table"
    r"|blobs/[^/]+"
    r")/?$"
)

_REVIEW_REQUEST_RE = re.compile(r"^/api/annotations/[^/]+/request-review/?$")
_STUDIO_EVAL_RE = re.compile(r"^/api/studio/experiments/[^/]+/evaluations/?$")
_STUDIO_EXPERIMENT_RE = re.compile(
    r"^/api/studio/experiments(?:/[^/]+)?(?:/metrics(?::batch)?)?/?$"
)
# 数据集接入：只增不删。archive / DELETE 不匹配，继续走 studio:write + 网页管理员。
_DATASET_MANAGE_RE = re.compile(
    r"^/api/(?:"
    r"datasets(?:/[^/]+(?:/(?:import-upload|import-path|import-jobs|ready))?)?"
    r"|scan-protocols"
    r")/?$"
)


@dataclass(frozen=True)
class Principal:
    user: User
    auth_method: Literal["jwt", "token"]
    scopes: frozenset[str] | None = None
    token_id: str | None = None
    repo_key: str = ""

    @property
    def is_token(self) -> bool:
        return self.auth_method == "token"


def required_scope_for_request(request: Request) -> str:
    path = request.url.path
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return SCOPE_DATA if _DATA_PATH_RE.match(path) else SCOPE_READ
    if _REVIEW_REQUEST_RE.match(path):
        return SCOPE_REVIEW_REQUEST
    if _STUDIO_EVAL_RE.match(path):
        return SCOPE_EVALUATE
    if _STUDIO_EXPERIMENT_RE.match(path):
        return SCOPE_EXPERIMENT
    if request.method in {"POST", "PATCH", "PUT"} and _DATASET_MANAGE_RE.match(path):
        return SCOPE_DATASET_MANAGE
    return SCOPE_WRITE


def _resolve_principal(request: Request, token: str | None, db: Session) -> Principal | None:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    if not token:
        return None

    user_id = decode_access_token(token)
    if user_id:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        principal = Principal(user=user, auth_method="jwt")
    else:
        api_token = authenticate_api_token(db, token)
        if api_token is None:
            return None
        principal = Principal(
            user=api_token.user,
            auth_method="token",
            scopes=frozenset(api_token.scopes),
            token_id=api_token.id,
            repo_key=api_token.repo_key or "",
        )

    request.state.principal = principal
    return principal


def get_principal(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    principal = _resolve_principal(request, token, db)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    return principal


def get_current_user(principal: Principal = Depends(get_principal)) -> User:
    return principal.user


def get_jwt_principal(principal: Principal = Depends(get_principal)) -> Principal:
    """令牌管理、设备授权审批等敏感操作只允许网页登录会话。"""

    if principal.auth_method != "jwt":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作需要网页登录会话，不能使用 API 访问令牌",
        )
    return principal


def get_current_user_jwt(principal: Principal = Depends(get_jwt_principal)) -> User:
    return principal.user


def enforce_token_scope(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> None:
    """对 API 访问令牌统一执行 scope 校验；网页 JWT 不受 scope 限制。

    认证接口自身不走 scope 校验：登录/设备码轮询是公开接口，令牌管理由
    get_jwt_principal 单独限制。
    """

    path = request.url.path
    if path == "/api/auth" or path.startswith("/api/auth/"):
        return
    principal = _resolve_principal(request, token, db)
    if principal is None or not principal.is_token:
        return
    # 用户管理会改变账号与密码，属于会话级操作，禁止 API 令牌调用。
    if path == "/api/users" or path.startswith("/api/users/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户管理接口仅允许网页登录会话",
        )
    required = required_scope_for_request(request)
    if not principal.scopes or required not in principal.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API 访问令牌缺少 {required} 权限",
            headers={
                "WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{required}"'
            },
        )


def require_scope(required: str) -> Callable[..., Principal]:
    """显式 scope 依赖：网页 JWT 全通过；API token 必须携带指定 scope。"""

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.is_token and required not in (principal.scopes or frozenset()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API 访问令牌缺少 {required} 权限",
                headers={
                    "WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{required}"'
                },
            )
        return principal

    return dependency


def require_admin_or_dataset_manage(
    principal: Principal = Depends(get_principal),
) -> Principal:
    """网页管理员，或管理员账号持有 studio:dataset-manage 的 API 令牌。

    数据集接入是"只增不删"的写操作：令牌不继承用户角色，因此仍要求令牌
    所属账号为管理员；删除/归档等破坏性接口继续使用 require_admin。
    """

    if principal.is_token:
        if SCOPE_DATASET_MANAGE not in (principal.scopes or frozenset()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API 访问令牌缺少 {SCOPE_DATASET_MANAGE} 权限",
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="insufficient_scope", '
                        f'scope="{SCOPE_DATASET_MANAGE}"'
                    )
                },
            )
        if principal.user.role != ROLE_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="数据集管理权限要求令牌所属账号为管理员",
            )
        return principal
    if principal.user.role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限执行该操作")
    return principal


def repo_key_for(principal: Principal, requested: str = "") -> str:
    """token 认证时以 token 的 repo_key 为准；JWT 可显式传 repo_key。"""

    if principal.is_token:
        if not principal.repo_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该 API 令牌未绑定仓库标识（repo_key），请重新授权",
            )
        if requested and requested != principal.repo_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="请求中的 repo_key 与令牌绑定的仓库不一致",
            )
        return principal.repo_key
    return requested.strip()


def require_roles(*roles: str) -> Callable[..., User]:
    def dependency(principal: Principal = Depends(get_principal)) -> User:
        if principal.is_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该操作需要网页登录会话，API 访问令牌只能使用明确的 scope 接口",
            )
        if principal.user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限执行该操作")
        return principal.user

    return dependency


require_admin = require_roles(ROLE_ADMIN)
require_annotator = require_roles(ROLE_ADMIN, ROLE_ANNOTATOR)
require_reviewer = require_roles(ROLE_ADMIN, ROLE_REVIEWER)
require_any = get_current_user
