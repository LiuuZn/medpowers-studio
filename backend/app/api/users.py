from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import User
from ..schemas import ResetPasswordRequest, UserCreate, UserOut, UserUpdate
from ..security import hash_password
from ..services.auth_service import revoke_user_tokens

router = APIRouter(prefix="/users", tags=["用户"])


def _active_admin_count(db: Session, exclude_id: str | None = None) -> int:
    query = (
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    )
    if exclude_id:
        query = query.where(User.id != exclude_id)
    return int(db.scalar(query) or 0)


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [UserOut.model_validate(user) for user in users]


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserOut:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=payload.username,
        display_name=payload.display_name or payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_admin),
) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if (
        payload.role is not None
        and payload.role != "admin"
        and user.role == "admin"
        and _active_admin_count(db, exclude_id=user.id) == 0
    ):
        raise HTTPException(status_code=400, detail="至少保留一名启用状态的管理员")
    if (
        payload.is_active is False
        and user.role == "admin"
        and _active_admin_count(db, exclude_id=user.id) == 0
    ):
        raise HTTPException(status_code=400, detail="至少保留一名启用状态的管理员")
    if payload.is_active is False and user.id == current.id:
        raise HTTPException(status_code=400, detail="不能停用当前登录账号")

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    if payload.is_active is False:
        revoke_user_tokens(db, user.id)
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: str,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(payload.password)
    db.commit()
    # 密码重置视为安全事件：撤销该用户全部 API 访问令牌。
    revoke_user_tokens(db, user.id)
    db.refresh(user)
    return UserOut.model_validate(user)
