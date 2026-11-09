from __future__ import annotations

from typing import Any


def match_frames(
    gt_frames: list[dict[str, Any]],
    pred_frames: list[dict[str, Any]],
    label_id: int,
    tolerance: int,
) -> dict[str, Any]:
    gt = [f for f in gt_frames if int(f.get("label_id", 0)) == label_id]
    pred = [f for f in pred_frames if int(f.get("label_id", 0)) == label_id]
    candidates = []
    for gi, g in enumerate(gt):
        for pi, p in enumerate(pred):
            distance = abs(int(g["z_index"]) - int(p["z_index"]))
            if distance <= tolerance:
                candidates.append((distance, gi, pi))
    candidates.sort()

    used_gt: set[int] = set()
    used_pred: set[int] = set()
    errors: list[int] = []
    for distance, gi, pi in candidates:
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        errors.append(distance)

    tp = len(errors)
    fp = len(pred) - tp
    fn = len(gt) - tp
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "mean_abs_error": round(sum(errors) / len(errors), 4) if errors else None,
    }


def evaluate_case(
    gt_frames: list[dict[str, Any]],
    pred_frames: list[dict[str, Any]],
    label_ids: list[int],
    tolerance: int,
) -> dict[str, Any]:
    per_label = {}
    total_tp = total_fp = total_fn = 0
    errors: list[float] = []
    for label_id in label_ids:
        result = match_frames(gt_frames, pred_frames, label_id, tolerance)
        per_label[str(label_id)] = result
        total_tp += result["tp"]
        total_fp += result["fp"]
        total_fn += result["fn"]
        if result["mean_abs_error"] is not None:
            errors.append(result["mean_abs_error"])
    return {
        "per_label": per_label,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "mean_abs_error": round(sum(errors) / len(errors), 4) if errors else None,
    }
