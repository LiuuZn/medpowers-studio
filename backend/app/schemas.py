from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 认证与用户 ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class UserBrief(ORMModel):
    id: str
    username: str
    display_name: str
    role: str


class UserOut(ORMModel):
    id: str
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------- API 访问令牌 / 设备码授权 ----------
class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    repo_key: str = Field(default="", max_length=80)
    scopes: list[str] = Field(default_factory=lambda: ["studio:read"])
    expires_in_days: int = Field(default=90, ge=1, le=3650)


class ApiTokenOut(ORMModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    source: str
    repo_key: str = ""
    client_name: str
    status: str
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiTokenCreated(BaseModel):
    token: str
    info: ApiTokenOut


class ScopeOut(BaseModel):
    code: str
    name: str
    description: str


class AuthContextOut(BaseModel):
    service: str
    version: str
    api_prefix: str
    auth_method: Literal["jwt", "token"]
    scopes: list[str]
    capabilities: dict[str, bool]
    repo_key: str = ""
    user: UserOut


class DeviceCodeRequest(BaseModel):
    client_name: str = Field(default="medpowers", min_length=1, max_length=120)
    repo_key: str = Field(default="", max_length=80)
    scopes: list[str] = Field(default_factory=lambda: ["studio:read"])


class DeviceCodeOut(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceTokenRequest(BaseModel):
    device_code: str = Field(min_length=10, max_length=200)


class DeviceTokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    scope: str
    repo_key: str = ""
    expires_at: datetime
    user: UserOut


class DeviceUserCodeRequest(BaseModel):
    user_code: str = Field(min_length=4, max_length=20)


class DeviceAuthorizationOut(BaseModel):
    client_name: str
    repo_key: str = ""
    scopes: list[str]
    status: str
    expires_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    role: Literal["admin", "annotator", "reviewer"] = "annotator"


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: Literal["admin", "annotator", "reviewer"] | None = None
    is_active: bool | None = None


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


# ---------- 扫描流程 ----------
class ScanProtocolCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    modality_scope: list[str] = Field(default_factory=list)
    sort_order: int = 0
    is_active: bool = True


class ScanProtocolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    modality_scope: list[str] | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ScanProtocolOut(ORMModel):
    id: str
    code: str
    name: str
    description: str
    modality_scope: list[str]
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ScanProtocolBrief(ORMModel):
    id: str
    code: str
    name: str


# ---------- 数据集 ----------
class DatasetCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    modality: str
    scan_protocol_id: str
    description: str = ""
    data_kind: str | None = None


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    scan_protocol_id: str | None = None


class DatasetOut(ORMModel):
    id: str
    code: str
    name: str
    description: str
    modality: str
    dimension: str
    data_kind: str
    scan_protocol_id: str
    scan_protocol: ScanProtocolBrief
    status: str
    case_count: int
    patient_count: int = 0
    study_count: int = 0
    storage_path: str
    created_by: UserBrief | None = None
    created_by_token_id: str | None = None
    created_by_repo_key: str = ""
    created_at: datetime
    updated_at: datetime


class DatasetBrief(ORMModel):
    id: str
    code: str
    name: str
    modality: str
    dimension: str
    data_kind: str
    status: str
    case_count: int


class CaseOut(ORMModel):
    id: str
    dataset_id: str
    study_id: str | None = None
    case_uid: str
    series_uid: str | None = None
    series_number: int | None = None
    series_description: str = ""
    patient_key: str | None
    image_format: str
    data_kind: str
    size_bytes: int = 0
    sha256: str | None = None
    geometry: dict[str, Any]
    source_kind: str
    source_path: str
    metadata_json: dict[str, Any]
    created_at: datetime


class CasePage(BaseModel):
    total: int
    items: list[CaseOut]


class DatasetTaskSummary(BaseModel):
    task_id: str
    code: str
    name: str
    task_type: str
    task_type_name: str
    annotation_kind: str
    dimension: str
    status: str
    label_schema: dict[str, Any] = Field(default_factory=dict)
    total_series: int = 0
    pending: int = 0
    in_progress: int = 0
    submitted: int = 0
    approved: int = 0
    rejected: int = 0
    review_requested: int = 0


class SeriesNode(BaseModel):
    node_type: Literal["series"] = "series"
    case_id: str
    case_uid: str
    series_uid: str | None = None
    series_number: int | None = None
    series_description: str = ""
    image_format: str
    data_kind: str = "volume3d"
    geometry: dict[str, Any] = Field(default_factory=dict)
    source_kind: str = ""
    annotation_id: str | None = None
    annotation_status: str = "pending"
    version: int = 0
    annotator_name: str | None = None
    updated_at: datetime | None = None
    # 所属患者 / 检查上下文；序列层面直接平铺时需要
    patient_id: str | None = None
    patient_key: str | None = None
    sex: str = ""
    age: str = ""
    study_id: str | None = None
    study_uid: str | None = None
    study_description: str = ""
    study_date: str = ""
    accession_number: str = ""


class StudyNode(BaseModel):
    node_type: Literal["study"] = "study"
    study_id: str
    study_uid: str
    description: str = ""
    study_date: str = ""
    accession_number: str = ""
    series_count: int = 0
    series: list[SeriesNode] = Field(default_factory=list)
    # 所属患者上下文；检查层面直接平铺时需要
    patient_id: str | None = None
    patient_key: str | None = None
    sex: str = ""
    age: str = ""


class PatientNode(BaseModel):
    node_type: Literal["patient"] = "patient"
    patient_id: str
    patient_key: str
    sex: str = ""
    age: str = ""
    study_count: int = 0
    series_count: int = 0
    studies: list[StudyNode] = Field(default_factory=list)


class DatasetHierarchyPage(BaseModel):
    level: Literal["patient", "study", "series"] = "patient"
    total_patients: int = 0
    matched_patients: int = 0
    total_studies: int = 0
    matched_studies: int = 0
    total_series: int = 0
    matched_series: int = 0
    unassigned_series: int = 0
    # 当前 level 下用于分页的总数
    total: int = 0
    items: list[PatientNode | StudyNode | SeriesNode] = Field(default_factory=list)


class ImportPathRequest(BaseModel):
    path: str
    mode: Literal["copy"] = "copy"
    recursive: bool = True
    acknowledge_source_discarded: bool = False


class ImportIssue(BaseModel):
    source: str
    message: str


class ImportReport(BaseModel):
    imported: int = 0
    skipped: int = 0
    converted: int = 0
    stored_bytes: int = 0
    errors: list[ImportIssue] = Field(default_factory=list)
    cases: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportJobCreate(BaseModel):
    path: str
    recursive: bool = True
    acknowledge_source_discarded: bool = False


class ImportJobOut(ORMModel):
    id: str
    dataset_id: str
    source_type: str
    source_path: str
    recursive: bool
    status: str
    imported: int
    skipped: int
    converted: int
    stored_bytes: int
    report: dict[str, Any]
    error: str | None
    created_by_id: str | None = None
    created_by_token_id: str | None = None
    created_by_repo_key: str = ""
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SliceInfo(BaseModel):
    case_id: str
    case_uid: str
    dimension: str
    modality: str
    width: int
    height: int
    slices: int
    spacing: list[float] | None = None
    origin: list[float] | None = None
    direction: list[float] | None = None
    default_window: float | None = None
    default_level: float | None = None
    axes: list[str] = Field(default_factory=lambda: ["axial"])


class TableColumn(BaseModel):
    name: str
    type: str


class TableInfo(BaseModel):
    row_count: int
    column_count: int
    columns: list[TableColumn] = Field(default_factory=list)


class TablePage(TableInfo):
    total: int
    offset: int = 0
    limit: int = 100
    rows: list[list[Any]] = Field(default_factory=list)


# ---------- 任务 ----------
class TaskCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    task_type: str
    description: str = ""
    annotation_guide: str = ""
    annotation_contract: dict[str, Any] = Field(default_factory=dict)
    label_schema: dict[str, Any] | None = None


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    annotation_guide: str | None = None
    annotation_contract: dict[str, Any] | None = None
    label_schema: dict[str, Any] | None = None
    status: Literal["draft", "active", "archived"] | None = None


class TaskOut(ORMModel):
    id: str
    code: str
    name: str
    description: str
    task_type: str
    dimension: str
    label_schema: dict[str, Any]
    annotation_guide: str
    annotation_contract: dict[str, Any] | None = None
    status: str
    dataset_count: int = 0
    created_at: datetime
    updated_at: datetime


class TaskStats(BaseModel):
    task_id: str
    total_cases: int
    pending: int = 0
    in_progress: int = 0
    submitted: int = 0
    approved: int = 0
    rejected: int = 0
    review_requested: int = 0


class TaskDatasetOut(BaseModel):
    id: str
    created_at: datetime
    dataset: DatasetBrief


class TaskDatasetLinkRequest(BaseModel):
    dataset_id: str


# ---------- 标注 ----------
class AnnotationSaveRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class AnnotationOut(BaseModel):
    id: str | None = None
    task_id: str
    case_id: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    version: int = 0
    mask_available: bool = False
    annotator: UserBrief | None = None
    reviewer: UserBrief | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    review_comment: str = ""
    updated_at: datetime | None = None


class AnnotationCaseOut(BaseModel):
    case_id: str
    case_uid: str
    patient_key: str | None
    dataset_id: str
    dataset_name: str
    status: str
    annotation_id: str | None = None
    version: int = 0
    annotator_name: str | None = None
    updated_at: datetime | None = None


class AnnotationCasePage(BaseModel):
    total: int
    items: list[AnnotationCaseOut]


class ReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = ""


# ---------- 导出 ----------
class ExportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    task_id: str
    dataset_ids: list[str] = Field(min_length=1)
    format: Literal["nnunet"] = "nnunet"
    split_config: dict[str, Any] = Field(
        default_factory=lambda: {
            "train": 0.7,
            "val": 0.15,
            "test": 0.15,
            "seed": 42,
            "patient_level": True,
        }
    )
    include_statuses: list[str] = Field(default_factory=lambda: ["approved"])


class ExportOut(BaseModel):
    id: str
    name: str
    task_id: str
    task_name: str
    dataset_ids: list[str]
    format: str
    split_config: dict[str, Any]
    include_statuses: list[str]
    status: str
    output_dir: str
    manifest_path: str | None
    summary: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ---------- 评估 ----------
class EvaluationCreateMeta(BaseModel):
    name: str
    task_id: str
    dataset_ids: list[str]
    gt_statuses: list[str] = Field(default_factory=lambda: ["approved"])
    metrics_config: dict[str, Any] = Field(default_factory=dict)


class EvaluationOut(BaseModel):
    id: str
    name: str
    task_id: str
    task_name: str
    dataset_ids: list[str]
    gt_statuses: list[str]
    metrics_config: dict[str, Any]
    status: str
    report_path: str | None
    summary: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ---------- 仪表盘 ----------
class AnnotationCounts(BaseModel):
    pending: int = 0
    in_progress: int = 0
    submitted: int = 0
    approved: int = 0
    rejected: int = 0
    review_requested: int = 0


class TaskProgress(BaseModel):
    task_id: str
    task_name: str
    task_type: str
    dataset_id: str | None = None
    total_cases: int
    pending: int = 0
    in_progress: int = 0
    submitted: int = 0
    approved: int = 0
    rejected: int = 0
    review_requested: int = 0


class DashboardOut(BaseModel):
    datasets: int
    tasks: int
    cases: int
    annotations: AnnotationCounts
    task_progress: list[TaskProgress]
    recent_exports: list[ExportOut]
    recent_evaluations: list[EvaluationOut]


# ---------- 训练仓库对接（Studio API） ----------
class StudioMetaOut(BaseModel):
    service: str
    version: str
    api_prefix: str
    schema_version: str
    task_types: list[dict[str, Any]] = Field(default_factory=list)
    metric_schema_version: str = "1"
    capabilities: dict[str, bool] = Field(default_factory=dict)


class StudioDatasetRef(BaseModel):
    id: str
    code: str
    name: str
    modality: str
    dimension: str
    data_kind: str
    status: str
    case_count: int


class StudioTaskSummary(BaseModel):
    id: str
    code: str
    name: str
    task_type: str
    dimension: str
    status: str
    dataset_count: int = 0
    total_cases: int = 0
    approved: int = 0
    review_requested: int = 0
    annotation_contract_complete: bool = False


class StudioReadiness(BaseModel):
    task: StudioTaskSummary
    datasets: list[StudioDatasetRef] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total_cases: int = 0
    class_case_counts: dict[str, int] = Field(default_factory=dict)
    qc_issues: list[dict[str, Any]] = Field(default_factory=list)
    annotation_contract: dict[str, Any] = Field(default_factory=dict)
    annotation_contract_complete: bool = False
    last_updated: datetime | None = None


class StudioChangeItem(BaseModel):
    kind: Literal["annotation", "experiment"]
    id: str
    status: str = ""
    task_id: str | None = None
    task_code: str = ""
    case_id: str | None = None
    case_uid: str = ""
    version: int = 0
    repo_key: str = ""
    exp_id: str = ""
    updated_at: datetime | None = None


class StudioChangesOut(BaseModel):
    cursor: datetime
    since: datetime | None = None
    items: list[StudioChangeItem] = Field(default_factory=list)
    truncated: bool = False


class ExperimentCreate(BaseModel):
    repo_key: str = Field(default="", max_length=80)
    exp_id: str = Field(pattern=r"^EXP-\d{3,}$")
    task_code: str = Field(min_length=1, max_length=64)
    status: Literal["planned", "running", "done", "interrupted", "cancelled"] = "planned"
    title: str = Field(default="", max_length=200)
    machine: str = Field(default="", max_length=120)
    git_commit: str = Field(default="", max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    record_path: str = ""
    record_sha256: str = Field(default="", max_length=64)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExperimentUpdate(BaseModel):
    status: Literal["planned", "running", "done", "interrupted", "cancelled"] | None = None
    title: str | None = Field(default=None, max_length=200)
    machine: str | None = Field(default=None, max_length=120)
    git_commit: str | None = Field(default=None, max_length=64)
    config: dict[str, Any] | None = None
    notes: str | None = None
    record_path: str | None = None
    record_sha256: str | None = Field(default=None, max_length=64)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExperimentOut(BaseModel):
    id: str
    repo_key: str
    exp_id: str
    task_id: str
    task_code: str
    status: str
    title: str
    machine: str
    git_commit: str
    config: dict[str, Any]
    notes: str
    record_path: str
    record_sha256: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MetricPointIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    value: float
    step: int = 0
    epoch: int | None = None
    split: str = Field(default="", max_length=40)
    class_label: str = Field(default="", max_length=40, alias="class")
    timestamp: datetime | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="train", max_length=40)
    extra: dict[str, Any] = Field(default_factory=dict)


class MetricBatch(BaseModel):
    points: list[MetricPointIn] = Field(default_factory=list)


class MetricPointOut(BaseModel):
    name: str
    value: float
    step: int
    epoch: int | None
    split: str
    class_label: str = Field(serialization_alias="class")
    timestamp: datetime
    tags: dict[str, Any]
    source: str
    extra: dict[str, Any]


class ExternalEvaluationIn(BaseModel):
    eval_id: str = Field(min_length=1, max_length=80)
    source: Literal["external", "studio"] = "external"
    task_code: str = Field(default="", max_length=64)
    gt_statuses: list[str] = Field(default_factory=lambda: ["approved"])
    dataset_version: str = Field(default="", max_length=80)
    summary: dict[str, Any] = Field(default_factory=dict)
    per_case: list[dict[str, Any]] = Field(default_factory=list)
    report_sha256: str = Field(default="", max_length=64)
    created_at: datetime | None = None


class ExternalEvaluationOut(BaseModel):
    id: str
    experiment_id: str
    eval_id: str
    source: str
    task_code: str
    gt_statuses: list[str]
    dataset_version: str
    summary: dict[str, Any]
    per_case: list[dict[str, Any]]
    report_sha256: str
    created_at: datetime


class AnnotationReviewRequestCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    eval_id: str | None = Field(default=None, max_length=80)


class AnnotationReviewRequestOut(BaseModel):
    id: str
    annotation_id: str
    task_id: str
    task_code: str
    case_id: str
    case_uid: str
    annotation_status: str
    review_status: str
    repo_key: str
    reason: str
    evidence: dict[str, Any]
    eval_id: str | None
    requested_by: UserBrief | None = None
    requested_at: datetime
    resolved_at: datetime | None
    resolution_note: str
