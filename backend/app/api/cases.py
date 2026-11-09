from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Case, User
from ..schemas import CaseOut, SliceInfo, TableInfo, TablePage
from ..services import imaging, storage
from ..services.formats import table as table_formats

router = APIRouter(prefix="/cases", tags=["病例影像"])


def _get_case(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    return case


@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CaseOut:
    return CaseOut.model_validate(_get_case(db, case_id))


@router.get("/{case_id}/slice-info", response_model=SliceInfo)
def slice_info(
    case_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SliceInfo:
    case = _get_case(db, case_id)
    try:
        return SliceInfo(**imaging.slice_info(case))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"影像读取失败：{exc}") from exc


def _table_case(db: Session, case_id: str) -> Case:
    case = _get_case(db, case_id)
    if case.data_kind != "table":
        raise HTTPException(status_code=400, detail="该病例不是表格数据")
    return case


@router.get("/{case_id}/table-info", response_model=TableInfo)
def table_info(
    case_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TableInfo:
    case = _table_case(db, case_id)
    try:
        return TableInfo(**table_formats.table_info(storage.case_image_path(case)))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"表格读取失败：{exc}") from exc


@router.get("/{case_id}/table", response_model=TablePage)
def table_page(
    case_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TablePage:
    case = _table_case(db, case_id)
    try:
        payload = table_formats.read_table_page(storage.case_image_path(case), offset, limit)
        return TablePage(**payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"表格读取失败：{exc}") from exc


@router.get("/{case_id}/slice")
def slice_png(
    case_id: str,
    axis: str = Query(default="axial"),
    index: int = Query(default=0, ge=0),
    window: float | None = None,
    level: float | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    case = _get_case(db, case_id)
    try:
        content = imaging.slice_png(case, axis=axis, index=index, window=window, level=level)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"影像切片失败：{exc}") from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=60"},
    )
