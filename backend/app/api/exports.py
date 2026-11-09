from __future__ import annotations

import shutil
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..domain.constants import ANNOTATION_STATUSES
from ..models import Dataset, ExportJob, Task, TaskDataset, User
from ..schemas import ExportCreate, ExportOut
from ..services import storage
from ..services.export_service import run_export
from .serializers import export_out

router = APIRouter(prefix="/exports", tags=["导出"])


def _get_job(db: Session, job_id: str) -> ExportJob:
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="导出作业不存在")
    return job


@router.get("", response_model=list[ExportOut])
def list_exports(
    task_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ExportOut]:
    query = select(ExportJob).order_by(ExportJob.created_at.desc())
    if task_id:
        query = query.where(ExportJob.task_id == task_id)
    if status:
        query = query.where(ExportJob.status == status)
    jobs = db.scalars(query).all()
    return [export_out(db, job) for job in jobs]


@router.post("", response_model=ExportOut, status_code=201)
def create_export(
    payload: ExportCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> ExportOut:
    task = db.get(Task, payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="任务已归档，不能导出")

    dataset_ids = list(dict.fromkeys(payload.dataset_ids))
    linked = set(
        db.scalars(select(TaskDataset.dataset_id).where(TaskDataset.task_id == task.id)).all()
    )
    invalid = set(dataset_ids) - linked
    if invalid:
        raise HTTPException(status_code=400, detail="所选数据集未关联到该任务")
    datasets = db.scalars(select(Dataset).where(Dataset.id.in_(dataset_ids))).all()
    if len(datasets) != len(dataset_ids):
        raise HTTPException(status_code=404, detail="部分数据集不存在")
    if any(d.dimension != task.dimension for d in datasets):
        raise HTTPException(status_code=400, detail="数据集维度与任务不匹配")

    statuses = list(dict.fromkeys(payload.include_statuses))
    if not statuses:
        raise HTTPException(status_code=400, detail="至少选择一种纳入导出的标注状态")
    unknown = [status for status in statuses if status not in ANNOTATION_STATUSES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知标注状态：{', '.join(unknown)}")

    job = ExportJob(
        name=payload.name,
        task_id=task.id,
        dataset_ids=dataset_ids,
        format=payload.format,
        split_config=payload.split_config,
        include_statuses=statuses,
        status="queued",
        created_by_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    run_export(db, job.id)
    db.refresh(job)
    return export_out(db, job)


@router.get("/{job_id}", response_model=ExportOut)
def get_export(
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ExportOut:
    return export_out(db, _get_job(db, job_id))


@router.get("/{job_id}/manifest")
def get_manifest(
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    job = _get_job(db, job_id)
    manifest = storage.resolve_key(job.manifest_path) if job.manifest_path else None
    if not manifest or not manifest.exists():
        raise HTTPException(status_code=404, detail="导出清单不存在")
    return FileResponse(manifest, media_type="application/json", filename="manifest.json")


@router.get("/{job_id}/download")
def download_export(
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    job = _get_job(db, job_id)
    if job.status != "succeeded" or not job.output_dir:
        raise HTTPException(status_code=400, detail="导出尚未成功完成")
    source = storage.resolve_key(job.output_dir)
    if not source.exists():
        raise HTTPException(status_code=404, detail="导出目录不存在")
    zip_path = storage.tmp_dir(f"download_export_{job.id}") / f"export_{job.id}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source))

    def _cleanup() -> None:
        shutil.rmtree(zip_path.parent, ignore_errors=True)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{job.name or job.id}.zip",
        background=BackgroundTask(_cleanup),
    )
