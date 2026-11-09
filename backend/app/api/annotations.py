from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import (
    Principal,
    get_current_user,
    get_principal,
    require_admin,
    require_annotator,
    require_reviewer,
)
from ..models import Annotation, Case, Dataset, Task, TaskDataset, User
from ..rate_limit import rate_limiter
from ..schemas import (
    AnnotationCaseOut,
    AnnotationCasePage,
    AnnotationOut,
    AnnotationReviewRequestCreate,
    AnnotationSaveRequest,
    ReviewRequest,
)
from ..services import annotation_service, imaging, storage

task_router = APIRouter(prefix="/tasks", tags=["标注"])
annotation_router = APIRouter(prefix="/annotations", tags=["标注"])


def _get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _get_case_for_task(db: Session, task_id: str, case_id: str) -> Case:
    case = db.scalar(
        select(Case)
        .join(TaskDataset, TaskDataset.dataset_id == Case.dataset_id)
        .where(Case.id == case_id, TaskDataset.task_id == task_id)
    )
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在或未关联到该任务")
    return case


def _get_annotation(db: Session, task_id: str, case_id: str) -> Annotation | None:
    return db.scalar(
        select(Annotation).where(Annotation.task_id == task_id, Annotation.case_id == case_id)
    )


def _get_annotation_by_id(db: Session, annotation_id: str) -> Annotation:
    annotation = db.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注记录不存在")
    return annotation


@task_router.get("/{task_id}/annotation-cases", response_model=AnnotationCasePage)
def annotation_cases(
    task_id: str,
    status: str | None = None,
    dataset_id: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AnnotationCasePage:
    task = _get_task(db, task_id)
    query = (
        select(Case, Annotation, Dataset)
        .join(
            TaskDataset,
            and_(TaskDataset.dataset_id == Case.dataset_id, TaskDataset.task_id == task.id),
        )
        .join(Dataset, Dataset.id == Case.dataset_id)
        .outerjoin(
            Annotation,
            and_(Annotation.case_id == Case.id, Annotation.task_id == task.id),
        )
        .options(joinedload(Annotation.annotator))
    )
    if dataset_id:
        query = query.where(Case.dataset_id == dataset_id)
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                Case.case_uid.ilike(like),
                Case.series_uid.ilike(like),
                Case.series_description.ilike(like),
                Case.patient_key.ilike(like),
            )
        )
    if status == "pending":
        query = query.where(or_(Annotation.id.is_(None), Annotation.status == "pending"))
    elif status:
        query = query.where(Annotation.status == status)

    total = int(db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)
    rows = db.execute(
        query.order_by(Dataset.code, Case.case_uid).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = []
    for case, annotation, dataset in rows:
        items.append(
            AnnotationCaseOut(
                case_id=case.id,
                case_uid=case.case_uid,
                patient_key=case.patient_key,
                dataset_id=dataset.id,
                dataset_name=dataset.name,
                status=annotation.status if annotation else "pending",
                annotation_id=annotation.id if annotation else None,
                version=annotation.version if annotation else 0,
                annotator_name=(
                    (annotation.annotator.display_name or annotation.annotator.username)
                    if annotation and annotation.annotator
                    else None
                ),
                updated_at=annotation.updated_at if annotation else None,
            )
        )
    return AnnotationCasePage(total=total, items=items)


@task_router.get("/{task_id}/annotations/{case_id}", response_model=AnnotationOut)
def get_annotation(
    task_id: str,
    case_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AnnotationOut:
    task = _get_task(db, task_id)
    case = _get_case_for_task(db, task_id, case_id)
    annotation = _get_annotation(db, task_id, case_id)
    return annotation_service.annotation_out(annotation, task, case)


@task_router.put("/{task_id}/annotations/{case_id}", response_model=AnnotationOut)
def save_annotation_data(
    task_id: str,
    case_id: str,
    payload: AnnotationSaveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_annotator),
) -> AnnotationOut:
    task = _get_task(db, task_id)
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="任务已归档，不能继续标注")
    case = _get_case_for_task(db, task_id, case_id)
    try:
        annotation = annotation_service.save_data(db, task, case, user, payload.data, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return annotation_service.annotation_out(annotation, task, case)


@task_router.put("/{task_id}/annotations/{case_id}/mask-slice", response_model=AnnotationOut)
def save_mask_slice(
    task_id: str,
    case_id: str,
    axis: str = Query(default="axial"),
    index: int = Query(default=0, ge=0),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_annotator),
) -> AnnotationOut:
    task = _get_task(db, task_id)
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="任务已归档，不能继续标注")
    case = _get_case_for_task(db, task_id, case_id)
    content = file.file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="掩码切片文件过大")
    try:
        annotation = annotation_service.save_mask_slice(db, task, case, user, axis, index, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return annotation_service.annotation_out(annotation, task, case)


@task_router.put("/{task_id}/annotations/{case_id}/mask", response_model=AnnotationOut)
def save_mask_2d(
    task_id: str,
    case_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_annotator),
) -> AnnotationOut:
    task = _get_task(db, task_id)
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="任务已归档，不能继续标注")
    case = _get_case_for_task(db, task_id, case_id)
    content = file.file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="掩码文件过大")
    try:
        annotation = annotation_service.save_mask_2d(db, task, case, user, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return annotation_service.annotation_out(annotation, task, case)


@task_router.get("/{task_id}/annotations/{case_id}/mask-slice")
def get_mask_slice(
    task_id: str,
    case_id: str,
    axis: str = Query(default="axial"),
    index: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    task = _get_task(db, task_id)
    case = _get_case_for_task(db, task_id, case_id)
    if task.task_type == "seg3d":
        if axis != "axial":
            raise HTTPException(status_code=400, detail="首版掩码切片仅支持轴位")
        content = imaging.read_mask_slice(task.id, case.id, index)
        if content is None:
            return Response(status_code=204)
        return Response(content=content, media_type="image/png")
    if task.task_type == "seg2d":
        mask_path = storage.annotation_current_dir(task.id, case.id) / "mask.png"
        if not mask_path.exists():
            return Response(status_code=204)
        return Response(content=mask_path.read_bytes(), media_type="image/png")
    return Response(status_code=204)


@task_router.get("/{task_id}/annotations/{case_id}/mask")
def get_mask_file(
    task_id: str,
    case_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    _get_task(db, task_id)
    case = _get_case_for_task(db, task_id, case_id)
    annotation = _get_annotation(db, task_id, case_id)
    if not annotation or not annotation.mask_path:
        raise HTTPException(status_code=404, detail="尚未生成提交版本掩码")
    path = storage.resolve_key(annotation.mask_path)
    media_type = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=f"{case.case_uid}{path.suffix}")


@annotation_router.post("/{annotation_id}/submit", response_model=AnnotationOut)
def submit_annotation(
    annotation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_annotator),
) -> AnnotationOut:
    annotation = _get_annotation_by_id(db, annotation_id)
    task = _get_task(db, annotation.task_id)
    case = db.get(Case, annotation.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="任务已归档，不能提交标注")
    try:
        annotation = annotation_service.submit(db, task, case, annotation, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return annotation_service.annotation_out(annotation, task, case)


@annotation_router.post("/{annotation_id}/request-review", response_model=AnnotationOut)
def request_annotation_review(
    annotation_id: str,
    payload: AnnotationReviewRequestCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> AnnotationOut:
    """训练仓库/插件申请人工复核：approved → review_requested，不改标注内容。"""

    retry_after = rate_limiter.hit(
        f"review-request:{principal.token_id or principal.user.id}", 10, 60
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="复核申请过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    annotation = _get_annotation_by_id(db, annotation_id)
    task = _get_task(db, annotation.task_id)
    case = db.get(Case, annotation.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    try:
        annotation, _ = annotation_service.request_review(
            db,
            annotation,
            principal.user,
            reason=payload.reason,
            evidence=payload.evidence,
            eval_id=payload.eval_id,
            token_id=principal.token_id,
            repo_key=principal.repo_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return annotation_service.annotation_out(annotation, task, case)


@annotation_router.post("/{annotation_id}/review", response_model=AnnotationOut)
def review_annotation(
    annotation_id: str,
    payload: ReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_reviewer),
) -> AnnotationOut:
    annotation = _get_annotation_by_id(db, annotation_id)
    task = _get_task(db, annotation.task_id)
    case = db.get(Case, annotation.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    try:
        annotation = annotation_service.review(
            db, annotation, user, payload.decision, payload.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return annotation_service.annotation_out(annotation, task, case)


@annotation_router.post("/{annotation_id}/reopen", response_model=AnnotationOut)
def reopen_annotation(
    annotation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> AnnotationOut:
    annotation = _get_annotation_by_id(db, annotation_id)
    task = _get_task(db, annotation.task_id)
    case = db.get(Case, annotation.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="病例不存在")
    annotation = annotation_service.reopen(db, annotation, user)
    return annotation_service.annotation_out(annotation, task, case)
