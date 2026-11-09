"""把 v1 数据迁移到内容寻址存储 + 资产模型。

默认 dry-run，只统计不写入。确认后加 --apply。

    cd backend
    uv run python scripts/migrate_to_v2.py --dry-run
    uv run python scripts/migrate_to_v2.py --apply --resume

迁移内容：
1. 把 Case.image_path 指向的影像复制到 blobs/sha256/...（同一哈希只复制一次）；
2. 建立 Blob / CaseAsset(canonical) 并回填 data_kind、size_bytes、sha256；
3. 把 Dataset / Annotation / Export / Evaluation 的绝对路径改为相对 key；
4. 把旧 storage/annotations 下的文件复制到新 storage root（如不同）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, ensure_dirs, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Annotation,
    AnnotationRevision,
    Blob,
    Case,
    CaseAsset,
    Dataset,
    EvaluationJob,
    ExportJob,
)
from app.services import asset_store, storage  # noqa: E402

MEDIA_TYPES = {
    "nrrd": "application/octet-stream",
    "png": "image/png",
    "parquet": "application/vnd.apache.parquet",
}


def _case_data_kind(case: Case) -> str:
    fmt = (case.image_format or "").lower()
    if fmt == "parquet":
        return "table"
    if fmt in {"png", "jpg", "jpeg", "bmp", "tif", "tiff"}:
        return "image2d"
    return "volume3d"


def _old_path(value: str, old_root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else old_root / path


def _key_from_old(path: Path, old_root: Path) -> str | None:
    try:
        return path.resolve().relative_to(old_root.resolve()).as_posix()
    except ValueError:
        return None


def _copy_relative(path: Path, old_root: Path, new_root: Path) -> str | None:
    key = _key_from_old(path, old_root)
    if key is None:
        return None
    target = new_root / key
    if target.resolve() == path.resolve():
        return key
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
    return key


def _migrate_case(
    db,
    case: Case,
    old_root: Path,
    apply: bool,
) -> tuple[int, int, str | None]:
    source = _old_path(case.image_path, old_root)
    if case.image_path.startswith("blobs/"):
        return 0, 0, None
    if not source.exists():
        return 0, 0, f"影像不存在：{source}"
    size = source.stat().st_size
    if not apply:
        return 1, size, None

    ref = asset_store.put_file(
        source, MEDIA_TYPES.get(case.image_format, "application/octet-stream")
    )
    blob = db.scalar(select(Blob).where(Blob.sha256 == ref.sha256))
    if blob is None:
        blob = Blob(
            sha256=ref.sha256,
            size_bytes=ref.size_bytes,
            media_type=ref.media_type,
            storage_key=ref.storage_key,
        )
        db.add(blob)
        db.flush()

    asset = db.scalar(
        select(CaseAsset).where(CaseAsset.case_id == case.id, CaseAsset.role == "canonical")
    )
    if asset is None:
        db.add(
            CaseAsset(
                case_id=case.id,
                blob_id=blob.id,
                role="canonical",
                format=case.image_format,
                metadata_json={"migrated_from": str(source)},
            )
        )
    else:
        asset.blob_id = blob.id
        asset.format = case.image_format

    manifest = {
        "schema_version": 2,
        "source_kind": "legacy_v1",
        "source_name": case.source_path or source.name,
        "source_format": source.suffix.lower(),
        "canonical_format": case.image_format,
        "original_retained": True,
        "converter": "medpowers-studio/2-migration",
        "original_path": str(source),
        "original_size": size,
    }
    manifest_ref = asset_store.put_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json",
    )
    manifest_blob = db.scalar(select(Blob).where(Blob.sha256 == manifest_ref.sha256))
    if manifest_blob is None:
        manifest_blob = Blob(
            sha256=manifest_ref.sha256,
            size_bytes=manifest_ref.size_bytes,
            media_type=manifest_ref.media_type,
            storage_key=manifest_ref.storage_key,
        )
        db.add(manifest_blob)
        db.flush()
    manifest_asset = db.scalar(
        select(CaseAsset).where(CaseAsset.case_id == case.id, CaseAsset.role == "source_manifest")
    )
    if manifest_asset is None:
        db.add(
            CaseAsset(
                case_id=case.id,
                blob_id=manifest_blob.id,
                role="source_manifest",
                format="json",
                metadata_json={},
            )
        )

    case.image_path = ref.storage_key
    case.data_kind = _case_data_kind(case)
    case.size_bytes = ref.size_bytes
    case.sha256 = ref.sha256
    case.metadata_json = {
        **(case.metadata_json or {}),
        "data_kind": case.data_kind,
        "canonical_format": case.image_format,
        "original_retained": True,
        "storage_migrated": True,
    }
    return 1, ref.size_bytes, None


def _migrate_annotation_path(value: str | None, old_root: Path, new_root: Path) -> str | None:
    if not value:
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        return value
    key = _copy_relative(path, old_root, new_root)
    return key if key is not None else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只统计")
    parser.add_argument("--dry-run", action="store_true", help="显式 dry-run（默认行为）")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--old-storage-root",
        default=str(BACKEND_DIR / "storage"),
        help="v1 storage 根目录（默认 backend/storage）",
    )
    parser.add_argument("--skip-annotations", action="store_true")
    parser.add_argument("--skip-files", action="store_true", help="只改路径，不复制 Blob")
    parser.add_argument("--resume", action="store_true", help="断点续跑（已迁移 Case 自动跳过）")
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    old_root = Path(args.old_storage_root).expanduser().resolve()
    new_root = storage.settings_root()
    init_db()
    ensure_dirs()
    print(f"旧存储根：{old_root}")
    print(f"新存储根：{new_root}")
    print(f"模式：{'APPLY' if apply else 'DRY-RUN'}")

    cases_done = 0
    total_bytes = 0
    errors: list[str] = []

    with SessionLocal() as db:
        query = select(Case).order_by(Case.created_at)
        if args.limit:
            query = query.limit(args.limit)
        cases = db.scalars(query).all()
        for index, case in enumerate(cases, start=1):
            if args.skip_files:
                case.image_path = str(_old_path(case.image_path, old_root))
                case.data_kind = _case_data_kind(case)
                cases_done += 1
                continue
            count, size, error = _migrate_case(db, case, old_root, apply)
            cases_done += count
            total_bytes += size
            if error:
                errors.append(f"{case.case_uid}: {error}")
            if apply and index % 100 == 0:
                db.commit()
                print(f"  已处理 {index}/{len(cases)} 个 Case，累计 {total_bytes / 1024**3:.2f} GB")

        if apply and not args.skip_annotations:
            annotations = db.scalars(select(Annotation)).all()
            for annotation in annotations:
                annotation.data_path = _migrate_annotation_path(
                    annotation.data_path, old_root, new_root
                )
                annotation.mask_path = _migrate_annotation_path(
                    annotation.mask_path, old_root, new_root
                )
            revisions = db.scalars(select(AnnotationRevision)).all()
            for revision in revisions:
                revision.data_path = _migrate_annotation_path(
                    revision.data_path, old_root, new_root
                )
                revision.mask_path = _migrate_annotation_path(
                    revision.mask_path, old_root, new_root
                )

        if apply:
            for dataset in db.scalars(select(Dataset)).all():
                dataset.storage_path = storage.dataset_key(dataset.id)
                if not dataset.data_kind:
                    dataset.data_kind = (
                        "table"
                        if dataset.dimension == "tabular"
                        else ("image2d" if dataset.dimension == "2d" else "volume3d")
                    )
            for job in db.scalars(select(ExportJob)).all():
                if job.output_dir:
                    job.output_dir = (
                        _migrate_annotation_path(job.output_dir, old_root, new_root)
                        or job.output_dir
                    )
                if job.manifest_path:
                    job.manifest_path = _migrate_annotation_path(
                        job.manifest_path, old_root, new_root
                    )
            for job in db.scalars(select(EvaluationJob)).all():
                if job.prediction_path:
                    job.prediction_path = (
                        _migrate_annotation_path(job.prediction_path, old_root, new_root)
                        or job.prediction_path
                    )
                if job.report_path:
                    job.report_path = _migrate_annotation_path(job.report_path, old_root, new_root)
            db.commit()

    print(f"\nCase 处理：{cases_done}，累计 {total_bytes / 1024**3:.2f} GB")
    if errors:
        print(f"错误 {len(errors)} 条：")
        for item in errors[:20]:
            print(f"  - {item}")
        if len(errors) > 20:
            print(f"  ... 其余 {len(errors) - 20} 条")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
