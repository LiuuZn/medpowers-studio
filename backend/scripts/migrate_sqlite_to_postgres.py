"""把旧 SQLite 数据库迁移到 PostgreSQL。

用法（先在空库执行 Alembic）：
    cd backend
    export MEDPOWERS_DATABASE_URL=postgresql+psycopg://...
    uv run python scripts/migrate_sqlite_to_postgres.py --sqlite medpowers_studio.db --replace

脚本按外键顺序复制；目标库必须为空，或显式使用 --replace 清空。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    MetaData,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402,F401  确保 Base.metadata 已注册全部表
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402

TABLE_ORDER = [
    "users",
    "scan_protocols",
    "patients",
    "studies",
    "datasets",
    "tasks",
    "cases",
    "task_datasets",
    "annotations",
    "annotation_revisions",
    "export_jobs",
    "evaluation_jobs",
    "api_tokens",
    "device_authorizations",
    "blobs",
    "case_assets",
]


def _coerce(column, value):  # type: ignore[no-untyped-def]
    if value is None:
        return None
    if isinstance(column.type, JSON) and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


_SKIP = object()


def _default_for_column(column):  # type: ignore[no-untyped-def]
    default = column.default
    if default is not None:
        arg = default.arg
        if callable(arg):
            for context in ({}, None):
                try:
                    return arg(context) if context is not None else arg()
                except TypeError:
                    continue
        else:
            return arg
    if column.server_default is not None:
        return _SKIP
    if isinstance(column.type, JSON):
        return {}
    if isinstance(column.type, Boolean):
        return False
    if isinstance(column.type, (Integer, Float)):
        return 0
    if isinstance(column.type, DateTime):
        return datetime.now()
    return ""


def _table_defaults(table_name: str, row: dict, target_table: Table) -> dict:
    """补齐新 schema 中旧库没有的列。"""

    if table_name == "datasets":
        dimension = row.get("dimension") or "3d"
        row.setdefault(
            "data_kind",
            "table" if dimension == "tabular" else ("2d" if dimension == "2d" else "volume3d"),
        )
    if table_name == "cases":
        image_format = (row.get("image_format") or "").lower()
        row.setdefault(
            "data_kind", "image2d" if image_format in {"png", "jpg", "jpeg"} else "volume3d"
        )
        row.setdefault("size_bytes", 0)
        row.setdefault("sha256", None)

    # 并行开发新增的 NOT NULL 列（如 tasks.annotation_contract、token repo_key）
    # 在旧 SQLite 中不存在；按 ORM 默认值补齐，避免 PostgreSQL 约束失败。
    for column in target_table.columns:
        if column.name in row or column.nullable:
            continue
        value = _default_for_column(column)
        if value is not _SKIP:
            row[column.name] = value
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default=str(BACKEND_DIR / "medpowers_studio.db"))
    parser.add_argument("--replace", action="store_true", help="清空目标库后复制")
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        print(f"SQLite 文件不存在：{sqlite_path}", file=sys.stderr)
        return 1

    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        print("请通过 MEDPOWERS_DATABASE_URL 指向 PostgreSQL 目标库", file=sys.stderr)
        return 1

    source_engine = create_engine(f"sqlite:///{sqlite_path}", future=True)
    target_engine = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(bind=target_engine)

    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_meta = MetaData()
    target_meta.reflect(bind=target_engine)

    target_tables = set(inspect(target_engine).get_table_names())
    if args.replace:
        with target_engine.begin() as conn:
            existing = [
                name
                for name in reversed(TABLE_ORDER)
                if name in target_tables and name != "alembic_version"
            ]
            if existing:
                conn.execute(text(f"TRUNCATE TABLE {', '.join(existing)} RESTART IDENTITY CASCADE"))
    else:
        with target_engine.connect() as conn:
            for name in TABLE_ORDER:
                if name not in target_tables:
                    continue
                count = conn.execute(
                    select(func.count()).select_from(target_meta.tables[name])
                ).scalar()
                if count:
                    print(
                        f"目标表 {name} 已有 {count} 行；请加 --replace 或使用空库",
                        file=sys.stderr,
                    )
                    return 1

    copied: dict[str, int] = {}
    with source_engine.connect() as source, target_engine.begin() as target:
        for name in TABLE_ORDER:
            if name not in source_meta.tables or name not in target_meta.tables:
                copied[name] = 0
                continue
            source_table: Table = source_meta.tables[name]
            target_table: Table = target_meta.tables[name]
            target_columns = {column.name: column for column in target_table.columns}
            source_columns = {column.name: column for column in source_table.columns}
            common = [column for column in source_columns if column in target_columns]

            rows = source.execute(select(source_table)).mappings().all()
            payload = []
            for raw in rows:
                row = {key: _coerce(source_columns[key], raw[key]) for key in common}
                row = _table_defaults(name, row, target_table)
                payload.append(row)
            for index in range(0, len(payload), max(1, args.batch)):
                target.execute(target_table.insert(), payload[index : index + args.batch])
            copied[name] = len(payload)
            print(f"{name}: {len(payload)}")

    print("\n复制完成，校验行数：")
    ok = True
    with source_engine.connect() as source, target_engine.connect() as target:
        for name in TABLE_ORDER:
            if name not in source_meta.tables or name not in target_meta.tables:
                continue
            source_count = source.execute(
                select(func.count()).select_from(source_meta.tables[name])
            ).scalar()
            target_count = target.execute(
                select(func.count()).select_from(target_meta.tables[name])
            ).scalar()
            flag = "OK" if source_count == target_count else "MISMATCH"
            if source_count != target_count:
                ok = False
            print(f"  {name}: {source_count} -> {target_count} [{flag}]")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
