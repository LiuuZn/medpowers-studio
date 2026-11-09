"""把指定数据集内已有标注批量提交并审核通过。

脚本按业务流程执行「提交（生成 revision）→ 审核通过」，不会直接改状态，
因此导出/评估仍能拿到可复现的标注版本。

用法（在 backend 目录）：
    uv run python scripts/approve_dataset_annotations.py \
        --dataset "脊柱关键层面 CT" --dry-run
    uv run python scripts/approve_dataset_annotations.py \
        --dataset "脊柱关键层面 CT" --comment "历史数据批量审核通过"

默认审核人为 admin，可通过 --reviewer 指定；已有 approved 标注会跳过。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, ensure_dirs, init_db  # noqa: E402
from app.domain.constants import (  # noqa: E402
    ANNOTATION_APPROVED,
    ANNOTATION_SUBMITTED,
    ROLE_ADMIN,
    ROLE_REVIEWER,
)
from app.domain.task_types import get_task_type  # noqa: E402
from app.models import Annotation, Case, Dataset, Task, User  # noqa: E402
from app.services import annotation_service  # noqa: E402


@dataclass
class ApproveStats:
    total: int = 0
    approved_now: int = 0
    already_approved: int = 0
    skipped_empty: int = 0
    errors: list[str] = field(default_factory=list)


def _has_content(annotation: Annotation, task: Task) -> bool:
    kind = get_task_type(task.task_type).annotation_kind
    if kind == "mask":
        return annotation_service.mask_available(annotation) or bool(annotation.mask_path)
    key = "frames" if kind == "keyframe" else "boxes"
    return bool((annotation.data or {}).get(key))


def _find_dataset(db, value: str) -> Dataset | None:
    dataset = db.scalar(select(Dataset).where(Dataset.name == value))
    if dataset:
        return dataset
    return db.scalar(select(Dataset).where(Dataset.name.ilike(f"%{value}%")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="数据集名称或名称片段")
    parser.add_argument("--reviewer", default="admin", help="审核人用户名（默认 admin）")
    parser.add_argument("--comment", default="历史数据批量审核通过", help="审核备注")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写数据库")
    args = parser.parse_args()

    init_db()
    ensure_dirs()
    stats = ApproveStats()

    with SessionLocal() as db:
        dataset = _find_dataset(db, args.dataset)
        if dataset is None:
            print(f"未找到数据集：{args.dataset}", file=sys.stderr)
            return 2
        reviewer = db.scalar(select(User).where(User.username == args.reviewer))
        if reviewer is None or not reviewer.is_active:
            print(f"审核人不存在或已停用：{args.reviewer}", file=sys.stderr)
            return 2
        if reviewer.role not in (ROLE_ADMIN, ROLE_REVIEWER):
            print(f"审核人需要 admin/reviewer 角色，当前为 {reviewer.role}", file=sys.stderr)
            return 2

        annotations = db.scalars(
            select(Annotation)
            .join(Case, Case.id == Annotation.case_id)
            .where(Case.dataset_id == dataset.id)
            .order_by(Annotation.created_at)
        ).all()
        stats.total = len(annotations)
        print(
            f"数据集：{dataset.name}（{dataset.id}）\n"
            f"审核人：{reviewer.username}（{reviewer.role}）\n"
            f"标注总数：{stats.total}，dry_run={args.dry_run}"
        )

        for annotation in annotations:
            task = db.get(Task, annotation.task_id)
            case = db.get(Case, annotation.case_id)
            if task is None or case is None:
                stats.errors.append(f"{annotation.id}: 任务或病例不存在")
                continue
            if annotation.status == ANNOTATION_APPROVED:
                stats.already_approved += 1
                continue
            if not _has_content(annotation, task):
                stats.skipped_empty += 1
                continue
            if args.dry_run:
                stats.approved_now += 1
                continue
            try:
                current = annotation
                if annotation.status != ANNOTATION_SUBMITTED:
                    current = annotation_service.submit(db, task, case, annotation, reviewer)
                annotation_service.review(
                    db, current, reviewer, ANNOTATION_APPROVED, args.comment
                )
                stats.approved_now += 1
                if stats.approved_now % 200 == 0:
                    print(f"  已处理 {stats.approved_now}/{stats.total}...")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                stats.errors.append(f"{case.case_uid}: {exc}")

        print(
            "完成："
            f"新通过 {stats.approved_now}，"
            f"原已通过 {stats.already_approved}，"
            f"空标注跳过 {stats.skipped_empty}，"
            f"错误 {len(stats.errors)}"
        )
        if stats.errors:
            print("错误示例：", file=sys.stderr)
            for message in stats.errors[:20]:
                print(f"  - {message}", file=sys.stderr)
    return 0 if not stats.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
