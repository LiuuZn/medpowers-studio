"""基线：创建当前全部表结构。

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app import models  # noqa: F401  确保模型注册
from app.db import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 基线直接使用 ORM 元数据建表；后续结构变更请新增 revision。
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
