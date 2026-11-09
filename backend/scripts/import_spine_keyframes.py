"""把 spine_locator 的 3D 影像与 T12/T13/L1 关键帧标注导入 MedPowers Studio。

数据来源（spine_locator 仓库）：
- 影像：``/ssd/data/spine/images/*.nrrd``（复制到平台内容寻址 Blob，同一哈希去重）
- 标注：``/home/liuxin/lx/spine_locator/nrrd_slice_mapping.json``，结构为
  ``{case_id: {"T12": z, "T13": z, "L1": z}}``，缺失目标表示该例未标注。

导入结果：
- 数据集（CT / 3D）+ 扫描流程；
- ``keyframe3d`` 任务，标签体系 ``T12=1 / T13=2 / L1=3``；
- 每个有标注的病例一条 ``in_progress`` 标注，关键帧写入 ``data.frames``，
  前端可直接阅片、跳转与调整。

用法（在 backend 目录）：
    uv run python scripts/import_spine_keyframes.py --dry-run --limit 10
    uv run python scripts/import_spine_keyframes.py
    uv run python scripts/import_spine_keyframes.py --include-unannotated
    uv run python scripts/import_spine_keyframes.py --update-annotations

脚本幂等：数据集/任务按编码复用，病例按 ``case_uid`` 复用，已有标注默认不覆盖
（需要把 mapping 重新同步到未提交标注时加 ``--update-annotations``）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import SimpleITK as sitk
from sqlalchemy import func, select
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, ensure_dirs, init_db  # noqa: E402
from app.domain.constants import (  # noqa: E402
    ANNOTATION_APPROVED,
    ANNOTATION_IN_PROGRESS,
    ANNOTATION_PENDING,
    ANNOTATION_REJECTED,
    ANNOTATION_SUBMITTED,
)
from app.domain.task_types import normalize_label_schema  # noqa: E402
from app.main import bootstrap_admin  # noqa: E402
from app.models import (  # noqa: E402
    Annotation,
    Blob,
    Case,
    CaseAsset,
    Dataset,
    ScanProtocol,
    Task,
    TaskDataset,
    User,
    new_id,
)
from app.services import asset_store, hierarchy, storage  # noqa: E402
from app.services.hierarchy import SeriesMetadata  # noqa: E402

DEFAULT_MAPPING = BACKEND_DIR.parent.parent / "spine_locator" / "nrrd_slice_mapping.json"
DEFAULT_IMAGES_DIR = Path("/ssd/data/spine/images")
DEFAULT_DATASET_CODE = "spine_keyplane"
DEFAULT_TASK_CODE = "spine_keyplane_keyframes"
DEFAULT_PROTOCOL_CODE = "spine_ct_keyplane"

# spine_locator 的标签顺序即 mapping 中的目标顺序
LABELS: list[tuple[str, int, str]] = [
    ("T12", 1, "#1677ff"),
    ("T13", 2, "#fa8c16"),
    ("L1", 3, "#52c41a"),
]
LABEL_IDS = {name: label_id for name, label_id, _ in LABELS}


@dataclass
class ImportStats:
    total_mapping: int = 0
    cases_created: int = 0
    cases_updated: int = 0
    cases_skipped: int = 0
    annotations_created: int = 0
    annotations_updated: int = 0
    annotations_skipped: int = 0
    frames_imported: int = 0
    errors: list[str] = field(default_factory=list)


def _read_geometry(path: Path) -> dict[str, Any]:
    """只读 NRRD 头，避免为 2727 个病例加载全部像素。"""
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()
    size = [int(v) for v in reader.GetSize()]
    spacing = [float(v) if v > 0 else 1.0 for v in reader.GetSpacing()]
    return {
        "size": size,  # ITK: x, y, z
        "spacing": spacing,
        "origin": [float(v) for v in reader.GetOrigin()],
        "direction": [float(v) for v in reader.GetDirection()],
        "array_shape": [size[2], size[1], size[0]],  # z, y, x
        "pixel_type": sitk.GetPixelIDValueAsString(reader.GetPixelID()),
    }


def _frames_from_annotation(entry: dict[str, Any]) -> list[dict[str, int]]:
    frames = []
    for name, label_id, _ in LABELS:
        value = entry.get(name)
        if value is None:
            continue
        frames.append({"label_id": label_id, "z_index": int(value)})
    frames.sort(key=lambda item: (item["z_index"], item["label_id"]))
    return frames


def _ensure_protocol(db: Session) -> ScanProtocol:
    protocol = db.scalar(select(ScanProtocol).where(ScanProtocol.code == DEFAULT_PROTOCOL_CODE))
    if protocol:
        return protocol
    protocol = ScanProtocol(
        code=DEFAULT_PROTOCOL_CODE,
        name="脊柱关键层面 CT",
        description="spine_locator 使用的胸部/脊柱厚层 CT，用于 T12/T13/L1 关键层面定位。",
        modality_scope=["CT"],
        sort_order=10,
        is_active=True,
    )
    db.add(protocol)
    db.flush()
    return protocol


def _ensure_dataset(db: Session, protocol: ScanProtocol, mapping: Path) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.code == DEFAULT_DATASET_CODE))
    if dataset:
        if dataset.modality != "CT" or dataset.dimension != "3d":
            raise SystemExit(
                f"数据集 {DEFAULT_DATASET_CODE} 已存在，但不是 CT/3D（"
                f"{dataset.modality}/{dataset.dimension}），无法复用。"
            )
        return dataset
    dataset_id = new_id()
    dataset = Dataset(
        id=dataset_id,
        code=DEFAULT_DATASET_CODE,
        name="脊柱关键层面 CT（spine_locator）",
        description=(
            "来自 spine_locator 的 3D 厚层 CT。影像复制到平台内容寻址存储，"
            f"标注来自 {mapping.name}，标签为 T12 / T13 / L1。"
        ),
        modality="CT",
        dimension="3d",
        data_kind="volume3d",
        scan_protocol_id=protocol.id,
        status="draft",
        case_count=0,
        storage_path=storage.dataset_key(dataset_id),
    )
    db.add(dataset)
    db.flush()
    return dataset


def _label_schema() -> dict[str, Any]:
    schema = {
        "labels": [
            {"id": label_id, "name": name, "color": color}
            for name, label_id, color in LABELS
        ]
    }
    return normalize_label_schema("keyframe3d", schema)


def _ensure_task(db: Session) -> Task:
    task = db.scalar(select(Task).where(Task.code == DEFAULT_TASK_CODE))
    if task:
        if task.task_type != "keyframe3d":
            raise SystemExit(
                f"任务 {DEFAULT_TASK_CODE} 已存在，但类型为 {task.task_type}，不是 keyframe3d。"
            )
        return task
    task = Task(
        code=DEFAULT_TASK_CODE,
        name="脊柱关键层面关键帧（T12/T13/L1）",
        description="在 3D CT 中选取 T12、T13、L1 三个关键层面（z 切片索引）。",
        task_type="keyframe3d",
        dimension="3d",
        label_schema=_label_schema(),
        annotation_guide=(
            "轴位阅片，拖动层面滑杆定位关键层面后，选择标签并加入关键帧。\n"
            "T12 / T13 / L1 各一帧；T13 为 T12 与 L1 之间的椎间隙层面。\n"
            "标注以 z 切片索引为准（与 spine_locator 的 nrrd_slice_mapping.json 一致）。"
        ),
        status="active",
    )
    db.add(task)
    db.flush()
    return task


def _ensure_link(db: Session, task: Task, dataset: Dataset) -> None:
    link = db.scalar(
        select(TaskDataset).where(
            TaskDataset.task_id == task.id, TaskDataset.dataset_id == dataset.id
        )
    )
    if not link:
        db.add(TaskDataset(task_id=task.id, dataset_id=dataset.id))
        db.flush()


def _load_mapping(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"找不到标注文件：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"标注文件格式错误（应为 JSON object）：{path}")
    return data


def _iter_nrrd_files(images_dir: Path) -> dict[str, Path]:
    return {path.stem: path for path in sorted(images_dir.glob("*.nrrd"))}


def _validate_frames(
    case_uid: str, entry: dict[str, Any], slices: int, stats: ImportStats
) -> list[dict[str, int]] | None:
    frames = _frames_from_annotation(entry)
    for frame in frames:
        if not 0 <= frame["z_index"] < slices:
            stats.errors.append(
                f"{case_uid}: z_index={frame['z_index']} 超出范围（共 {slices} 层），已跳过该例"
            )
            stats.cases_skipped += 1
            return None
    if not frames:
        stats.cases_skipped += 1
        return None
    return frames


def _write_annotation_data(
    task: Task, case: Case, frames: list[dict[str, int]]
) -> tuple[dict[str, Any], str]:
    data = {"frames": frames}
    current = storage.annotation_current_dir(task.id, case.id)
    data_path = current / "data.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data, storage.key_for(data_path)


def _ensure_blob(db: Session, image_path: Path) -> Blob:
    ref = asset_store.put_file(image_path, "application/octet-stream")
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
    return blob


def _ensure_canonical_asset(db: Session, case: Case, blob: Blob) -> None:
    asset = db.scalar(
        select(CaseAsset).where(CaseAsset.case_id == case.id, CaseAsset.role == "canonical")
    )
    if asset is None:
        db.add(
            CaseAsset(
                case_id=case.id,
                blob_id=blob.id,
                role="canonical",
                format="nrrd",
                metadata_json={},
            )
        )
    else:
        asset.blob_id = blob.id


def _upsert_case(
    db: Session,
    dataset: Dataset,
    case_uid: str,
    image_path: Path,
    geometry: dict[str, Any],
    series_meta: SeriesMetadata,
    mapping: Path,
    has_annotation: bool,
    stats: ImportStats,
) -> Case:
    case = db.scalar(
        select(Case).where(Case.dataset_id == dataset.id, Case.case_uid == case_uid)
    )
    assignment = hierarchy.assign_hierarchy(db, dataset, case_uid, series_meta)
    blob = _ensure_blob(db, image_path)
    metadata = {
        "source_name": image_path.name,
        "source_kind": "volume_file",
        "shape": geometry["array_shape"],
        "spacing": geometry["spacing"],
        "pixel_type": geometry["pixel_type"],
        "data_kind": "volume3d",
        "canonical_format": "nrrd",
        "original_retained": True,
        "annotation_source": str(mapping) if has_annotation else None,
        "has_annotation": has_annotation,
    }
    metadata.update(series_meta.safe_metadata(assignment.patient_key))
    if case:
        case.study_id = assignment.study.id
        case.series_uid = assignment.series_uid
        case.series_number = series_meta.series_number
        case.series_description = series_meta.series_description
        case.patient_key = assignment.patient_key
        case.image_path = blob.storage_key
        case.image_format = "nrrd"
        case.data_kind = "volume3d"
        case.size_bytes = blob.size_bytes
        case.sha256 = blob.sha256
        case.geometry = geometry
        case.source_kind = "volume_file"
        case.source_path = image_path.name
        case.metadata_json = metadata
        _ensure_canonical_asset(db, case, blob)
        stats.cases_updated += 1
        return case
    case = Case(
        id=new_id(),
        dataset_id=dataset.id,
        study_id=assignment.study.id,
        case_uid=case_uid,
        series_uid=assignment.series_uid,
        series_number=series_meta.series_number,
        series_description=series_meta.series_description,
        patient_key=assignment.patient_key,
        image_path=blob.storage_key,
        image_format="nrrd",
        data_kind="volume3d",
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        geometry=geometry,
        source_kind="volume_file",
        source_path=image_path.name,
        metadata_json=metadata,
    )
    db.add(case)
    db.flush()
    _ensure_canonical_asset(db, case, blob)
    stats.cases_created += 1
    return case


def _upsert_annotation(
    db: Session,
    task: Task,
    case: Case,
    frames: list[dict[str, int]],
    admin: User,
    update_existing: bool,
    stats: ImportStats,
) -> None:
    annotation = db.scalar(
        select(Annotation).where(Annotation.task_id == task.id, Annotation.case_id == case.id)
    )
    if annotation is None:
        data, data_path = _write_annotation_data(task, case, frames)
        db.add(
            Annotation(
                task_id=task.id,
                case_id=case.id,
                status=ANNOTATION_IN_PROGRESS,
                data=data,
                data_path=data_path,
                version=0,
                annotator_id=admin.id,
            )
        )
        stats.annotations_created += 1
        stats.frames_imported += len(frames)
        return

    if not update_existing:
        stats.annotations_skipped += 1
        return
    if annotation.status in (ANNOTATION_SUBMITTED, ANNOTATION_APPROVED):
        stats.errors.append(
            f"{case.case_uid}: 标注状态为 {annotation.status}，不覆盖已提交/已通过标注"
        )
        stats.annotations_skipped += 1
        return
    data, data_path = _write_annotation_data(task, case, frames)
    annotation.data = data
    annotation.data_path = data_path
    if annotation.status not in (ANNOTATION_IN_PROGRESS, ANNOTATION_PENDING, ANNOTATION_REJECTED):
        annotation.status = ANNOTATION_IN_PROGRESS
    stats.annotations_updated += 1
    stats.frames_imported += len(frames)


def _existing_case_count(db: Session, dataset: Dataset) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Case).where(Case.dataset_id == dataset.id))
        or 0
    )


def run(args: argparse.Namespace) -> ImportStats:
    mapping_path = Path(args.mapping).expanduser().resolve()
    annotations = _load_mapping(mapping_path)
    images_dir = Path(args.images_dir).expanduser().resolve()
    if not images_dir.is_dir():
        raise SystemExit(f"影像目录不存在：{images_dir}")
    image_files = _iter_nrrd_files(images_dir)
    if not image_files:
        raise SystemExit(f"影像目录中没有 .nrrd 文件：{images_dir}")

    # 组织待导入清单：默认只含有标注的病例（与 spine_locator 训练口径一致）
    selected: list[tuple[str, dict[str, Any] | None]] = []
    for case_uid, entry in annotations.items():
        if case_uid in image_files:
            selected.append((case_uid, entry))
    missing = [case_uid for case_uid in annotations if case_uid not in image_files]
    stats = ImportStats(total_mapping=len(annotations))
    for case_uid in missing[:20]:
        stats.errors.append(f"{case_uid}: mapping 存在但影像文件缺失")
    if args.include_unannotated:
        annotated = {case_uid for case_uid, _ in selected}
        for case_uid in image_files:
            if case_uid not in annotated:
                selected.append((case_uid, None))
    if args.limit is not None:
        selected = selected[: args.limit]

    print(f"影像目录：{images_dir}")
    print(f"标注文件：{mapping_path}（{len(annotations)} 例）")
    print(
        f"待处理：{len(selected)} 例"
        f"（含标注 {sum(1 for _, entry in selected if entry is not None)} 例"
        f"，无标注 {sum(1 for _, entry in selected if entry is None)} 例）"
    )
    if args.dry_run:
        for case_uid, entry in selected[:3]:
            geometry = _read_geometry(image_files[case_uid])
            if entry is not None:
                print(
                    f"  [dry-run] {case_uid}: shape={geometry['array_shape']} "
                    f"spacing={geometry['spacing']} frames={_frames_from_annotation(entry)}"
                )
            else:
                print(f"  [dry-run] {case_uid}: shape={geometry['array_shape']}（无标注）")
        print("dry-run 完成，未写入数据库。")
        return stats

    init_db()
    ensure_dirs()
    bootstrap_admin()

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            raise SystemExit("未找到 admin 账号，无法建立导入标注。")
        protocol = _ensure_protocol(db)
        dataset = _ensure_dataset(db, protocol, mapping_path)
        task = _ensure_task(db)
        _ensure_link(db, task, dataset)
        db.commit()

        for index, (case_uid, entry) in enumerate(selected, start=1):
            try:
                geometry = _read_geometry(image_files[case_uid])
                series_meta = hierarchy.read_volume_metadata(image_files[case_uid])
                frames = None
                if entry is not None:
                    frames = _validate_frames(
                        case_uid, entry, geometry["array_shape"][0], stats
                    )
                    if frames is None:
                        continue
                case = _upsert_case(
                    db,
                    dataset,
                    case_uid,
                    image_files[case_uid],
                    geometry,
                    series_meta,
                    mapping_path,
                    entry is not None,
                    stats,
                )
                if frames is not None:
                    _upsert_annotation(
                        db, task, case, frames, admin, args.update_annotations, stats
                    )
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"{case_uid}: {exc}")
                stats.cases_skipped += 1
            if index % args.batch_size == 0:
                db.commit()
                print(f"  已处理 {index}/{len(selected)} 例...")

        dataset.case_count = _existing_case_count(db, dataset)
        if dataset.case_count > 0:
            dataset.status = "ready"
        db.commit()

        print()
        print("导入完成")
        print(f"  病例：新增 {stats.cases_created}，更新 {stats.cases_updated}，"
              f"跳过 {stats.cases_skipped}；数据集现有 {dataset.case_count} 例")
        print(f"  标注：新增 {stats.annotations_created}，更新 {stats.annotations_updated}，"
              f"保留 {stats.annotations_skipped}；写入关键帧 {stats.frames_imported} 条")
        print(f"  任务：{task.code} ({task.id})")
        if stats.errors:
            print(f"  问题 {len(stats.errors)} 条（显示前 20 条）：")
            for message in stats.errors[:20]:
                print(f"    - {message}")
        return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入 spine_locator 影像与关键帧标注")
    parser.add_argument(
        "--mapping", default=str(DEFAULT_MAPPING), help="nrrd_slice_mapping.json 路径"
    )
    parser.add_argument("--images-dir", default=str(DEFAULT_IMAGES_DIR), help="NRRD 影像目录")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 例（调试用）")
    parser.add_argument(
        "--include-unannotated",
        action="store_true",
        help="除有标注病例外，同时登记目录中没有 mapping 标注的影像",
    )
    parser.add_argument(
        "--update-annotations",
        action="store_true",
        help="已存在且未提交/未通过的标注按 mapping 重新同步",
    )
    parser.add_argument("--batch-size", type=int, default=200, help="每批提交的病例数")
    parser.add_argument("--dry-run", action="store_true", help="只读取与打印，不写数据库")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size <= 0:
        raise SystemExit("--batch-size 必须大于 0")
    started = datetime.now(UTC)
    stats = run(args)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"耗时 {elapsed:.1f}s")
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
