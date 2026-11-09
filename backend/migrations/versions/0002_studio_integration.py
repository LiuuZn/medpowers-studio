"""训练仓库对接：API token repo_key、任务标注契约、实验/指标/外部评测/复核请求。

Revision ID: 0002_studio_integration
Revises: 0001_initial
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect, text

from app import models  # noqa: F401  确保模型注册
from app.db import Base

revision: str = "0002_studio_integration"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = {
    "api_tokens": {"repo_key": "VARCHAR(80) DEFAULT ''"},
    "device_authorizations": {"repo_key": "VARCHAR(80) DEFAULT ''"},
    "tasks": {"annotation_contract": "JSON"},
}

_TABLES = (
    "annotation_review_requests",
    "experiments",
    "metric_points",
    "external_evaluations",
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspect(bind).get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                bind.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        if table == "api_tokens":
            bind.execute(
                text("CREATE INDEX IF NOT EXISTS ix_api_tokens_repo_key ON api_tokens (repo_key)")
            )

    for name in _TABLES:
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLES):
        bind.execute(text(f"DROP TABLE IF EXISTS {name}"))
