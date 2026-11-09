from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..domain.constants import ROLE_NAMES
from ..domain.data_kinds import public_data_kinds
from ..domain.modalities import public_modalities
from ..domain.task_types import public_task_types
from ..models import User

router = APIRouter(prefix="/meta", tags=["元数据"])


@router.get("/modalities")
def modalities(_: User = Depends(get_current_user)) -> list[dict]:
    return public_modalities()


@router.get("/task-types")
def task_types(_: User = Depends(get_current_user)) -> list[dict]:
    return public_task_types()


@router.get("/data-kinds")
def data_kinds(_: User = Depends(get_current_user)) -> list[dict]:
    return public_data_kinds()


@router.get("/roles")
def roles(_: User = Depends(get_current_user)) -> list[dict]:
    return [{"code": code, "name": name} for code, name in ROLE_NAMES.items()]
