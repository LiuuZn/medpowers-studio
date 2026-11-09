from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..domain.constants import ANNOTATION_STATUSES
from ..models import Annotation, Case, Dataset, EvaluationJob, ExportJob, Task, TaskDataset, User
from ..schemas import AnnotationCounts, DashboardOut, TaskProgress
from .serializers import evaluation_out, export_out

router = APIRouter(prefix="/dashboard", tags=["概览"])


def _status_counts(db: Session, task_id: str | None = None) -> dict[str, int]:
    query = select(Annotation.status, func.count()).group_by(Annotation.status)
    if task_id:
        query = query.where(Annotation.task_id == task_id)
    counts = {status: 0 for status in ANNOTATION_STATUSES}
    for status, count in db.execute(query).all():
        counts[str(status)] = int(count)
    return counts


@router.get("", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DashboardOut:
    dataset_count = int(db.scalar(select(func.count()).select_from(Dataset)) or 0)
    task_count = int(db.scalar(select(func.count()).select_from(Task)) or 0)
    case_count = int(db.scalar(select(func.count()).select_from(Case)) or 0)
    overall = _status_counts(db)

    tasks = db.scalars(
        select(Task).where(Task.status == "active").order_by(Task.created_at.desc())
    ).all()
    first_dataset: dict[str, str] = {}
    for task_id, dataset_id in db.execute(
        select(TaskDataset.task_id, TaskDataset.dataset_id).order_by(TaskDataset.created_at)
    ).all():
        first_dataset.setdefault(str(task_id), str(dataset_id))
    progress = []
    for task in tasks:
        total = int(
            db.scalar(
                select(func.sum(Dataset.case_count))
                .select_from(TaskDataset)
                .join(Dataset, Dataset.id == TaskDataset.dataset_id)
                .where(TaskDataset.task_id == task.id)
            )
            or 0
        )
        counts = _status_counts(db, task.id)
        pending = max(0, total - sum(value for key, value in counts.items() if key != "pending"))
        progress.append(
            TaskProgress(
                task_id=task.id,
                task_name=task.name,
                task_type=task.task_type,
                dataset_id=first_dataset.get(task.id),
                total_cases=total,
                pending=pending,
                in_progress=counts.get("in_progress", 0),
                submitted=counts.get("submitted", 0),
                approved=counts.get("approved", 0),
                rejected=counts.get("rejected", 0),
                review_requested=counts.get("review_requested", 0),
            )
        )

    recent_exports = db.scalars(
        select(ExportJob).order_by(ExportJob.created_at.desc()).limit(5)
    ).all()
    recent_evaluations = db.scalars(
        select(EvaluationJob).order_by(EvaluationJob.created_at.desc()).limit(5)
    ).all()

    return DashboardOut(
        datasets=dataset_count,
        tasks=task_count,
        cases=case_count,
        annotations=AnnotationCounts(**overall),
        task_progress=progress,
        recent_exports=[export_out(db, job) for job in recent_exports],
        recent_evaluations=[evaluation_out(db, job) for job in recent_evaluations],
    )
