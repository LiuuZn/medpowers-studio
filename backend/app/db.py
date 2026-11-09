from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

connect_args = {}
engine_kwargs: dict = {"future": True}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    engine_kwargs.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})

engine = create_engine(settings.database_url, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_case_hierarchy_columns() -> None:
    """轻量迁移：为旧版 cases 表补齐 patient/study/series 层级字段。

    SQLAlchemy 的 create_all 不会修改已存在的表；这里只添加可空列与索引，
    不影响已有数据，回填由 scripts/backfill_hierarchy.py 完成。
    """

    inspector = inspect(engine)
    if "cases" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("cases")}
    additions = {
        "study_id": "VARCHAR(36)",
        "series_uid": "VARCHAR(160)",
        "series_number": "INTEGER",
        "series_description": "TEXT DEFAULT ''",
    }
    statements = [
        f"ALTER TABLE cases ADD COLUMN {name} {ddl}"
        for name, ddl in additions.items()
        if name not in existing
    ]
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_cases_study_id ON cases (study_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_cases_series_uid ON cases (series_uid)")
        )


def _ensure_asset_columns() -> None:
    """轻量迁移：为旧库补齐数据种类与资产字段，并回填 data_kind。"""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "datasets": {"data_kind": "VARCHAR(16) DEFAULT 'volume3d'"},
        "cases": {
            "data_kind": "VARCHAR(16) DEFAULT 'volume3d'",
            "size_bytes": "BIGINT DEFAULT 0",
            "sha256": "VARCHAR(64)",
        },
    }
    statements: list[str] = []
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "cases" in tables:
            connection.execute(
                text(
                    "UPDATE cases SET data_kind = 'image2d' "
                    "WHERE image_format IN ('png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff') "
                    "AND (data_kind IS NULL OR data_kind = 'volume3d')"
                )
            )
        if "datasets" in tables:
            connection.execute(
                text(
                    "UPDATE datasets SET data_kind = 'image2d' "
                    "WHERE dimension = '2d' AND (data_kind IS NULL OR data_kind = 'volume3d')"
                )
            )
            connection.execute(
                text(
                    "UPDATE datasets SET data_kind = 'table' "
                    "WHERE dimension = 'tabular' AND (data_kind IS NULL OR data_kind = 'volume3d')"
                )
            )


def _ensure_studio_columns() -> None:
    """轻量迁移：训练仓库对接所需的 token repo_key 与任务标注契约字段。

    新表（experiments/metric_points/external_evaluations/annotation_review_requests）
    由 create_all 创建；这里只补齐旧库缺的列。
    """

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "api_tokens": {"repo_key": "VARCHAR(80) DEFAULT ''"},
        "device_authorizations": {"repo_key": "VARCHAR(80) DEFAULT ''"},
        "tasks": {"annotation_contract": "JSON"},
    }
    statements: list[str] = []
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "api_tokens" in tables:
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_api_tokens_repo_key ON api_tokens (repo_key)")
            )


def _ensure_dataset_audit_columns() -> None:
    """轻量迁移：数据集/导入任务的数据接入溯源字段（API 令牌与仓库）。"""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "datasets": {
            "created_by_token_id": "VARCHAR(36) REFERENCES api_tokens(id) ON DELETE SET NULL",
            "created_by_repo_key": "VARCHAR(80) DEFAULT ''",
        },
        "import_jobs": {
            "created_by_token_id": "VARCHAR(36) REFERENCES api_tokens(id) ON DELETE SET NULL",
            "created_by_repo_key": "VARCHAR(80) DEFAULT ''",
        },
    }
    statements: list[str] = []
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        for table in additions:
            if table in tables:
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_created_by_token_id "
                        f"ON {table} (created_by_token_id)"
                    )
                )


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    settings.storage_root.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_case_hierarchy_columns()
    _ensure_asset_columns()
    _ensure_studio_columns()
    _ensure_dataset_audit_columns()


def ensure_dirs() -> None:
    for name in ("datasets", "annotations", "exports", "evaluations", "tmp", "blobs"):
        (settings.storage_root / name).mkdir(parents=True, exist_ok=True)
    Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
