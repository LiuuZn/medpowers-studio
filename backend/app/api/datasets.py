from __future__ import annotations

import shutil
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import (
    Principal,
    get_current_user,
    require_admin,
    require_admin_or_dataset_manage,
)
from ..domain.modalities import get_modality
from ..domain.task_types import get_task_type
from ..models import (
    Annotation,
    Case,
    Dataset,
    ImportJob,
    Patient,
    ScanProtocol,
    Study,
    Task,
    TaskDataset,
    User,
    new_id,
)
from ..schemas import (
    CasePage,
    DatasetCreate,
    DatasetHierarchyPage,
    DatasetOut,
    DatasetTaskSummary,
    DatasetUpdate,
    ImportJobCreate,
    ImportJobOut,
    ImportPathRequest,
    ImportReport,
    PatientNode,
    SeriesNode,
    StudyNode,
)
from ..services import import_jobs, storage
from ..services.import_service import import_from_path, import_from_upload

router = APIRouter(prefix="/datasets", tags=["数据集"])

# 令牌并发导入配额：只限制后台任务，网页管理员不受影响。
MAX_ACTIVE_IMPORT_JOBS_PER_TOKEN = 3


def _get_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return dataset


def _dataset_hierarchy_counts(
    db: Session, dataset_ids: list[str]
) -> dict[str, tuple[int, int]]:
    if not dataset_ids:
        return {}
    rows = db.execute(
        select(
            Case.dataset_id,
            func.count(func.distinct(Study.patient_id)),
            func.count(func.distinct(Case.study_id)),
        )
        .join(Study, Study.id == Case.study_id)
        .where(Case.dataset_id.in_(dataset_ids))
        .group_by(Case.dataset_id)
    ).all()
    return {
        str(dataset_id): (int(patient_count), int(study_count))
        for dataset_id, patient_count, study_count in rows
    }


def _dataset_out(db: Session, dataset: Dataset) -> DatasetOut:
    patient_count, study_count = _dataset_hierarchy_counts(db, [dataset.id]).get(
        dataset.id, (0, 0)
    )
    return DatasetOut.model_validate(dataset).model_copy(
        update={"patient_count": patient_count, "study_count": study_count}
    )


def _validate_protocol(
    db: Session, protocol_id: str, modality: str, allow_inactive: bool = False
) -> ScanProtocol:
    protocol = db.get(ScanProtocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=400, detail="扫描流程不存在")
    if not protocol.is_active and not allow_inactive:
        raise HTTPException(status_code=400, detail="扫描流程已停用，不能用于新数据集")
    if protocol.modality_scope and modality not in protocol.modality_scope:
        raise HTTPException(status_code=400, detail="扫描流程不适用于该模态")
    return protocol


@router.get("", response_model=list[DatasetOut])
def list_datasets(
    modality: str | None = None,
    status: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DatasetOut]:
    query = select(Dataset).order_by(Dataset.created_at.desc())
    if modality:
        query = query.where(Dataset.modality == modality)
    if status:
        query = query.where(Dataset.status == status)
    if search:
        like = f"%{search}%"
        query = query.where(or_(Dataset.name.ilike(like), Dataset.code.ilike(like)))
    datasets = db.scalars(query).all()
    counts = _dataset_hierarchy_counts(db, [item.id for item in datasets])
    return [
        DatasetOut.model_validate(item).model_copy(
            update={
                "patient_count": counts.get(item.id, (0, 0))[0],
                "study_count": counts.get(item.id, (0, 0))[1],
            }
        )
        for item in datasets
    ]


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(
    payload: DatasetCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin_or_dataset_manage),
) -> DatasetOut:
    try:
        spec = get_modality(payload.modality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.data_kind and payload.data_kind != spec.data_kind:
        raise HTTPException(
            status_code=400,
            detail=f"数据种类与模态不匹配：{payload.modality} 应为 {spec.data_kind}",
        )
    if db.scalar(select(Dataset).where(Dataset.code == payload.code)):
        raise HTTPException(status_code=409, detail="数据集编码已存在")
    _validate_protocol(db, payload.scan_protocol_id, payload.modality)

    dataset_id = new_id()
    dataset = Dataset(
        id=dataset_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        modality=payload.modality,
        dimension=spec.dimension,
        data_kind=spec.data_kind,
        scan_protocol_id=payload.scan_protocol_id,
        status="draft",
        case_count=0,
        storage_path=storage.dataset_key(dataset_id),
        created_by_id=principal.user.id,
        created_by_token_id=principal.token_id,
        created_by_repo_key=principal.repo_key,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _dataset_out(db, dataset)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DatasetOut:
    return _dataset_out(db, _get_dataset(db, dataset_id))


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: str,
    payload: DatasetUpdate,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin_or_dataset_manage),
) -> DatasetOut:
    dataset = _get_dataset(db, dataset_id)
    if payload.scan_protocol_id is not None:
        _validate_protocol(db, payload.scan_protocol_id, dataset.modality)
        dataset.scan_protocol_id = payload.scan_protocol_id
    if payload.name is not None:
        dataset.name = payload.name
    if payload.description is not None:
        dataset.description = payload.description
    db.commit()
    db.refresh(dataset)
    return _dataset_out(db, dataset)


@router.post("/{dataset_id}/ready", response_model=DatasetOut)
def mark_ready(
    dataset_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin_or_dataset_manage),
) -> DatasetOut:
    dataset = _get_dataset(db, dataset_id)
    if dataset.status == "archived":
        raise HTTPException(status_code=400, detail="已归档数据集不能标记为就绪")
    if dataset.case_count <= 0:
        raise HTTPException(status_code=400, detail="数据集还没有病例，不能标记为就绪")
    dataset.status = "ready"
    db.commit()
    db.refresh(dataset)
    return _dataset_out(db, dataset)


@router.post("/{dataset_id}/archive", response_model=DatasetOut)
def archive_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> DatasetOut:
    dataset = _get_dataset(db, dataset_id)
    links = int(
        db.scalar(
            select(func.count())
            .select_from(TaskDataset)
            .where(TaskDataset.dataset_id == dataset.id)
        )
        or 0
    )
    if links:
        raise HTTPException(status_code=409, detail="数据集已关联任务，不能归档")
    dataset.status = "archived"
    db.commit()
    db.refresh(dataset)
    return _dataset_out(db, dataset)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    dataset = _get_dataset(db, dataset_id)
    if dataset.case_count > 0:
        raise HTTPException(status_code=409, detail="数据集已有病例，不能删除；请使用归档")
    links = int(
        db.scalar(
            select(func.count())
            .select_from(TaskDataset)
            .where(TaskDataset.dataset_id == dataset.id)
        )
        or 0
    )
    if links:
        raise HTTPException(status_code=409, detail="数据集已关联任务，不能删除")
    path = storage.resolve_key(dataset.storage_path) if dataset.storage_path else None
    db.delete(dataset)
    db.commit()
    if path and path.exists():
        shutil.rmtree(path, ignore_errors=True)


@router.get("/{dataset_id}/tasks", response_model=list[DatasetTaskSummary])
def list_dataset_tasks(
    dataset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DatasetTaskSummary]:
    """数据集关联任务，以及标注状态在本数据集范围内的统计。"""

    dataset = _get_dataset(db, dataset_id)
    total_series = int(
        db.scalar(select(func.count()).select_from(Case).where(Case.dataset_id == dataset.id))
        or 0
    )
    tasks = db.scalars(
        select(Task)
        .join(TaskDataset, TaskDataset.task_id == Task.id)
        .where(TaskDataset.dataset_id == dataset.id)
        .order_by(Task.created_at.desc())
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for task_id, status, count in db.execute(
        select(Annotation.task_id, Annotation.status, func.count())
        .join(Case, Case.id == Annotation.case_id)
        .where(Case.dataset_id == dataset.id)
        .group_by(Annotation.task_id, Annotation.status)
    ).all():
        counts.setdefault(str(task_id), {})[str(status)] = int(count)

    result: list[DatasetTaskSummary] = []
    for task in tasks:
        status_counts = counts.get(task.id, {})
        non_pending = sum(
            status_counts.get(status, 0)
            for status in ("in_progress", "submitted", "approved", "rejected", "review_requested")
        )
        spec = get_task_type(task.task_type)
        result.append(
            DatasetTaskSummary(
                task_id=task.id,
                code=task.code,
                name=task.name,
                task_type=task.task_type,
                task_type_name=spec.name,
                annotation_kind=spec.annotation_kind,
                dimension=task.dimension,
                status=task.status,
                label_schema=task.label_schema or {},
                total_series=total_series,
                pending=max(0, total_series - non_pending),
                in_progress=status_counts.get("in_progress", 0),
                submitted=status_counts.get("submitted", 0),
                approved=status_counts.get("approved", 0),
                rejected=status_counts.get("rejected", 0),
                review_requested=status_counts.get("review_requested", 0),
            )
        )
    return result


def _hierarchy_search_condition(like: str) -> ColumnElement[bool]:
    return or_(
        Case.case_uid.ilike(like),
        Case.series_uid.ilike(like),
        Case.series_description.ilike(like),
        Study.study_uid.ilike(like),
        Study.description.ilike(like),
        Patient.patient_key.ilike(like),
    )


def _series_node(
    case: Case,
    study: Study | None,
    patient: Patient | None,
    annotation: Annotation | None,
    annotator: User | None,
) -> SeriesNode:
    return SeriesNode(
        case_id=case.id,
        case_uid=case.case_uid,
        series_uid=case.series_uid,
        series_number=case.series_number,
        series_description=case.series_description or "",
        image_format=case.image_format,
        data_kind=case.data_kind or "",
        geometry=case.geometry or {},
        source_kind=case.source_kind or "",
        annotation_id=annotation.id if annotation else None,
        annotation_status=annotation.status if annotation else "pending",
        version=annotation.version if annotation else 0,
        annotator_name=(
            (annotator.display_name or annotator.username) if annotator else None
        ),
        updated_at=annotation.updated_at if annotation else None,
        patient_id=patient.id if patient else None,
        patient_key=patient.patient_key if patient else None,
        sex=(patient.sex or "") if patient else "",
        age=(patient.age or "") if patient else "",
        study_id=study.id if study else None,
        study_uid=study.study_uid if study else None,
        study_description=(study.description or "") if study else "",
        study_date=(study.study_date or "") if study else "",
        accession_number=(study.accession_number or "") if study else "",
    )


def _load_series_nodes(
    db: Session,
    dataset_id: str,
    task_id: str | None,
    condition: ColumnElement[bool] | None = None,
) -> list[SeriesNode]:
    stmt = (
        select(Case, Study, Patient, Annotation, User)
        .outerjoin(Study, Study.id == Case.study_id)
        .outerjoin(Patient, Patient.id == Study.patient_id)
        .outerjoin(
            Annotation,
            and_(Annotation.case_id == Case.id, Annotation.task_id == task_id),
        )
        .outerjoin(User, User.id == Annotation.annotator_id)
        .where(Case.dataset_id == dataset_id)
        .order_by(func.coalesce(Case.series_number, 999999), Case.case_uid)
    )
    if condition is not None:
        stmt = stmt.where(condition)
    return [
        _series_node(case, study, patient, annotation, annotator)
        for case, study, patient, annotation, annotator in db.execute(stmt).all()
    ]


def _count_subquery(db: Session, stmt) -> int:  # type: ignore[no-untyped-def]
    return int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


@router.get("/{dataset_id}/hierarchy", response_model=DatasetHierarchyPage)
def dataset_hierarchy(
    dataset_id: str,
    task_id: str | None = None,
    search: str | None = None,
    level: Literal["patient", "study", "series"] = "patient",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DatasetHierarchyPage:
    """按 DICOM Patient → Study → Series 返回数据集层级，并附带指定任务的标注状态。

    - ``level=patient``（默认，兼容旧调用）：患者树，可展开到检查、序列；
    - ``level=study``：平铺所有检查，每个检查内嵌序列；
    - ``level=series``：平铺所有序列，附带患者/检查上下文。
    """

    dataset = _get_dataset(db, dataset_id)
    if task_id:
        linked = db.scalar(
            select(TaskDataset).where(
                TaskDataset.dataset_id == dataset.id, TaskDataset.task_id == task_id
            )
        )
        if not linked:
            raise HTTPException(status_code=400, detail="该任务未关联到此数据集")

    total_series = int(
        db.scalar(select(func.count()).select_from(Case).where(Case.dataset_id == dataset.id))
        or 0
    )
    total_studies = int(
        db.scalar(
            select(func.count(func.distinct(Study.id)))
            .select_from(Case)
            .join(Study, Study.id == Case.study_id)
            .where(Case.dataset_id == dataset.id)
        )
        or 0
    )
    total_patients = int(
        db.scalar(
            select(func.count(func.distinct(Study.patient_id)))
            .select_from(Case)
            .join(Study, Study.id == Case.study_id)
            .where(Case.dataset_id == dataset.id)
        )
        or 0
    )
    unassigned_series = int(
        db.scalar(
            select(func.count())
            .select_from(Case)
            .where(Case.dataset_id == dataset.id, Case.study_id.is_(None))
        )
        or 0
    )

    search = (search or "").strip() or None
    search_condition = _hierarchy_search_condition(f"%{search}%") if search else None

    patient_filter = (
        select(Patient.id.label("patient_id"))
        .join(Study, Study.patient_id == Patient.id)
        .join(Case, Case.study_id == Study.id)
        .where(Case.dataset_id == dataset.id)
    )
    study_filter = (
        select(Study.id.label("study_id"))
        .join(Case, Case.study_id == Study.id)
        .join(Patient, Patient.id == Study.patient_id)
        .where(Case.dataset_id == dataset.id)
    )
    series_filter = (
        select(Case.id.label("case_id"))
        .outerjoin(Study, Study.id == Case.study_id)
        .outerjoin(Patient, Patient.id == Study.patient_id)
        .where(Case.dataset_id == dataset.id)
    )
    if search_condition is not None:
        patient_filter = patient_filter.where(search_condition)
        study_filter = study_filter.where(search_condition)
        series_filter = series_filter.where(search_condition)

    patient_filter = patient_filter.distinct()
    study_filter = study_filter.distinct()
    matched_patients = _count_subquery(db, patient_filter)
    matched_studies = _count_subquery(db, study_filter)
    matched_series = _count_subquery(db, series_filter)

    items: list[PatientNode | StudyNode | SeriesNode]
    if level == "patient":
        patient_subquery = patient_filter.subquery()
        patient_page = db.scalars(
            select(Patient)
            .join(patient_subquery, patient_subquery.c.patient_id == Patient.id)
            .order_by(Patient.patient_key)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        patient_ids = [patient.id for patient in patient_page]
        studies = (
            db.scalars(
                select(Study)
                .where(Study.patient_id.in_(patient_ids))
                .where(
                    Study.id.in_(
                        select(Case.study_id).where(
                            Case.dataset_id == dataset.id, Case.study_id.is_not(None)
                        )
                    )
                )
                .order_by(Study.study_date, Study.study_uid)
            ).all()
            if patient_ids
            else []
        )
        study_ids = [study.id for study in studies]
        series_by_study: dict[str, list[SeriesNode]] = {}
        if study_ids:
            for node in _load_series_nodes(
                db, dataset.id, task_id, Case.study_id.in_(study_ids)
            ):
                series_by_study.setdefault(node.study_id or "", []).append(node)

        studies_by_patient: dict[str, list[Study]] = {}
        for study in studies:
            studies_by_patient.setdefault(study.patient_id, []).append(study)

        items = []
        for patient in patient_page:
            study_nodes = []
            for study in studies_by_patient.get(patient.id, []):
                series = series_by_study.get(study.id, [])
                study_nodes.append(
                    StudyNode(
                        study_id=study.id,
                        study_uid=study.study_uid,
                        description=study.description or "",
                        study_date=study.study_date or "",
                        accession_number=study.accession_number or "",
                        series_count=len(series),
                        series=series,
                        patient_id=patient.id,
                        patient_key=patient.patient_key,
                        sex=patient.sex or "",
                        age=patient.age or "",
                    )
                )
            items.append(
                PatientNode(
                    patient_id=patient.id,
                    patient_key=patient.patient_key,
                    sex=patient.sex or "",
                    age=patient.age or "",
                    study_count=len(study_nodes),
                    series_count=sum(node.series_count for node in study_nodes),
                    studies=study_nodes,
                )
            )
        total = matched_patients

    elif level == "study":
        study_subquery = study_filter.subquery()
        study_page = db.execute(
            select(Study, Patient)
            .join(study_subquery, study_subquery.c.study_id == Study.id)
            .join(Patient, Patient.id == Study.patient_id)
            .order_by(Patient.patient_key, Study.study_date, Study.study_uid)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        study_ids = [study.id for study, _ in study_page]
        series_by_study = {}
        if study_ids:
            for node in _load_series_nodes(
                db, dataset.id, task_id, Case.study_id.in_(study_ids)
            ):
                series_by_study.setdefault(node.study_id or "", []).append(node)

        items = []
        for study, patient in study_page:
            series = series_by_study.get(study.id, [])
            items.append(
                StudyNode(
                    study_id=study.id,
                    study_uid=study.study_uid,
                    description=study.description or "",
                    study_date=study.study_date or "",
                    accession_number=study.accession_number or "",
                    series_count=len(series),
                    series=series,
                    patient_id=patient.id,
                    patient_key=patient.patient_key,
                    sex=patient.sex or "",
                    age=patient.age or "",
                )
            )
        total = matched_studies

    else:
        series_page_stmt = (
            select(Case, Study, Patient)
            .outerjoin(Study, Study.id == Case.study_id)
            .outerjoin(Patient, Patient.id == Study.patient_id)
            .where(Case.dataset_id == dataset.id)
        )
        if search_condition is not None:
            series_page_stmt = series_page_stmt.where(search_condition)
        series_page = db.execute(
            series_page_stmt.order_by(
                Patient.patient_key,
                Study.study_date,
                func.coalesce(Case.series_number, 999999),
                Case.case_uid,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        case_ids = [case.id for case, _, _ in series_page]
        nodes = (
            _load_series_nodes(db, dataset.id, task_id, Case.id.in_(case_ids))
            if case_ids
            else []
        )
        node_by_case = {node.case_id: node for node in nodes}
        items = [node_by_case[case.id] for case, _, _ in series_page if case.id in node_by_case]
        total = matched_series

    return DatasetHierarchyPage(
        level=level,
        total_patients=total_patients,
        matched_patients=matched_patients,
        total_studies=total_studies,
        matched_studies=matched_studies,
        total_series=total_series,
        matched_series=matched_series,
        unassigned_series=unassigned_series,
        total=total,
        items=items,
    )


@router.get("/{dataset_id}/cases", response_model=CasePage)
def list_cases(
    dataset_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CasePage:
    _get_dataset(db, dataset_id)
    query = select(Case).where(Case.dataset_id == dataset_id)
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
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    items = db.scalars(
        query.order_by(Case.case_uid).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return CasePage(total=total, items=items)


@router.post("/{dataset_id}/import-path", response_model=ImportReport)
def import_path(
    dataset_id: str,
    payload: ImportPathRequest,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin_or_dataset_manage),
) -> ImportReport:
    dataset = _get_dataset(db, dataset_id)
    if dataset.status == "archived":
        raise HTTPException(status_code=400, detail="已归档数据集不能导入病例")
    try:
        return import_from_path(
            db,
            dataset,
            payload.path,
            recursive=payload.recursive,
            acknowledge_source_discarded=payload.acknowledge_source_discarded,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{dataset_id}/import-upload", response_model=ImportReport)
def import_upload(
    dataset_id: str,
    file: UploadFile = File(...),
    acknowledge_source_discarded: bool = Form(default=False),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_admin_or_dataset_manage),
) -> ImportReport:
    dataset = _get_dataset(db, dataset_id)
    if dataset.status == "archived":
        raise HTTPException(status_code=400, detail="已归档数据集不能导入病例")
    try:
        return import_from_upload(
            db,
            dataset,
            file,
            get_settings().max_upload_mb,
            acknowledge_source_discarded=acknowledge_source_discarded,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{dataset_id}/import-jobs", response_model=ImportJobOut, status_code=202)
def create_import_job(
    dataset_id: str,
    payload: ImportJobCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin_or_dataset_manage),
) -> ImportJob:
    dataset = _get_dataset(db, dataset_id)
    if dataset.status == "archived":
        raise HTTPException(status_code=400, detail="已归档数据集不能导入病例")
    if not payload.acknowledge_source_discarded:
        raise HTTPException(status_code=400, detail="请先确认已自行备份原始数据")
    if principal.is_token:
        active_jobs = int(
            db.scalar(
                select(func.count())
                .select_from(ImportJob)
                .where(
                    ImportJob.created_by_token_id == principal.token_id,
                    ImportJob.status.in_(("queued", "running")),
                )
            )
            or 0
        )
        if active_jobs >= MAX_ACTIVE_IMPORT_JOBS_PER_TOKEN:
            raise HTTPException(
                status_code=429,
                detail=(
                    "该 API 令牌同时进行的导入任务不能超过 "
                    f"{MAX_ACTIVE_IMPORT_JOBS_PER_TOKEN} 个，请等待现有任务完成"
                ),
            )
    job = ImportJob(
        dataset_id=dataset.id,
        source_type="path",
        source_path=payload.path,
        recursive=payload.recursive,
        status="queued",
        created_by_id=principal.user.id,
        created_by_token_id=principal.token_id,
        created_by_repo_key=principal.repo_key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    import_jobs.submit(job.id)
    return job


@router.get("/{dataset_id}/import-jobs", response_model=list[ImportJobOut])
def list_import_jobs(
    dataset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ImportJob]:
    _get_dataset(db, dataset_id)
    return list(
        db.scalars(
            select(ImportJob)
            .where(ImportJob.dataset_id == dataset_id)
            .order_by(ImportJob.created_at.desc())
            .limit(20)
        ).all()
    )


@router.get("/{dataset_id}/import-jobs/{job_id}", response_model=ImportJobOut)
def get_import_job(
    dataset_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if not job or job.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return job
