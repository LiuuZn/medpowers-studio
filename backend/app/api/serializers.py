from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import EvaluationJob, ExportJob, Task
from ..schemas import EvaluationOut, ExportOut
from ..services import storage


def export_out(db: Session, job: ExportJob) -> ExportOut:
    task = db.get(Task, job.task_id)
    return ExportOut(
        id=job.id,
        name=job.name,
        task_id=job.task_id,
        task_name=task.name if task else "",
        dataset_ids=job.dataset_ids or [],
        format=job.format,
        split_config=job.split_config or {},
        include_statuses=job.include_statuses or [],
        status=job.status,
        output_dir=str(storage.resolve_key(job.output_dir)) if job.output_dir else "",
        manifest_path=(
            str(storage.resolve_key(job.manifest_path)) if job.manifest_path else None
        ),
        summary=job.summary or {},
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def evaluation_out(db: Session, job: EvaluationJob) -> EvaluationOut:
    task = db.get(Task, job.task_id)
    return EvaluationOut(
        id=job.id,
        name=job.name,
        task_id=job.task_id,
        task_name=task.name if task else "",
        dataset_ids=job.dataset_ids or [],
        gt_statuses=job.gt_statuses or [],
        metrics_config=job.metrics_config or {},
        status=job.status,
        report_path=str(storage.resolve_key(job.report_path)) if job.report_path else None,
        summary=job.summary or {},
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
