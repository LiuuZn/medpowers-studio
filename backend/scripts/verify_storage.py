"""校验 v2 存储：资产存在、路径相对、哈希可选校验。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Annotation, AnnotationRevision, Blob, Case, CaseAsset, Dataset  # noqa: E402
from app.services import storage  # noqa: E402


def _check_path(value: str | None, label: str, errors: list[str]) -> None:
    if not value:
        return
    path = Path(value)
    if path.is_absolute():
        errors.append(f"{label} 仍是绝对路径：{value}")
        return
    if not storage.resolve_key(value).exists():
        errors.append(f"{label} 文件不存在：{value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hash", action="store_true", help="重新计算并校验 sha256（大库很慢）")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    init_db()
    errors: list[str] = []
    checked = 0
    with SessionLocal() as db:
        query = select(Case).order_by(Case.created_at)
        if args.limit:
            query = query.limit(args.limit)
        for case in db.scalars(query).all():
            checked += 1
            if not case.image_path:
                errors.append(f"Case {case.case_uid} 缺少 storage key")
                continue
            path = storage.case_image_path(case)
            if not path.exists():
                errors.append(f"Case {case.case_uid} 文件不存在：{case.image_path}")
                continue
            asset = db.scalar(
                select(CaseAsset).where(CaseAsset.case_id == case.id, CaseAsset.role == "canonical")
            )
            if asset is None:
                errors.append(f"Case {case.case_uid} 缺少 canonical CaseAsset")
            if args.hash and case.sha256:
                digest, size = storage.hash_file(path)
                if digest != case.sha256:
                    errors.append(f"Case {case.case_uid} sha256 不匹配")
                if size != case.size_bytes:
                    errors.append(f"Case {case.case_uid} 大小不匹配")

        for dataset in db.scalars(select(Dataset)).all():
            if dataset.storage_path and Path(dataset.storage_path).is_absolute():
                errors.append(f"Dataset {dataset.code} storage_path 仍是绝对路径")

        for annotation in db.scalars(select(Annotation)).all():
            _check_path(annotation.data_path, f"Annotation {annotation.id} data_path", errors)
            _check_path(annotation.mask_path, f"Annotation {annotation.id} mask_path", errors)

        for revision in db.scalars(select(AnnotationRevision)).all():
            _check_path(revision.data_path, f"Revision {revision.id} data_path", errors)
            _check_path(revision.mask_path, f"Revision {revision.id} mask_path", errors)

        blob_count = len(db.scalars(select(Blob)).all())
        usage = storage.storage_usage()

    print(f"检查 Case：{checked}")
    print(f"Blob 行数：{blob_count}")
    print(
        f"存储：{usage['blob_bytes'] / 1024**3:.2f} GB / "
        f"剩余 {usage['free_bytes'] / 1024**3:.2f} GB"
    )
    if errors:
        print(f"\n发现 {len(errors)} 个问题：")
        for item in errors[:50]:
            print(f"  - {item}")
        if len(errors) > 50:
            print(f"  ... 其余 {len(errors) - 50} 条")
        return 1
    print("校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
