from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..domain.constants import ANNOTATION_STATUSES
from ..domain.task_types import get_task_type, normalize_label_schema
from ..models import Annotation, Case, Dataset, Task, TaskDataset, User
from ..schemas import (
    DatasetBrief,
    TaskCreate,
    TaskDatasetLinkRequest,
    TaskDatasetOut,
    TaskOut,
    TaskStats,
    TaskUpdate,
)

router = APIRouter(prefix="/tasks", tags=["任务"])


def _get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _dataset_count(db: Session, task_id: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(TaskDataset).where(TaskDataset.task_id == task_id)
        )
        or 0
    )


def _task_out(db: Session, task: Task) -> TaskOut:
    data = TaskOut.model_validate(task)
    return data.model_copy(update={"dataset_count": _dataset_count(db, task.id)})


@router.get("", response_model=list[TaskOut])
def list_tasks(
    task_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TaskOut]:
    query = select(Task).order_by(Task.created_at.desc())
    if task_type:
        query = query.where(Task.task_type == task_type)
    if status:
        query = query.where(Task.status == status)
    if search:
        like = f"%{search}%"
        query = query.where(or_(Task.name.ilike(like), Task.code.ilike(like)))
    tasks = db.scalars(query).all()
    counts = dict(
        db.execute(select(TaskDataset.task_id, func.count()).group_by(TaskDataset.task_id)).all()
    )
    result = []
    for task in tasks:
        data = TaskOut.model_validate(task)
        result.append(data.model_copy(update={"dataset_count": int(counts.get(task.id, 0))}))
    return result


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> TaskOut:
    try:
        spec = get_task_type(payload.task_type)
        schema = normalize_label_schema(payload.task_type, payload.label_schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if db.scalar(select(Task).where(Task.code == payload.code)):
        raise HTTPException(status_code=409, detail="任务编码已存在")
    task = Task(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        task_type=payload.task_type,
        dimension=spec.dimension,
        label_schema=schema,
        annotation_guide=payload.annotation_guide,
        annotation_contract=payload.annotation_contract or {},
        status="active",
        created_by_id=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.get("/{task_id}/stats", response_model=TaskStats)
def task_stats(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskStats:
    task = _get_task(db, task_id)
    total = int(
        db.scalar(
            select(func.sum(Dataset.case_count))
            .select_from(TaskDataset)
            .join(Dataset, Dataset.id == TaskDataset.dataset_id)
            .where(TaskDataset.task_id == task.id)
        )
        or 0
    )
    counts = {status: 0 for status in ANNOTATION_STATUSES}
    for status, count in db.execute(
        select(Annotation.status, func.count())
        .where(Annotation.task_id == task.id)
        .group_by(Annotation.status)
    ).all():
        counts[str(status)] = int(count)
    pending = max(0, total - sum(value for key, value in counts.items() if key != "pending"))
    return TaskStats(
        task_id=task.id,
        total_cases=total,
        pending=pending,
        in_progress=counts.get("in_progress", 0),
        submitted=counts.get("submitted", 0),
        approved=counts.get("approved", 0),
        rejected=counts.get("rejected", 0),
        review_requested=counts.get("review_requested", 0),
    )


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskOut:
    return _task_out(db, _get_task(db, task_id))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> TaskOut:
    task = _get_task(db, task_id)
    if payload.label_schema is not None:
        annotation_exists = db.scalar(
            select(func.count()).select_from(Annotation).where(Annotation.task_id == task.id)
        )
        if annotation_exists:
            raise HTTPException(status_code=409, detail="任务已有标注，不能修改标签体系")
        try:
            task.label_schema = normalize_label_schema(task.task_type, payload.label_schema)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.name is not None:
        task.name = payload.name
    if payload.description is not None:
        task.description = payload.description
    if payload.annotation_guide is not None:
        task.annotation_guide = payload.annotation_guide
    if payload.annotation_contract is not None:
        task.annotation_contract = payload.annotation_contract
    if payload.status is not None:
        task.status = payload.status
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.get("/{task_id}/datasets", response_model=list[TaskDatasetOut])
def list_task_datasets(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TaskDatasetOut]:
    _get_task(db, task_id)
    links = db.scalars(
        select(TaskDataset)
        .where(TaskDataset.task_id == task_id)
        .options(joinedload(TaskDataset.dataset))
        .order_by(TaskDataset.created_at)
    ).all()
    return [
        TaskDatasetOut(
            id=link.id,
            created_at=link.created_at,
            dataset=DatasetBrief.model_validate(link.dataset),
        )
        for link in links
    ]


@router.post("/{task_id}/datasets", response_model=TaskDatasetOut, status_code=201)
def link_dataset(
    task_id: str,
    payload: TaskDatasetLinkRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> TaskDatasetOut:
    task = _get_task(db, task_id)
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="已归档任务不能关联数据集")
    dataset = db.get(Dataset, payload.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.status != "ready":
        raise HTTPException(status_code=400, detail="数据集尚未就绪，不能关联任务")
    if dataset.dimension != task.dimension:
        raise HTTPException(
            status_code=400,
            detail=(
                f"维度不匹配：任务需要 {task.dimension.upper()} 数据，"
                f"数据集是 {dataset.dimension.upper()} 数据"
            ),
        )
    exists = db.scalar(
        select(TaskDataset).where(
            TaskDataset.task_id == task.id, TaskDataset.dataset_id == dataset.id
        )
    )
    if exists:
        raise HTTPException(status_code=409, detail="该数据集已关联到此任务")
    link = TaskDataset(task_id=task.id, dataset_id=dataset.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return TaskDatasetOut(
        id=link.id,
        created_at=link.created_at,
        dataset=DatasetBrief.model_validate(dataset),
    )


@router.delete("/{task_id}/datasets/{dataset_id}", status_code=204)
def unlink_dataset(
    task_id: str,
    dataset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    link = db.scalar(
        select(TaskDataset).where(
            TaskDataset.task_id == task_id, TaskDataset.dataset_id == dataset_id
        )
    )
    if not link:
        raise HTTPException(status_code=404, detail="关联不存在")
    annotations = int(
        db.scalar(
            select(func.count())
            .select_from(Annotation)
            .join(Case, Case.id == Annotation.case_id)
            .where(Annotation.task_id == task_id, Case.dataset_id == dataset_id)
        )
        or 0
    )
    if annotations:
        raise HTTPException(status_code=409, detail="该数据集已有标注，不能解除关联")
    db.delete(link)
    db.commit()
