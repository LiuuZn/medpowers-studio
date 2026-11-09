from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import (
    Principal,
    get_current_user,
    require_admin,
    require_admin_or_dataset_manage,
)
from ..domain.modalities import MODALITIES
from ..models import Dataset, ScanProtocol, User
from ..schemas import ScanProtocolCreate, ScanProtocolOut, ScanProtocolUpdate

router = APIRouter(prefix="/scan-protocols", tags=["扫描流程"])


def _validate_scope(scope: list[str]) -> list[str]:
    if not scope:
        return []
    unknown = [item for item in scope if item not in MODALITIES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知模态：{', '.join(unknown)}")
    return sorted(set(scope))


@router.get("", response_model=list[ScanProtocolOut])
def list_protocols(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ScanProtocolOut]:
    query = select(ScanProtocol).order_by(ScanProtocol.sort_order, ScanProtocol.code)
    if include_inactive and user.role == "admin":
        pass
    else:
        query = query.where(ScanProtocol.is_active.is_(True))
    return [ScanProtocolOut.model_validate(item) for item in db.scalars(query).all()]


@router.post("", response_model=ScanProtocolOut, status_code=201)
def create_protocol(
    payload: ScanProtocolCreate,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin_or_dataset_manage),
) -> ScanProtocolOut:
    if db.scalar(select(ScanProtocol).where(ScanProtocol.code == payload.code)):
        raise HTTPException(status_code=409, detail="扫描流程编码已存在")
    protocol = ScanProtocol(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        modality_scope=_validate_scope(payload.modality_scope),
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(protocol)
    db.commit()
    db.refresh(protocol)
    return ScanProtocolOut.model_validate(protocol)


@router.patch("/{protocol_id}", response_model=ScanProtocolOut)
def update_protocol(
    protocol_id: str,
    payload: ScanProtocolUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ScanProtocolOut:
    protocol = db.get(ScanProtocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="扫描流程不存在")

    new_scope = (
        _validate_scope(payload.modality_scope) if payload.modality_scope is not None else None
    )
    if new_scope:
        used_modalities = set(
            db.scalars(
                select(Dataset.modality).where(Dataset.scan_protocol_id == protocol.id)
            ).all()
        )
        conflict = used_modalities - set(new_scope)
        if conflict:
            raise HTTPException(
                status_code=400,
                detail=(
                    "已有数据集使用该流程，但其模态不在适用范围内：" + ", ".join(sorted(conflict))
                ),
            )
    if payload.name is not None:
        protocol.name = payload.name
    if payload.description is not None:
        protocol.description = payload.description
    if new_scope is not None:
        protocol.modality_scope = new_scope
    if payload.sort_order is not None:
        protocol.sort_order = payload.sort_order
    if payload.is_active is not None:
        protocol.is_active = payload.is_active
    db.commit()
    db.refresh(protocol)
    return ScanProtocolOut.model_validate(protocol)


@router.delete("/{protocol_id}", status_code=204)
def delete_protocol(
    protocol_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    protocol = db.get(ScanProtocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="扫描流程不存在")
    used = int(
        db.scalar(
            select(func.count()).select_from(Dataset).where(Dataset.scan_protocol_id == protocol.id)
        )
        or 0
    )
    if used:
        raise HTTPException(status_code=409, detail="该扫描流程已被数据集使用，请改为停用")
    db.delete(protocol)
    db.commit()
