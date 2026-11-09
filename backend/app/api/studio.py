"""训练仓库/插件对接 API。

设计口径：
- 任务（Task）= 模型；一个训练仓库可通过 repo_key 对应多个 task。
- git 中的 EXP-<NNN> 记录是实验事实的权威；本模块只做只读镜像与可视化。
- 插件 token 只允许：推送实验/指标、外部评测结果、申请标注复核；不能写标注内容。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, get_current_user, get_principal, repo_key_for
from ..domain.constants import (
    ANNOTATION_APPROVED,
    ANNOTATION_STATUSES,
    EXPERIMENT_STATUSES,
    REVIEW_REQUEST_STATUSES,
)
from ..domain.task_types import get_task_type, public_task_types
from ..models import (
    Annotation,
    AnnotationReviewRequest,
    Case,
    Dataset,
    Experiment,
    ExternalEvaluation,
    MetricPoint,
    Task,
    TaskDataset,
    User,
)
from ..schemas import (
    AnnotationReviewRequestOut,
    ExperimentCreate,
    ExperimentOut,
    ExperimentUpdate,
    ExternalEvaluationIn,
    ExternalEvaluationOut,
    MetricBatch,
    MetricPointOut,
    StudioChangeItem,
    StudioChangesOut,
    StudioDatasetRef,
    StudioMetaOut,
    StudioReadiness,
    StudioTaskSummary,
)
from ..services import storage

router = APIRouter(prefix="/studio", tags=["训练仓库对接"])

SCHEMA_VERSION = "2026-11-07"
METRIC_SCHEMA_VERSION = "1"
MAX_METRIC_POINTS = 5000
CHANGE_LIMIT = 500


def _get_task(db: Session, code_or_id: str) -> Task:
    task = db.scalar(
        select(Task).where(or_(Task.code == code_or_id, Task.id == code_or_id))
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _task_total_cases(db: Session, task_id: str) -> int:
    return int(
        db.scalar(
            select(func.sum(Dataset.case_count))
            .select_from(TaskDataset)
            .join(Dataset, Dataset.id == TaskDataset.dataset_id)
            .where(TaskDataset.task_id == task_id)
        )
        or 0
    )


def _task_counts(db: Session, task_id: str, total_cases: int) -> dict[str, int]:
    counts = {status: 0 for status in ANNOTATION_STATUSES}
    for status, count in db.execute(
        select(Annotation.status, func.count())
        .where(Annotation.task_id == task_id)
        .group_by(Annotation.status)
    ).all():
        counts[str(status)] = int(count)
    non_pending = sum(value for key, value in counts.items() if key != "pending")
    counts["pending"] = max(0, total_cases - non_pending)
    return counts


def _contract_complete(contract: dict[str, Any] | None) -> bool:
    if not contract:
        return False
    for key in ("produced_by", "rule", "tolerance"):
        if str(contract.get(key, "")).strip() in ("", "None", "TODO"):
            return False
    verified = contract.get("verified")
    if isinstance(verified, bool):
        return verified
    return str(verified or "").strip().lower() not in ("", "false", "0", "no", "否", "none", "todo")


def _class_case_counts(db: Session, task: Task) -> dict[str, int]:
    """已通过标注中，各类别至少出现一次的病例数（尽力而为，旧标注可能缺数据）。"""

    rows = db.execute(
        select(Annotation.data)
        .where(Annotation.task_id == task.id, Annotation.status == ANNOTATION_APPROVED)
    ).all()
    kind = get_task_type(task.task_type).annotation_kind
    counts: dict[str, int] = {}
    for (data,) in rows:
        data = data or {}
        if kind == "mask":
            labels = data.get("classes_present") or []
        elif kind == "keyframe":
            labels = [item.get("label_id") for item in data.get("frames", [])]
        else:
            labels = [item.get("label_id") for item in data.get("boxes", [])]
        for label in set(labels):
            if label is None:
                continue
            key = str(int(label))
            counts[key] = counts.get(key, 0) + 1
    return counts


def _qc_issues(db: Session, task: Task, datasets: list[Dataset]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    kind = get_task_type(task.task_type).annotation_kind
    approved = db.scalars(
        select(Annotation).where(
            Annotation.task_id == task.id, Annotation.status == ANNOTATION_APPROVED
        )
    ).all()

    missing_mask = 0
    empty_annotation = 0
    for annotation in approved:
        if kind == "mask":
            if not annotation.mask_path or not storage.resolve_key(annotation.mask_path).exists():
                missing_mask += 1
        else:
            key = "frames" if kind == "keyframe" else "boxes"
            if not (annotation.data or {}).get(key):
                empty_annotation += 1
    if missing_mask:
        issues.append(
            {
                "code": "approved_missing_mask",
                "message": "已通过标注缺少掩膜文件",
                "count": missing_mask,
            }
        )
    if empty_annotation:
        issues.append(
            {
                "code": "approved_empty_annotation",
                "message": "已通过标注内容为空（关键帧/检测框）",
                "count": empty_annotation,
            }
        )

    duplicates = db.execute(
        select(Case.case_uid, func.count())
        .join(TaskDataset, TaskDataset.dataset_id == Case.dataset_id)
        .where(TaskDataset.task_id == task.id)
        .group_by(Case.case_uid)
        .having(func.count() > 1)
    ).all()
    if duplicates:
        issues.append(
            {
                "code": "duplicate_case_uid",
                "message": "同一任务关联的数据集中存在重复 case_uid",
                "count": len(duplicates),
            }
        )

    not_ready = [dataset.code for dataset in datasets if dataset.status != "ready"]
    if not_ready:
        issues.append(
            {
                "code": "dataset_not_ready",
                "message": "任务关联的数据集未就绪",
                "count": len(not_ready),
                "datasets": not_ready,
            }
        )
    return issues


def _task_summary(db: Session, task: Task) -> StudioTaskSummary:
    total = _task_total_cases(db, task.id)
    counts = _task_counts(db, task.id, total)
    return StudioTaskSummary(
        id=task.id,
        code=task.code,
        name=task.name,
        task_type=task.task_type,
        dimension=task.dimension,
        status=task.status,
        dataset_count=int(
            db.scalar(
                select(func.count())
                .select_from(TaskDataset)
                .where(TaskDataset.task_id == task.id)
            )
            or 0
        ),
        total_cases=total,
        approved=counts.get("approved", 0),
        review_requested=counts.get("review_requested", 0),
        annotation_contract_complete=_contract_complete(task.annotation_contract),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _experiment_out(experiment: Experiment) -> ExperimentOut:
    return ExperimentOut(
        id=experiment.id,
        repo_key=experiment.repo_key,
        exp_id=experiment.exp_id,
        task_id=experiment.task_id,
        task_code=experiment.task_code,
        status=experiment.status,
        title=experiment.title,
        machine=experiment.machine,
        git_commit=experiment.git_commit,
        config=experiment.config or {},
        notes=experiment.notes,
        record_path=experiment.record_path,
        record_sha256=experiment.record_sha256,
        started_at=experiment.started_at,
        ended_at=experiment.ended_at,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )


def _get_experiment(
    db: Session, principal: Principal, exp_id: str, repo_key: str = ""
) -> Experiment:
    effective = repo_key_for(principal, repo_key)
    query = select(Experiment).where(Experiment.exp_id == exp_id)
    if effective:
        query = query.where(Experiment.repo_key == effective)
    rows = db.scalars(query.order_by(Experiment.created_at.desc())).all()
    if not rows:
        raise HTTPException(status_code=404, detail="实验镜像不存在，请先推送实验")
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail="存在多个仓库的同名实验，请指定 repo_key")
    return rows[0]


def _metric_out(point: MetricPoint) -> MetricPointOut:
    return MetricPointOut(
        name=point.name,
        value=point.value,
        step=point.step,
        epoch=point.epoch,
        split=point.split,
        class_label=point.class_label,
        timestamp=point.timestamp,
        tags=point.tags or {},
        source=point.source,
        extra=point.extra or {},
    )


@router.get("/meta", response_model=StudioMetaOut)
def studio_meta(
    request: Request,
    _: User = Depends(get_current_user),
) -> StudioMetaOut:
    return StudioMetaOut(
        service=request.app.title,
        version=request.app.version,
        api_prefix=get_settings().api_prefix,
        schema_version=SCHEMA_VERSION,
        task_types=public_task_types(),
        metric_schema_version=METRIC_SCHEMA_VERSION,
        capabilities={
            "experiments": True,
            "metrics": True,
            "external_evaluations": True,
            "review_requests": True,
            "native_evaluations": False,
            "export_package": False,
        },
    )


@router.get("/tasks", response_model=list[StudioTaskSummary])
def studio_tasks(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[StudioTaskSummary]:
    query = select(Task).order_by(Task.code)
    if status:
        query = query.where(Task.status == status)
    return [_task_summary(db, task) for task in db.scalars(query).all()]


@router.get("/tasks/{code}/readiness", response_model=StudioReadiness)
def studio_task_readiness(
    code: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StudioReadiness:
    task = _get_task(db, code)
    datasets = db.scalars(
        select(Dataset)
        .join(TaskDataset, TaskDataset.dataset_id == Dataset.id)
        .where(TaskDataset.task_id == task.id)
        .order_by(Dataset.code)
    ).all()
    total = sum(int(dataset.case_count) for dataset in datasets)
    counts = _task_counts(db, task.id, total)
    last_updated = db.scalar(
        select(func.max(Annotation.updated_at)).where(Annotation.task_id == task.id)
    )
    return StudioReadiness(
        task=_task_summary(db, task),
        datasets=[
            StudioDatasetRef(
                id=dataset.id,
                code=dataset.code,
                name=dataset.name,
                modality=dataset.modality,
                dimension=dataset.dimension,
                data_kind=dataset.data_kind,
                status=dataset.status,
                case_count=dataset.case_count,
            )
            for dataset in datasets
        ],
        counts=counts,
        total_cases=total,
        class_case_counts=_class_case_counts(db, task),
        qc_issues=_qc_issues(db, task, list(datasets)),
        annotation_contract=task.annotation_contract or {},
        annotation_contract_complete=_contract_complete(task.annotation_contract),
        last_updated=last_updated,
    )


@router.get("/changes", response_model=StudioChangesOut)
def studio_changes(
    since: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StudioChangesOut:
    cursor = datetime.now(UTC)
    if since is not None:
        since = _as_utc(since)
        annotations = db.execute(
            select(Annotation, Task, Case)
            .join(Task, Task.id == Annotation.task_id)
            .join(Case, Case.id == Annotation.case_id)
            .where(Annotation.updated_at > since)
            .order_by(Annotation.updated_at)
            .limit(CHANGE_LIMIT)
        ).all()
        experiments = db.scalars(
            select(Experiment)
            .where(Experiment.updated_at > since)
            .order_by(Experiment.updated_at)
            .limit(CHANGE_LIMIT)
        ).all()
    else:
        annotations = db.execute(
            select(Annotation, Task, Case)
            .join(Task, Task.id == Annotation.task_id)
            .join(Case, Case.id == Annotation.case_id)
            .order_by(Annotation.updated_at.desc())
            .limit(CHANGE_LIMIT)
        ).all()
        experiments = db.scalars(
            select(Experiment).order_by(Experiment.updated_at.desc()).limit(CHANGE_LIMIT)
        ).all()

    items = [
        StudioChangeItem(
            kind="annotation",
            id=annotation.id,
            status=annotation.status,
            task_id=task.id,
            task_code=task.code,
            case_id=case.id,
            case_uid=case.case_uid,
            version=annotation.version,
            updated_at=annotation.updated_at,
        )
        for annotation, task, case in annotations
    ]
    items.extend(
        StudioChangeItem(
            kind="experiment",
            id=experiment.id,
            status=experiment.status,
            task_id=experiment.task_id,
            task_code=experiment.task_code,
            repo_key=experiment.repo_key,
            exp_id=experiment.exp_id,
            updated_at=experiment.updated_at,
        )
        for experiment in experiments
    )
    return StudioChangesOut(
        cursor=cursor,
        since=since,
        items=items,
        truncated=len(items) >= CHANGE_LIMIT,
    )


@router.post("/experiments", response_model=ExperimentOut)
def upsert_experiment(
    payload: ExperimentCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ExperimentOut:
    repo_key = repo_key_for(principal, payload.repo_key)
    if not repo_key:
        raise HTTPException(status_code=400, detail="缺少 repo_key")
    task = _get_task(db, payload.task_code)
    experiment = db.scalar(
        select(Experiment).where(
            Experiment.repo_key == repo_key, Experiment.exp_id == payload.exp_id
        )
    )
    if experiment is None:
        experiment = Experiment(
            repo_key=repo_key,
            exp_id=payload.exp_id,
            task_id=task.id,
            task_code=task.code,
        )
        db.add(experiment)
    experiment.task_id = task.id
    experiment.task_code = task.code
    experiment.status = payload.status
    if payload.title:
        experiment.title = payload.title
    if payload.machine:
        experiment.machine = payload.machine
    if payload.git_commit:
        experiment.git_commit = payload.git_commit
    if payload.config:
        experiment.config = payload.config
    if payload.notes:
        experiment.notes = payload.notes
    if payload.record_path:
        experiment.record_path = payload.record_path
    if payload.record_sha256:
        experiment.record_sha256 = payload.record_sha256
    if payload.started_at:
        experiment.started_at = payload.started_at
    if payload.ended_at:
        experiment.ended_at = payload.ended_at
    if experiment.status == "running" and not experiment.started_at:
        experiment.started_at = datetime.now(UTC)
    if experiment.status in ("done", "interrupted", "cancelled") and not experiment.ended_at:
        experiment.ended_at = datetime.now(UTC)
    db.commit()
    db.refresh(experiment)
    return _experiment_out(experiment)


@router.patch("/experiments/{exp_id}", response_model=ExperimentOut)
def update_experiment(
    exp_id: str,
    payload: ExperimentUpdate,
    repo_key: str = Query(default=""),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ExperimentOut:
    experiment = _get_experiment(db, principal, exp_id, repo_key)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        status = str(data["status"])
        if status not in EXPERIMENT_STATUSES:
            raise HTTPException(status_code=400, detail="非法实验状态")
        experiment.status = status
        if status == "running" and not experiment.started_at:
            experiment.started_at = datetime.now(UTC)
        if status in ("done", "interrupted", "cancelled") and not experiment.ended_at:
            experiment.ended_at = datetime.now(UTC)
    for field in (
        "title",
        "machine",
        "git_commit",
        "config",
        "notes",
        "record_path",
        "record_sha256",
        "started_at",
        "ended_at",
    ):
        if field in data:
            setattr(experiment, field, data[field])
    db.commit()
    db.refresh(experiment)
    return _experiment_out(experiment)


@router.get("/experiments/{exp_id}", response_model=ExperimentOut)
def get_experiment(
    exp_id: str,
    repo_key: str = Query(default=""),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ExperimentOut:
    return _experiment_out(_get_experiment(db, principal, exp_id, repo_key))


@router.post("/experiments/{exp_id}/metrics:batch")
def push_metrics(
    exp_id: str,
    payload: MetricBatch,
    repo_key: str = Query(default=""),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    experiment = _get_experiment(db, principal, exp_id, repo_key)
    points = payload.points
    if len(points) > MAX_METRIC_POINTS:
        raise HTTPException(
            status_code=400, detail=f"单批指标不能超过 {MAX_METRIC_POINTS} 点"
        )
    if not points:
        return {"accepted": 0, "experiment_id": experiment.id}

    names = {point.name for point in points}
    existing = db.scalars(
        select(MetricPoint).where(
            MetricPoint.experiment_id == experiment.id, MetricPoint.name.in_(names)
        )
    ).all()
    index = {
        (item.name, item.split, item.class_label, item.step): item for item in existing
    }
    for point in points:
        if not math.isfinite(point.value):
            raise HTTPException(status_code=400, detail=f"指标 {point.name} 的值不是有限数")
        key = (point.name, point.split, point.class_label, point.step)
        item = index.get(key)
        if item is None:
            item = MetricPoint(
                experiment_id=experiment.id,
                name=point.name,
                split=point.split,
                class_label=point.class_label,
                step=point.step,
            )
            db.add(item)
            index[key] = item
        item.value = float(point.value)
        item.epoch = point.epoch
        item.timestamp = point.timestamp or datetime.now(UTC)
        item.tags = point.tags
        item.source = point.source
        item.extra = point.extra
    db.commit()
    return {
        "accepted": len(points),
        "experiment_id": experiment.id,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
    }


@router.get("/experiments/{exp_id}/metrics", response_model=list[MetricPointOut])
def list_metrics(
    exp_id: str,
    name: str | None = None,
    split: str | None = None,
    class_label: str | None = Query(default=None, alias="class"),
    step_from: int | None = None,
    step_to: int | None = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    repo_key: str = Query(default=""),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[MetricPointOut]:
    experiment = _get_experiment(db, principal, exp_id, repo_key)
    query = select(MetricPoint).where(MetricPoint.experiment_id == experiment.id)
    if name:
        query = query.where(MetricPoint.name == name)
    if split:
        query = query.where(MetricPoint.split == split)
    if class_label:
        query = query.where(MetricPoint.class_label == class_label)
    if step_from is not None:
        query = query.where(MetricPoint.step >= step_from)
    if step_to is not None:
        query = query.where(MetricPoint.step <= step_to)
    points = db.scalars(
        query.order_by(MetricPoint.name, MetricPoint.step, MetricPoint.timestamp).limit(limit)
    ).all()
    return [_metric_out(point) for point in points]


@router.get("/tasks/{code}/experiments", response_model=list[ExperimentOut])
def list_task_experiments(
    code: str,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ExperimentOut]:
    task = _get_task(db, code)
    query = select(Experiment).where(Experiment.task_id == task.id)
    if status:
        query = query.where(Experiment.status == status)
    experiments = db.scalars(
        query.order_by(Experiment.updated_at.desc()).limit(limit)
    ).all()
    return [_experiment_out(experiment) for experiment in experiments]


@router.post("/experiments/{exp_id}/evaluations", response_model=ExternalEvaluationOut)
def push_evaluation(
    exp_id: str,
    payload: ExternalEvaluationIn,
    repo_key: str = Query(default=""),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ExternalEvaluationOut:
    experiment = _get_experiment(db, principal, exp_id, repo_key)
    if payload.source != "external":
        raise HTTPException(
            status_code=400,
            detail="P0 该接口只接受 source=external；Studio 原生评测后续使用独立流程",
        )
    if payload.task_code and payload.task_code != experiment.task_code:
        raise HTTPException(status_code=400, detail="评测任务与实验镜像的任务不一致")
    evaluation = db.scalar(
        select(ExternalEvaluation).where(
            ExternalEvaluation.experiment_id == experiment.id,
            ExternalEvaluation.eval_id == payload.eval_id,
        )
    )
    if evaluation is None:
        evaluation = ExternalEvaluation(
            experiment_id=experiment.id, eval_id=payload.eval_id
        )
        db.add(evaluation)
    evaluation.source = payload.source
    evaluation.task_code = payload.task_code or experiment.task_code
    evaluation.gt_statuses = payload.gt_statuses
    evaluation.dataset_version = payload.dataset_version
    evaluation.summary = payload.summary
    evaluation.per_case = payload.per_case
    evaluation.report_sha256 = payload.report_sha256
    if payload.created_at:
        evaluation.created_at = payload.created_at
    db.commit()
    db.refresh(evaluation)
    return ExternalEvaluationOut(
        id=evaluation.id,
        experiment_id=evaluation.experiment_id,
        eval_id=evaluation.eval_id,
        source=evaluation.source,
        task_code=evaluation.task_code,
        gt_statuses=evaluation.gt_statuses or [],
        dataset_version=evaluation.dataset_version,
        summary=evaluation.summary or {},
        per_case=evaluation.per_case or [],
        report_sha256=evaluation.report_sha256,
        created_at=evaluation.created_at,
    )


@router.get(
    "/experiments/{exp_id}/evaluations",
    response_model=list[ExternalEvaluationOut],
)
def list_evaluations(
    exp_id: str,
    repo_key: str = Query(default=""),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[ExternalEvaluationOut]:
    experiment = _get_experiment(db, principal, exp_id, repo_key)
    evaluations = db.scalars(
        select(ExternalEvaluation)
        .where(ExternalEvaluation.experiment_id == experiment.id)
        .order_by(ExternalEvaluation.created_at.desc())
    ).all()
    return [
        ExternalEvaluationOut(
            id=item.id,
            experiment_id=item.experiment_id,
            eval_id=item.eval_id,
            source=item.source,
            task_code=item.task_code,
            gt_statuses=item.gt_statuses or [],
            dataset_version=item.dataset_version,
            summary=item.summary or {},
            per_case=item.per_case or [],
            report_sha256=item.report_sha256,
            created_at=item.created_at,
        )
        for item in evaluations
    ]


@router.get(
    "/review-requests",
    response_model=list[AnnotationReviewRequestOut],
)
def list_review_requests(
    status: str | None = Query(default="open"),
    task_code: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AnnotationReviewRequestOut]:
    if status and status not in REVIEW_REQUEST_STATUSES:
        raise HTTPException(status_code=400, detail="非法复核状态")
    query = (
        select(AnnotationReviewRequest, Annotation, Task, Case)
        .join(Annotation, Annotation.id == AnnotationReviewRequest.annotation_id)
        .join(Task, Task.id == Annotation.task_id)
        .join(Case, Case.id == Annotation.case_id)
    )
    if status:
        query = query.where(AnnotationReviewRequest.status == status)
    if task_code:
        query = query.where(Task.code == task_code)
    rows = db.execute(
        query.order_by(AnnotationReviewRequest.requested_at.desc()).limit(limit)
    ).all()
    result = []
    for request, annotation, task, case in rows:
        user = db.get(User, request.user_id) if request.user_id else None
        result.append(
            AnnotationReviewRequestOut(
                id=request.id,
                annotation_id=request.annotation_id,
                task_id=task.id,
                task_code=task.code,
                case_id=case.id,
                case_uid=case.case_uid,
                annotation_status=annotation.status,
                review_status=request.status,
                repo_key=request.repo_key,
                reason=request.reason,
                evidence=request.evidence or {},
                eval_id=request.eval_id,
                requested_by=(
                    {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                        "role": user.role,
                    }
                    if user
                    else None
                ),
                requested_at=request.requested_at,
                resolved_at=request.resolved_at,
                resolution_note=request.resolution_note,
            )
        )
    return result
