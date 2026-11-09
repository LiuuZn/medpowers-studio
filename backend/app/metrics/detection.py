from __future__ import annotations

from typing import Any


def _bounds(box: dict[str, Any]) -> tuple[list[float], list[float]]:
    center = [float(v) for v in box["center_world"]]
    size = [float(v) for v in box["size_world"]]
    half = [s / 2.0 for s in size]
    return [center[i] - half[i] for i in range(3)], [center[i] + half[i] for i in range(3)]


def box_iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_min, a_max = _bounds(a)
    b_min, b_max = _bounds(b)
    inter_dims = [max(0.0, min(a_max[i], b_max[i]) - max(a_min[i], b_min[i])) for i in range(3)]
    inter = inter_dims[0] * inter_dims[1] * inter_dims[2]
    a_vol = max(0.0, (a_max[0] - a_min[0]) * (a_max[1] - a_min[1]) * (a_max[2] - a_min[2]))
    b_vol = max(0.0, (b_max[0] - b_min[0]) * (b_max[1] - b_min[1]) * (b_max[2] - b_min[2]))
    union = a_vol + b_vol - inter
    return 0.0 if union <= 0 else float(inter / union)


def match_boxes(
    gt_boxes: list[dict[str, Any]],
    pred_boxes: list[dict[str, Any]],
    label_id: int,
    threshold: float,
) -> dict[str, Any]:
    gt = [b for b in gt_boxes if int(b.get("label_id", 0)) == label_id]
    pred = [b for b in pred_boxes if int(b.get("label_id", 0)) == label_id]
    pairs = []
    for gi, g in enumerate(gt):
        for pi, p in enumerate(pred):
            pairs.append((box_iou(g, p), gi, pi))
    pairs.sort(reverse=True)

    used_gt: set[int] = set()
    used_pred: set[int] = set()
    matched_ious: list[float] = []
    for value, gi, pi in pairs:
        if value < threshold:
            break
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        matched_ious.append(value)

    tp = len(matched_ious)
    fp = len(pred) - tp
    fn = len(gt) - tp
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "mean_iou": round(sum(matched_ious) / len(matched_ious), 6) if matched_ious else None,
    }


def evaluate_case(
    gt_boxes: list[dict[str, Any]],
    pred_boxes: list[dict[str, Any]],
    label_ids: list[int],
    threshold: float,
) -> dict[str, Any]:
    per_label = {}
    total_tp = total_fp = total_fn = 0
    ious: list[float] = []
    for label_id in label_ids:
        result = match_boxes(gt_boxes, pred_boxes, label_id, threshold)
        per_label[str(label_id)] = result
        total_tp += result["tp"]
        total_fp += result["fp"]
        total_fn += result["fn"]
        if result["mean_iou"] is not None:
            ious.append(result["mean_iou"])
    return {
        "per_label": per_label,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "mean_iou": round(sum(ious) / len(ious), 6) if ious else None,
    }
