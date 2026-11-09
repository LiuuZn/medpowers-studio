from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite 读出的时间可能不带时区，统一按 UTC 处理。"""

    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="annotator", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ApiToken(Base):
    """训练仓库/插件使用的 API 访问令牌。

    数据库只保存 SHA-256 摘要；明文 token 仅在创建响应或设备码轮询结果中出现一次。
    """

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(20), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    # 训练仓库标识：同一仓库可有多枚 token（换机/轮换），都归属同一 repo_key。
    repo_key: Mapped[str] = mapped_column(String(80), default="", index=True)
    client_name: Mapped[str] = mapped_column(String(120), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def status(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        expires_at = as_utc(self.expires_at)
        if expires_at is not None and expires_at <= utcnow():
            return "expired"
        return "active"


class DeviceAuthorization(Base):
    """RFC 8628 设备码授权请求；device_code 与 user_code 都只保存摘要。"""

    __tablename__ = "device_authorizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(120), default="")
    repo_key: Mapped[str] = mapped_column(String(80), default="")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    api_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL"), nullable=True
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    denied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanProtocol(Base):
    """扫描流程字典，由管理员配置；数据集只能单选一个。"""

    __tablename__ = "scan_protocols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    # 为空表示适用于全部模态；否则只允许这些模态的数据集选择
    modality_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    datasets: Mapped[list[Dataset]] = relationship(back_populates="scan_protocol")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    modality: Mapped[str] = mapped_column(String(16), index=True)
    dimension: Mapped[str] = mapped_column(String(8), index=True)  # 2d / 3d / tabular
    data_kind: Mapped[str] = mapped_column(String(16), default="volume3d", index=True)
    scan_protocol_id: Mapped[str] = mapped_column(
        ForeignKey("scan_protocols.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 数据接入溯源：API 令牌创建时记录令牌与仓库；网页会话为空。
    created_by_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_repo_key: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    scan_protocol: Mapped[ScanProtocol] = relationship(back_populates="datasets", lazy="joined")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy="joined")
    cases: Mapped[list[Case]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    task_links: Mapped[list[TaskDataset]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class Patient(Base):
    """DICOM Patient 层级；patient_key 为加盐哈希后的稳定标识。"""

    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    patient_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sex: Mapped[str] = mapped_column(String(8), default="")
    age: Mapped[str] = mapped_column(String(16), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    studies: Mapped[list[Study]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )


class Study(Base):
    """DICOM Study 层级；同一患者下按 StudyInstanceUID 唯一。"""

    __tablename__ = "studies"
    __table_args__ = (UniqueConstraint("patient_id", "study_uid", name="uq_study_patient_uid"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    study_uid: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    study_date: Mapped[str] = mapped_column(String(16), default="")
    accession_number: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="studies")
    cases: Mapped[list[Case]] = relationship(back_populates="study")


class Case(Base):
    """一个病例 = 一个 DICOM Series（3D 体数据或一张 2D 影像）。"""

    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("dataset_id", "case_uid", name="uq_case_dataset_uid"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    case_uid: Mapped[str] = mapped_column(String(160), index=True)
    series_uid: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    series_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    series_description: Mapped[str] = mapped_column(Text, default="")
    patient_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # image_path 现在保存相对 storage_root 的 storage key（blobs/sha256/...）。
    # 兼容迁移期旧数据：绝对路径仍可被 storage.resolve_key() 识别。
    image_path: Mapped[str] = mapped_column(Text)
    image_format: Mapped[str] = mapped_column(String(16))  # nrrd / png / parquet
    data_kind: Mapped[str] = mapped_column(String(16), default="volume3d", index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    geometry: Mapped[dict] = mapped_column(JSON, default=dict)
    source_kind: Mapped[str] = mapped_column(String(32), default="")
    source_path: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="cases")
    study: Mapped[Study | None] = relationship(back_populates="cases")
    assets: Mapped[list[CaseAsset]] = relationship(
        back_populates="case", cascade="all, delete-orphan", passive_deletes=True
    )
    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="case", cascade="all, delete-orphan", passive_deletes=True
    )


class Blob(Base):
    """内容寻址的不可变文件；同一 sha256 全平台只存一份。"""

    __tablename__ = "blobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    media_type: Mapped[str] = mapped_column(String(80), default="application/octet-stream")
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assets: Mapped[list[CaseAsset]] = relationship(back_populates="blob")


class CaseAsset(Base):
    """Case 与 Blob 的关联；role=canonical 是平台读取的主文件。"""

    __tablename__ = "case_assets"
    __table_args__ = (UniqueConstraint("case_id", "role", name="uq_case_asset_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    blob_id: Mapped[str] = mapped_column(ForeignKey("blobs.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="canonical", index=True)
    format: Mapped[str] = mapped_column(String(16), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="assets")
    blob: Mapped[Blob] = relationship(back_populates="assets", lazy="joined")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    dimension: Mapped[str] = mapped_column(String(4), index=True)
    label_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    annotation_guide: Mapped[str] = mapped_column(Text, default="")
    # 结构化标注契约：produced_by / rule / tolerance / verified；训练前必须完整。
    annotation_contract: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    dataset_links: Mapped[list[TaskDataset]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )


class TaskDataset(Base):
    """任务与数据集多对多关联；关联时强制维度一致。"""

    __tablename__ = "task_datasets"
    __table_args__ = (UniqueConstraint("task_id", "dataset_id", name="uq_task_dataset"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="dataset_links")
    dataset: Mapped[Dataset] = relationship(back_populates="task_links", lazy="joined")


class Annotation(Base):
    """任务 × 病例 的唯一标注记录。"""

    __tablename__ = "annotations"
    __table_args__ = (UniqueConstraint("task_id", "case_id", name="uq_annotation_task_case"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    data_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mask_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    annotator_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    task: Mapped[Task] = relationship(back_populates="annotations")
    case: Mapped[Case] = relationship(back_populates="annotations")
    annotator: Mapped[User | None] = relationship(foreign_keys=[annotator_id])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id])
    revisions: Mapped[list[AnnotationRevision]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan", passive_deletes=True
    )
    review_requests: Mapped[list[AnnotationReviewRequest]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan", passive_deletes=True
    )


class AnnotationRevision(Base):
    """提交时的标注快照，供导出/评估复现。"""

    __tablename__ = "annotation_revisions"
    __table_args__ = (
        UniqueConstraint("annotation_id", "version", name="uq_annotation_revision_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(
        ForeignKey("annotations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    data_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mask_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    annotation: Mapped[Annotation] = relationship(back_populates="revisions")


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    dataset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    format: Mapped[str] = mapped_column(String(32), default="nnunet")
    split_config: Mapped[dict] = mapped_column(JSON, default=dict)
    include_statuses: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["approved"])
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    output_dir: Mapped[str] = mapped_column(Text, default="")
    manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(lazy="joined")


class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    dataset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    gt_statuses: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["approved"])
    prediction_path: Mapped[str] = mapped_column(Text, default="")
    metrics_config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(lazy="joined")


class ImportJob(Base):
    """大目录导入任务；后台单线程执行，避免 HTTP 请求超时。"""

    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), default="path")
    source_path: Mapped[str] = mapped_column(Text)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    converted: Mapped[int] = mapped_column(Integer, default=0)
    stored_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_repo_key: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnnotationReviewRequest(Base):
    """已通过标注的人工复核申请；只改状态，不改标注内容/版本。"""

    __tablename__ = "annotation_review_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(
        ForeignKey("annotations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repo_key: Mapped[str] = mapped_column(String(80), default="", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    eval_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolver_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note: Mapped[str] = mapped_column(Text, default="")

    annotation: Mapped[Annotation] = relationship(back_populates="review_requests")
    user: Mapped[User | None] = relationship(foreign_keys=[user_id])
    resolver: Mapped[User | None] = relationship(foreign_keys=[resolver_id])


class Experiment(Base):
    """实验镜像：git 中的 EXP-<NNN> 记录是权威，本表只做可视化/查询。

    以 (repo_key, exp_id) 唯一；Studio 不托管 checkpoint。
    """

    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("repo_key", "exp_id", name="uq_experiment_repo_exp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repo_key: Mapped[str] = mapped_column(String(80), default="", index=True)
    exp_id: Mapped[str] = mapped_column(String(16), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    task_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    machine: Mapped[str] = mapped_column(String(120), default="")
    git_commit: Mapped[str] = mapped_column(String(64), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    record_path: Mapped[str] = mapped_column(Text, default="")
    record_sha256: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    task: Mapped[Task] = relationship(lazy="joined")
    metrics: Mapped[list[MetricPoint]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", passive_deletes=True
    )
    evaluations: Mapped[list[ExternalEvaluation]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", passive_deletes=True
    )


class MetricPoint(Base):
    """任意数值指标点；幂等键 (experiment, name, split, class, step)。"""

    __tablename__ = "metric_points"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "name", "split", "class_label", "step",
            name="uq_metric_point_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    value: Mapped[float] = mapped_column(Float)
    step: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    split: Mapped[str] = mapped_column(String(40), default="")
    class_label: Mapped[str] = mapped_column(String(40), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="train")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    experiment: Mapped[Experiment] = relationship(back_populates="metrics")


class ExternalEvaluation(Base):
    """外部推送的评测结果（source=external）；Studio 原生评测后续接入。"""

    __tablename__ = "external_evaluations"
    __table_args__ = (
        UniqueConstraint("experiment_id", "eval_id", name="uq_external_eval_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    eval_id: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(20), default="external")
    task_code: Mapped[str] = mapped_column(String(64), default="")
    gt_statuses: Mapped[list[str]] = mapped_column(JSON, default=list)
    dataset_version: Mapped[str] = mapped_column(String(80), default="")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    per_case: Mapped[list] = mapped_column(JSON, default=list)
    report_sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="evaluations")
