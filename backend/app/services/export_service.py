from __future__ import annotations

import json
import random
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.constants import ANNOTATION_STATUSES, JOB_FAILED, JOB_RUNNING, JOB_SUCCEEDED
from ..domain.task_types import get_task_type
from ..models import Annotation, AnnotationRevision, Case, Dataset, ExportJob, Task, TaskDataset
from . import storage


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _label_lookup(task: Task) -> dict[int, str]:
    kind = get_task_type(task.task_type).annotation_kind
    key = "classes" if kind == "mask" else "labels"
    return {int(item["id"]): str(item["name"]) for item in task.label_schema.get(key, [])}


def _snapshot(db: Session, annotation: Annotation) -> tuple[dict[str, Any], str | None]:
    revision = db.scalar(
        select(AnnotationRevision)
        .where(
            AnnotationRevision.annotation_id == annotation.id,
            AnnotationRevision.version == annotation.version,
        )
        .order_by(AnnotationRevision.created_at.desc())
    )
    if revision:
        return revision.data or {}, revision.mask_path
    return annotation.data or {}, annotation.mask_path


def _collect_cases(
    db: Session, task: Task, dataset_ids: list[str], include_statuses: list[str]
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Case, Annotation, Dataset)
        .join(Annotation, Annotation.case_id == Case.id)
        .join(Dataset, Dataset.id == Case.dataset_id)
        .where(
            Annotation.task_id == task.id,
            Case.dataset_id.in_(dataset_ids),
            Annotation.status.in_(include_statuses),
        )
        .order_by(Case.case_uid)
    ).all()
    result = []
    for case, annotation, dataset in rows:
        data, mask_path = _snapshot(db, annotation)
        result.append(
            {
                "case": case,
                "dataset": dataset,
                "annotation": annotation,
                "data": data,
                "mask_path": mask_path,
            }
        )
    return result


def _case_key(item: dict[str, Any]) -> str:
    return item.get("export_name") or item["case"].case_uid


def _split_cases(
    cases: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    case_keys = [_case_key(c) for c in cases]
    by_key = {_case_key(c): c for c in cases}

    explicit = all(isinstance(config.get(k), list) for k in ("train", "val", "test"))
    if explicit:
        splits = {k: [str(v) for v in config.get(k, [])] for k in ("train", "val", "test")}
        unknown = set(sum(splits.values(), [])) - set(case_keys)
        if unknown:
            raise ValueError(f"划分中包含未选中的病例：{sorted(unknown)[:5]}")
        return splits, {"mode": "explicit", "patient_level": False}

    train_ratio = float(config.get("train", 0.7))
    val_ratio = float(config.get("val", 0.15))
    test_ratio = float(config.get("test", 0.15))
    if min(train_ratio, val_ratio, test_ratio) < 0:
        raise ValueError("划分比例不能为负数")
    if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-6:
        raise ValueError("train/val/test 比例之和必须为 1")
    seed = int(config.get("seed", 42))
    patient_level = bool(config.get("patient_level", True))

    groups: dict[str, list[str]] = defaultdict(list)
    for case_key in case_keys:
        item = by_key[case_key]
        key = (item["case"].patient_key or case_key) if patient_level else case_key
        groups[key].append(case_key)

    keys = list(groups.keys())
    random.Random(seed).shuffle(keys)
    total = len(keys)
    n_train = int(total * train_ratio)
    n_val = int(total * val_ratio)
    n_test = total - n_train - n_val
    if total >= 3:
        non_zero = [
            name
            for name, r in (("train", train_ratio), ("val", val_ratio), ("test", test_ratio))
            if r > 0
        ]
        counts = {"train": n_train, "val": n_val, "test": n_test}
        for name in non_zero:
            if counts[name] == 0:
                donor = max(counts, key=lambda k: counts[k])
                if counts[donor] > 1:
                    counts[donor] -= 1
                    counts[name] += 1
        n_train, n_val, n_test = counts["train"], counts["val"], counts["test"]

    splits = {"train": [], "val": [], "test": []}
    cursor = 0
    for name, count in (("train", n_train), ("val", n_val), ("test", n_test)):
        for key in keys[cursor : cursor + count]:
            splits[name].extend(groups[key])
        cursor += count

    meta = {
        "mode": "ratio",
        "patient_level": patient_level,
        "seed": seed,
        "ratios": {"train": train_ratio, "val": val_ratio, "test": test_ratio},
        "group_count": total,
    }
    return splits, meta


def _export_seg(
    task: Task,
    cases: list[dict[str, Any]],
    output: Path,
    file_ending: str,
    is_3d: bool,
) -> list[dict[str, Any]]:
    images_dir = output / "imagesTr"
    labels_dir = output / "labelsTr"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    label_names = _label_lookup(task)
    exported = []
    used: set[str] = set()
    for case in cases:
        case_obj: Case = case["case"]
        safe = storage.unique_name(storage.sanitize_name(case_obj.case_uid), used)
        used.add(safe)
        image_ext = f".{case_obj.image_format}" if case_obj.image_format else file_ending
        image_name = f"{safe}_0000{image_ext}" if is_3d else f"{safe}{image_ext}"
        label_name = f"{safe}{file_ending}"
        shutil.copy2(storage.case_image_path(case_obj), images_dir / image_name)
        mask_path = case["mask_path"]
        if not mask_path or not storage.resolve_key(mask_path).exists():
            raise ValueError(f"病例 {case_obj.case_uid} 缺少提交版本的分割掩码")
        shutil.copy2(storage.resolve_key(mask_path), labels_dir / label_name)
        exported.append(
            {
                "case_uid": case_obj.case_uid,
                "export_name": safe,
                "image": f"imagesTr/{image_name}",
                "label": f"labelsTr/{label_name}",
                "dataset_id": case_obj.dataset_id,
                "annotation_id": case["annotation"].id,
                "annotation_version": case["annotation"].version,
                "annotation_status": case["annotation"].status,
            }
        )

    dataset_json = {
        "name": task.code,
        "description": task.name,
        "channel_names": {"0": "image"},
        "labels": {"background": 0, **{name: idx for idx, name in label_names.items() if idx != 0}},
        "numTraining": len(exported),
        "file_ending": file_ending,
        "task_type": task.task_type,
    }
    _write_json(output / "dataset.json", dataset_json)
    return exported


def _export_json_labels(
    task: Task, cases: list[dict[str, Any]], output: Path
) -> list[dict[str, Any]]:
    images_dir = output / "images"
    labels_dir = output / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    label_names = _label_lookup(task)
    kind = get_task_type(task.task_type).annotation_kind
    exported = []
    used: set[str] = set()

    for case in cases:
        case_obj: Case = case["case"]
        safe = storage.unique_name(storage.sanitize_name(case_obj.case_uid), used)
        used.add(safe)
        image_ext = f".{case_obj.image_format}" if case_obj.image_format else ".nrrd"
        shutil.copy2(storage.case_image_path(case_obj), images_dir / f"{safe}{image_ext}")
        data = case["data"]

        if kind == "keyframe":
            items = [
                {
                    "label_id": int(frame["label_id"]),
                    "label_name": label_names.get(int(frame["label_id"]), ""),
                    "z_index": int(frame["z_index"]),
                }
                for frame in data.get("frames", [])
            ]
            payload = {"case_uid": case_obj.case_uid, "frames": items}
        else:
            items = []
            for box in data.get("boxes", []):
                item = dict(box)
                item["label_name"] = label_names.get(int(item.get("label_id", 0)), "")
                items.append(item)
            payload = {"case_uid": case_obj.case_uid, "boxes": items}

        _write_json(labels_dir / f"{safe}.json", payload)
        exported.append(
            {
                "case_uid": case_obj.case_uid,
                "export_name": safe,
                "image": f"images/{safe}{image_ext}",
                "label": f"labels/{safe}.json",
                "dataset_id": case_obj.dataset_id,
                "annotation_id": case["annotation"].id,
                "annotation_version": case["annotation"].version,
                "annotation_status": case["annotation"].status,
            }
        )

    _write_json(
        output / "dataset.json",
        {
            "name": task.code,
            "description": task.name,
            "task_type": task.task_type,
            "labels": label_names,
            "numTraining": len(exported),
            "file_ending": ".nrrd",
        },
    )
    return exported


def run_export(db: Session, job_id: str) -> None:
    job = db.get(ExportJob, job_id)
    if not job:
        return
    job.status = JOB_RUNNING
    job.started_at = datetime.now(UTC)
    db.commit()

    try:
        task = db.get(Task, job.task_id)
        if not task:
            raise ValueError("任务不存在")
        linked = set(
            db.scalars(select(TaskDataset.dataset_id).where(TaskDataset.task_id == task.id)).all()
        )
        invalid = set(job.dataset_ids) - linked
        if invalid:
            raise ValueError("所选数据集未关联到该任务")
        if not job.dataset_ids:
            raise ValueError("至少选择一个数据集")

        for status in job.include_statuses:
            if status not in ANNOTATION_STATUSES:
                raise ValueError(f"未知标注状态：{status}")

        all_cases = _collect_cases(db, task, job.dataset_ids, job.include_statuses)
        if not all_cases:
            raise ValueError("没有符合状态要求的已标注病例，无法导出")

        output = storage.export_dir(job.id)
        # 清理同名目录，保证重复执行结果一致
        for child in output.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        kind = get_task_type(task.task_type).annotation_kind
        if kind == "mask":
            is_3d = task.task_type == "seg3d"
            exported = _export_seg(task, all_cases, output, ".nrrd" if is_3d else ".png", is_3d)
        else:
            exported = _export_json_labels(task, all_cases, output)

        exported_by_key = {
            (item["dataset_id"], item["case_uid"]): item["export_name"] for item in exported
        }
        split_source = []
        for case in all_cases:
            export_name = exported_by_key.get((case["case"].dataset_id, case["case"].case_uid))
            if export_name:
                split_source.append({**case, "export_name": export_name})
        splits, split_meta = _split_cases(split_source, job.split_config)
        split_payload = {**splits, "meta": split_meta}
        _write_json(output / "splits.json", split_payload)
        _write_json(
            output / "splits_final.json",
            [{"train": splits["train"], "val": splits["val"]}],
        )

        datasets = db.scalars(select(Dataset).where(Dataset.id.in_(job.dataset_ids))).all()
        manifest = {
            "format": "medpowers-nnunet-style",
            "format_version": 1,
            "export_id": job.id,
            "export_name": job.name,
            "created_at": datetime.now(UTC).isoformat(),
            "task": {
                "id": task.id,
                "code": task.code,
                "name": task.name,
                "task_type": task.task_type,
                "dimension": task.dimension,
                "label_schema": task.label_schema,
            },
            "datasets": [
                {
                    "id": dataset.id,
                    "code": dataset.code,
                    "name": dataset.name,
                    "modality": dataset.modality,
                }
                for dataset in datasets
            ],
            "include_statuses": job.include_statuses,
            "splits": split_payload,
            "cases": exported,
        }
        manifest_path = output / "manifest.json"
        _write_json(manifest_path, manifest)

        counts = {name: len(values) for name, values in splits.items()}
        job.output_dir = storage.key_for(output)
        job.manifest_path = storage.key_for(manifest_path)
        job.summary = {
            "exported_cases": len(exported),
            "split_counts": counts,
            "split_meta": split_meta,
            "classes": _label_lookup(task),
            "format": job.format,
            "output_dir": job.output_dir,
        }
        job.status = JOB_SUCCEEDED
        job.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(ExportJob, job_id)
        if job:
            job.status = JOB_FAILED
            job.error = str(exc)
            job.finished_at = datetime.now(UTC)
            db.commit()
