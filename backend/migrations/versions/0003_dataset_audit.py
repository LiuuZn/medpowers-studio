"""数据接入审计：数据集/导入任务记录创建令牌与仓库。

Revision ID: 0003_dataset_audit
Revises: 0002_studio_integration
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect, text

revision: str = "0003_dataset_audit"
down_revision: str | None = "0002_studio_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = {
    "datasets": {
        "created_by_token_id": "VARCHAR(36) REFERENCES api_tokens(id) ON DELETE SET NULL",
        "created_by_repo_key": "VARCHAR(80) DEFAULT ''",
    },
    "import_jobs": {
        "created_by_token_id": "VARCHAR(36) REFERENCES api_tokens(id) ON DELETE SET NULL",
        "created_by_repo_key": "VARCHAR(80) DEFAULT ''",
    },
}


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
        bind.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_created_by_token_id "
                f"ON {table} (created_by_token_id)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        bind.execute(
            text(f"DROP INDEX IF EXISTS ix_{table}_created_by_token_id")
        )
        existing = {column["name"] for column in inspect(bind).get_columns(table)}
        for name in columns:
            if name in existing:
                bind.execute(text(f"ALTER TABLE {table} DROP COLUMN {name}"))
