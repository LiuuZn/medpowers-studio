from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import SimpleITK as sitk
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.constants import JOB_FAILED, JOB_RUNNING, JOB_SUCCEEDED
from ..domain.task_types import get_task_type
from ..metrics import detection as detection_metrics
from ..metrics import keyframe as keyframe_metrics
from ..metrics import segmentation as seg_metrics
from ..models import Annotation, AnnotationRevision, Case, EvaluationJob, Task
from . import storage


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _label_lookup(task: Task) -> dict[int, str]:
    kind = get_task_type(task.task_type).annotation_kind
    key = "classes" if kind == "mask" else "labels"
    return {int(item["id"]): str(item["name"]) for item in task.label_schema.get(key, [])}


def _label_ids(task: Task, include_background: bool = False) -> list[int]:
    ids = sorted(_label_lookup(task).keys())
    if not include_background:
        ids = [i for i in ids if i != 0]
    return ids


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


def _collect_gt(
    db: Session, task: Task, dataset_ids: list[str], statuses: list[str]
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Case, Annotation)
        .join(Annotation, Annotation.case_id == Case.id)
        .where(
            Annotation.task_id == task.id,
            Case.dataset_id.in_(dataset_ids),
            Annotation.status.in_(statuses),
        )
        .order_by(Case.case_uid)
    ).all()
    result = []
    for case, annotation in rows:
        data, mask_path = _snapshot(db, annotation)
        result.append(
            {
                "case": case,
                "annotation": annotation,
                "data": data,
                "mask_path": mask_path,
            }
        )
    return result


def _iter_prediction_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        name = path.name
        stem = name[:-7] if name.lower().endswith(".nii.gz") else path.stem
        if stem.endswith("_0000"):
            stem = stem[:-5]
        result.setdefault(stem, path)
    return result


def _read_mask(path: str | Path) -> np.ndarray:
    path = Path(path)
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
        with Image.open(path) as image:
            return np.asarray(image.convert("L"))
    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    if array.ndim != 3:
        raise ValueError(f"预测掩码维度应为 3D，实际为 {array.ndim}D")
    return array


def _aggregate_segmentation(per_case: list[dict[str, Any]], label_ids: list[int]) -> dict[str, Any]:
    classes: dict[str, Any] = {}
    all_dice: list[float] = []
    for label_id in label_ids:
        metrics = {}
        for metric in ("dice", "iou", "precision", "recall", "hd95"):
            values = []
            for case in per_case:
                class_result = case.get("classes", {}).get(str(label_id))
                if not class_result or not class_result.get("present"):
                    continue
                value = class_result.get(metric)
                if value is not None:
                    values.append(float(value))
            if values:
                metrics[metric] = {
                    "count": len(values),
                    "mean": round(float(np.mean(values)), 6),
                    "median": round(float(np.median(values)), 6),
                    "std": round(float(np.std(values)), 6),
                }
            else:
                metrics[metric] = {"count": 0, "mean": None, "median": None, "std": None}
        classes[str(label_id)] = metrics
        values = [
            float(case["classes"][str(label_id)]["dice"])
            for case in per_case
            if case.get("classes", {}).get(str(label_id), {}).get("present")
        ]
        all_dice.extend(values)

    return {
        "case_count": len(per_case),
        "classes": classes,
        "mean_dice": round(float(np.mean(all_dice)), 6) if all_dice else None,
    }


def _aggregate_counts(per_case: list[dict[str, Any]], label_ids: list[int]) -> dict[str, Any]:
    classes = {}
    total_tp = total_fp = total_fn = 0
    for label_id in label_ids:
        tp = sum(int(c.get("per_label", {}).get(str(label_id), {}).get("tp", 0)) for c in per_case)
        fp = sum(int(c.get("per_label", {}).get(str(label_id), {}).get("fp", 0)) for c in per_case)
        fn = sum(int(c.get("per_label", {}).get(str(label_id), {}).get("fn", 0)) for c in per_case)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ious = [
            c["per_label"][str(label_id)]["mean_iou"]
            for c in per_case
            if c.get("per_label", {}).get(str(label_id), {}).get("mean_iou") is not None
        ]
        classes[str(label_id)] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "mean_iou": round(float(np.mean(ious)), 6) if ious else None,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn

    precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 1.0
    recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "case_count": len(per_case),
        "classes": classes,
        "overall": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        },
    }


def _deep_get(payload: dict[str, Any], case_uid: str) -> Any:
    if "cases" in payload and isinstance(payload["cases"], dict):
        return payload["cases"].get(case_uid)
    return payload.get(case_uid)


def _load_predictions_json(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in root.rglob("*.json"):
        if path.name.startswith("."):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            if "cases" in payload and isinstance(payload["cases"], dict):
                result.update(payload["cases"])
            elif "case_uid" in payload:
                result[str(payload["case_uid"])] = payload
            else:
                result.update(payload)
    return result


def _evaluate_seg(
    db: Session, task: Task, gt_cases: list[dict[str, Any]], pred_root: Path, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    include_background = bool(config.get("include_background", False))
    label_ids = _label_ids(task, include_background)
    files = _iter_prediction_files(pred_root)
    per_case: list[dict[str, Any]] = []

    for item in gt_cases:
        case: Case = item["case"]
        gt_mask_path = item["mask_path"]
        pred_path = files.get(case.case_uid)
        if not gt_mask_path or not storage.resolve_key(gt_mask_path).exists():
            per_case.append({"case_uid": case.case_uid, "error": "缺少金标准掩码"})
            continue
        if not pred_path:
            per_case.append({"case_uid": case.case_uid, "error": "缺少预测文件"})
            continue
        try:
            gt = _read_mask(storage.resolve_key(gt_mask_path))
            pred = _read_mask(pred_path)
            if gt.shape != pred.shape:
                raise ValueError(f"预测与金标准尺寸不一致：{pred.shape} vs {gt.shape}")
            spacing = (
                list(reversed(case.geometry.get("spacing", [])))
                if case.data_kind == "volume3d" or case.image_format == "nrrd"
                else None
            )
            class_results = {}
            for label_id in label_ids:
                gt_binary = gt == label_id
                pred_binary = pred == label_id
                present = bool(gt_binary.any() or pred_binary.any())
                result = seg_metrics.segmentation_metrics(gt_binary, pred_binary, spacing)
                result["present"] = present
                class_results[str(label_id)] = result
            per_case.append(
                {
                    "case_uid": case.case_uid,
                    "dataset_id": case.dataset_id,
                    "prediction_file": str(pred_path),
                    "classes": class_results,
                }
            )
        except Exception as exc:  # noqa: BLE001
            per_case.append({"case_uid": case.case_uid, "error": str(exc)})

    valid = [c for c in per_case if "classes" in c]
    if not valid:
        raise ValueError("没有任何病例完成评估，请检查预测文件命名与格式")
    return per_case, _aggregate_segmentation(valid, label_ids)


def _evaluate_keyframe(
    task: Task, gt_cases: list[dict[str, Any]], pred_root: Path, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tolerance = int(config.get("keyframe_tolerance", 1))
    label_ids = _label_ids(task)
    predictions = _load_predictions_json(pred_root)
    per_case = []
    for item in gt_cases:
        case: Case = item["case"]
        gt_frames = item["data"].get("frames", [])
        payload = _deep_get(predictions, case.case_uid)
        if payload is None:
            per_case.append({"case_uid": case.case_uid, "error": "缺少预测结果"})
            continue
        pred_frames = payload.get("frames", []) if isinstance(payload, dict) else payload
        try:
            result = keyframe_metrics.evaluate_case(
                gt_frames, pred_frames or [], label_ids, tolerance
            )
            per_case.append(
                {
                    "case_uid": case.case_uid,
                    "dataset_id": case.dataset_id,
                    "per_label": result["per_label"],
                    "tp": result["tp"],
                    "fp": result["fp"],
                    "fn": result["fn"],
                    "mean_abs_error": result["mean_abs_error"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            per_case.append({"case_uid": case.case_uid, "error": str(exc)})
    valid = [c for c in per_case if "per_label" in c]
    if not valid:
        raise ValueError("没有任何病例完成评估，请检查 predictions.json")
    aggregate = _aggregate_counts(valid, label_ids)
    errors = [c["mean_abs_error"] for c in valid if c.get("mean_abs_error") is not None]
    aggregate["mean_abs_error"] = round(float(np.mean(errors)), 4) if errors else None
    aggregate["tolerance"] = tolerance
    return per_case, aggregate


def _evaluate_detection(
    task: Task, gt_cases: list[dict[str, Any]], pred_root: Path, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    threshold = float(config.get("iou_threshold", 0.5))
    label_ids = _label_ids(task)
    predictions = _load_predictions_json(pred_root)
    per_case = []
    for item in gt_cases:
        case: Case = item["case"]
        gt_boxes = item["data"].get("boxes", [])
        payload = _deep_get(predictions, case.case_uid)
        if payload is None:
            per_case.append({"case_uid": case.case_uid, "error": "缺少预测结果"})
            continue
        pred_boxes = payload.get("boxes", []) if isinstance(payload, dict) else payload
        try:
            result = detection_metrics.evaluate_case(
                gt_boxes, pred_boxes or [], label_ids, threshold
            )
            per_case.append(
                {
                    "case_uid": case.case_uid,
                    "dataset_id": case.dataset_id,
                    "per_label": result["per_label"],
                    "tp": result["tp"],
                    "fp": result["fp"],
                    "fn": result["fn"],
                    "mean_iou": result["mean_iou"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            per_case.append({"case_uid": case.case_uid, "error": str(exc)})
    valid = [c for c in per_case if "per_label" in c]
    if not valid:
        raise ValueError("没有任何病例完成评估，请检查 predictions.json")
    aggregate = _aggregate_counts(valid, label_ids)
    aggregate["iou_threshold"] = threshold
    return per_case, aggregate


def run_evaluation(db: Session, job_id: str) -> None:
    job = db.get(EvaluationJob, job_id)
    if not job:
        return
    job.status = JOB_RUNNING
    job.started_at = datetime.now(UTC)
    db.commit()

    try:
        task = db.get(Task, job.task_id)
        if not task:
            raise ValueError("任务不存在")
        gt_cases = _collect_gt(db, task, job.dataset_ids, job.gt_statuses)
        if not gt_cases:
            raise ValueError("没有符合状态要求的金标准标注，无法评估")
        pred_root = storage.resolve_key(job.prediction_path)
        if not pred_root.exists():
            raise ValueError("预测结果目录不存在")

        kind = get_task_type(task.task_type).annotation_kind
        if kind == "mask":
            per_case, aggregate = _evaluate_seg(db, task, gt_cases, pred_root, job.metrics_config)
        elif kind == "keyframe":
            per_case, aggregate = _evaluate_keyframe(task, gt_cases, pred_root, job.metrics_config)
        else:
            per_case, aggregate = _evaluate_detection(task, gt_cases, pred_root, job.metrics_config)

        report = {
            "evaluation_id": job.id,
            "name": job.name,
            "created_at": datetime.now(UTC).isoformat(),
            "task": {
                "id": task.id,
                "code": task.code,
                "name": task.name,
                "task_type": task.task_type,
                "label_schema": task.label_schema,
            },
            "datasets": job.dataset_ids,
            "gt_statuses": job.gt_statuses,
            "metrics_config": job.metrics_config,
            "aggregate": aggregate,
            "per_case": per_case,
        }
        report_path = storage.evaluation_dir(job.id) / "report.json"
        _write_json(report_path, report)
        job.report_path = storage.key_for(report_path)
        job.summary = aggregate
        job.status = JOB_SUCCEEDED
        job.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(EvaluationJob, job_id)
        if job:
            job.status = JOB_FAILED
            job.error = str(exc)
            job.finished_at = datetime.now(UTC)
            db.commit()


__all__ = ["run_evaluation"]
