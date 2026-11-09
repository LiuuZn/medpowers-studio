"""为历史 Case 补齐 DICOM Patient / Study / Series 层级。

用法（在 backend 目录）：
    uv run python scripts/backfill_hierarchy.py --dry-run --limit 10
    uv run python scripts/backfill_hierarchy.py

优先使用 Case.metadata_json 中已有的 DICOM 字段；缺失时读取 NRRD/NIfTI 头，
不会加载像素。脚本幂等：已补齐 study_id / patient_key / series_uid 的病例会跳过。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, ensure_dirs, init_db  # noqa: E402
from app.main import bootstrap_admin  # noqa: E402
from app.models import Case, Dataset, Patient, Study  # noqa: E402
from app.services import hierarchy, storage  # noqa: E402
from app.services.hierarchy import SeriesMetadata  # noqa: E402

VOLUME_SUFFIXES = {".nrrd", ".nii", ".nii.gz"}


@dataclass
class BackfillStats:
    total: int = 0
    processed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _fill(primary: str, fallback: str) -> str:
    return primary or fallback


def _merge_metadata(primary: SeriesMetadata, fallback: SeriesMetadata) -> SeriesMetadata:
    return SeriesMetadata(
        patient_id=_fill(primary.patient_id, fallback.patient_id),
        patient_sex=_fill(primary.patient_sex, fallback.patient_sex),
        patient_age=_fill(primary.patient_age, fallback.patient_age),
        study_uid=_fill(primary.study_uid, fallback.study_uid),
        study_description=_fill(primary.study_description, fallback.study_description),
        study_date=_fill(primary.study_date, fallback.study_date),
        accession_number=_fill(primary.accession_number, fallback.accession_number),
        series_uid=_fill(primary.series_uid, fallback.series_uid),
        series_description=_fill(primary.series_description, fallback.series_description),
        series_number=primary.series_number or fallback.series_number,
        modality=_fill(primary.modality, fallback.modality),
    )


def _metadata_for(case: Case) -> SeriesMetadata:
    stored = SeriesMetadata.from_mapping(case.metadata_json or {})
    path = storage.case_image_path(case)
    is_volume = case.data_kind == "volume3d" or path.suffix.lower() in VOLUME_SUFFIXES
    if not path.exists() or not is_volume:
        return stored
    try:
        return _merge_metadata(hierarchy.read_volume_metadata(path), stored)
    except Exception:  # noqa: BLE001 - 头读取失败时退回已存元数据
        return stored


def _safe_json(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return dict(metadata or {})


def _fill_int(primary: int | None, fallback: int | None) -> int | None:
    return primary if primary is not None else fallback


def run(args: argparse.Namespace) -> BackfillStats:
    init_db()
    ensure_dirs()
    bootstrap_admin()

    with SessionLocal() as db:
        query = (
            select(Case)
            .where(
                or_(
                    Case.study_id.is_(None),
                    Case.patient_key.is_(None),
                    Case.series_uid.is_(None),
                )
            )
            .order_by(Case.case_uid)
        )
        if args.dataset:
            dataset = db.scalar(select(Dataset).where(Dataset.code == args.dataset))
            if dataset is None:
                raise SystemExit(f"找不到数据集编码：{args.dataset}")
            query = query.where(Case.dataset_id == dataset.id)
        if args.limit is not None:
            query = query.limit(args.limit)

        cases = db.scalars(query).all()
        stats = BackfillStats(total=len(cases))
        print(f"待补齐病例：{len(cases)}")

        if args.dry_run:
            for case in cases[:5]:
                metadata = _metadata_for(case)
                patient_key = hierarchy.resolve_patient_key(
                    db.get(Dataset, case.dataset_id), case.case_uid, metadata, case.patient_key
                )
                print(
                    f"  [dry-run] {case.case_uid}: patient={patient_key} "
                    f"study={metadata.study_uid or '-'} series={metadata.series_uid or '-'}"
                )
            print("dry-run 完成，未写入数据库。")
            return stats

        for index, case in enumerate(cases, start=1):
            try:
                dataset = db.get(Dataset, case.dataset_id)
                if dataset is None:
                    stats.skipped += 1
                    stats.errors.append(f"{case.case_uid}: 数据集不存在")
                    continue
                metadata = _metadata_for(case)
                assignment = hierarchy.assign_hierarchy(
                    db,
                    dataset,
                    case.case_uid,
                    metadata,
                    patient_key_override=case.patient_key,
                )
                case.study_id = assignment.study.id
                case.patient_key = assignment.patient_key
                case.series_uid = assignment.series_uid
                case.series_number = _fill_int(case.series_number, metadata.series_number)
                case.series_description = (
                    case.series_description or metadata.series_description
                )
                if case.metadata_json is None:
                    case.metadata_json = {}
                case.metadata_json = {
                    **hierarchy.sanitize_metadata(
                        _safe_json(case.metadata_json), assignment.patient_key
                    ),
                    **metadata.safe_metadata(assignment.patient_key),
                }
                stats.processed += 1
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"{case.case_uid}: {exc}")
                stats.skipped += 1
            if index % args.batch_size == 0:
                db.commit()
                print(f"  已处理 {index}/{len(cases)}...")
        db.commit()

        patient_count = int(db.scalar(select(func.count()).select_from(Patient)) or 0)
        study_count = int(db.scalar(select(func.count()).select_from(Study)) or 0)
        unassigned = int(
            db.scalar(
                select(func.count()).select_from(Case).where(Case.study_id.is_(None))
            )
            or 0
        )
        print()
        print("补齐完成")
        print(f"  处理 {stats.processed}，跳过 {stats.skipped}")
        print(f"  Patient={patient_count}，Study={study_count}，未归类序列={unassigned}")
        if stats.errors:
            print(f"  问题 {len(stats.errors)} 条（显示前 20 条）：")
            for message in stats.errors[:20]:
                print(f"    - {message}")
        return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="补齐 Patient/Study/Series 层级")
    parser.add_argument("--dataset", help="仅处理指定数据集编码")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 例（调试用）")
    parser.add_argument("--batch-size", type=int, default=200, help="每批提交的病例数")
    parser.add_argument("--dry-run", action="store_true", help="只读取与打印，不写数据库")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size <= 0:
        raise SystemExit("--batch-size 必须大于 0")
    stats = run(args)
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
