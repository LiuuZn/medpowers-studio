from __future__ import annotations

import json
import shutil
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..domain.constants import ANNOTATION_STATUSES
from ..models import Dataset, EvaluationJob, Task, TaskDataset, User
from ..schemas import EvaluationOut
from ..services import storage
from ..services.evaluation_service import run_evaluation
from ..services.import_service import extract_zip, save_upload
from .serializers import evaluation_out

router = APIRouter(prefix="/evaluations", tags=["评估"])


def _get_job(db: Session, job_id: str) -> EvaluationJob:
    job = db.get(EvaluationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="评估作业不存在")
    return job


def _parse_list(raw: str, field: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field} 不是合法 JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=400, detail=f"{field} 必须是字符串数组")
    return value


def _parse_dict(raw: str, field: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field} 不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{field} 必须是 JSON 对象")
    return value


@router.get("", response_model=list[EvaluationOut])
def list_evaluations(
    task_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[EvaluationOut]:
    query = select(EvaluationJob).order_by(EvaluationJob.created_at.desc())
    if task_id:
        query = query.where(EvaluationJob.task_id == task_id)
    if status:
        query = query.where(EvaluationJob.status == status)
    return [evaluation_out(db, job) for job in db.scalars(query).all()]


@router.post("", response_model=EvaluationOut, status_code=201)
def create_evaluation(
    name: str = Form(...),
    task_id: str = Form(...),
    dataset_ids: str = Form(...),
    gt_statuses: str = Form(default='["approved"]'),
    metrics_config: str = Form(default="{}"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> EvaluationOut:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    ids = _parse_list(dataset_ids, "dataset_ids")
    statuses = _parse_list(gt_statuses, "gt_statuses")
    config = _parse_dict(metrics_config, "metrics_config")
    if not ids:
        raise HTTPException(status_code=400, detail="至少选择一个数据集")
    if not statuses:
        raise HTTPException(status_code=400, detail="至少选择一种金标准状态")
    unknown = [status for status in statuses if status not in ANNOTATION_STATUSES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知标注状态：{', '.join(unknown)}")

    linked = set(
        db.scalars(select(TaskDataset.dataset_id).where(TaskDataset.task_id == task.id)).all()
    )
    invalid = set(ids) - linked
    if invalid:
        raise HTTPException(status_code=400, detail="所选数据集未关联到该任务")
    datasets = db.scalars(select(Dataset).where(Dataset.id.in_(ids))).all()
    if len(datasets) != len(ids):
        raise HTTPException(status_code=404, detail="部分数据集不存在")
    if any(d.dimension != task.dimension for d in datasets):
        raise HTTPException(status_code=400, detail="数据集维度与任务不匹配")

    job = EvaluationJob(
        name=name,
        task_id=task.id,
        dataset_ids=ids,
        gt_statuses=statuses,
        metrics_config=config,
        status="queued",
        created_by_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_dir = storage.evaluation_dir(job.id)
    try:
        zip_path = job_dir / "predictions.zip"
        save_upload(file, zip_path, get_settings().max_upload_mb)
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("预测结果必须是 ZIP 压缩包")
        pred_dir = job_dir / "predictions"
        pred_dir.mkdir(parents=True, exist_ok=True)
        extract_zip(zip_path, pred_dir)
        job.prediction_path = storage.key_for(pred_dir)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.delete(job)
        db.commit()
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"预测结果上传失败：{exc}") from exc

    run_evaluation(db, job.id)
    db.refresh(job)
    return evaluation_out(db, job)


@router.get("/{job_id}", response_model=EvaluationOut)
def get_evaluation(
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EvaluationOut:
    return evaluation_out(db, _get_job(db, job_id))


@router.get("/{job_id}/report")
def get_report(
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    job = _get_job(db, job_id)
    report = storage.resolve_key(job.report_path) if job.report_path else None
    if not report or not report.exists():
        raise HTTPException(status_code=404, detail="评估报告不存在")
    return FileResponse(report, media_type="application/json", filename="report.json")
