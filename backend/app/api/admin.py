from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_admin
from ..models import User
from ..services import storage

router = APIRouter(prefix="/admin", tags=["管理"])


@router.get("/storage/usage")
def storage_usage(_: User = Depends(require_admin)) -> dict[str, int]:
    return storage.storage_usage()
