from __future__ import annotations

from typing import Any

import numpy as np
from scipy import ndimage


def _binary(mask: np.ndarray) -> np.ndarray:
    return np.asarray(mask) > 0


def dice(gt: np.ndarray, pred: np.ndarray) -> float:
    gt_b = _binary(gt)
    pred_b = _binary(pred)
    gt_sum = int(gt_b.sum())
    pred_sum = int(pred_b.sum())
    if gt_sum + pred_sum == 0:
        return 1.0
    intersection = int(np.logical_and(gt_b, pred_b).sum())
    return float(2.0 * intersection / (gt_sum + pred_sum))


def iou(gt: np.ndarray, pred: np.ndarray) -> float:
    gt_b = _binary(gt)
    pred_b = _binary(pred)
    union = int(np.logical_or(gt_b, pred_b).sum())
    if union == 0:
        return 1.0
    intersection = int(np.logical_and(gt_b, pred_b).sum())
    return float(intersection / union)


def precision_recall(gt: np.ndarray, pred: np.ndarray) -> tuple[float, float]:
    gt_b = _binary(gt)
    pred_b = _binary(pred)
    tp = int(np.logical_and(gt_b, pred_b).sum())
    fp = int(np.logical_and(~gt_b, pred_b).sum())
    fn = int(np.logical_and(gt_b, ~pred_b).sum())
    precision = 1.0 if tp + fp == 0 else tp / (tp + fp)
    recall = 1.0 if tp + fn == 0 else tp / (tp + fn)
    return float(precision), float(recall)


def _surface(mask: np.ndarray) -> np.ndarray:
    structure = ndimage.generate_binary_structure(mask.ndim, 1)
    eroded = ndimage.binary_erosion(mask, structure=structure, border_value=0)
    return np.logical_and(mask, ~eroded)


def hd95(gt: np.ndarray, pred: np.ndarray, spacing: list[float] | None = None) -> float | None:
    """95% Hausdorff distance（mm）。任一掩码为空时返回 None；两者都空返回 0。"""
    gt_b = _binary(gt)
    pred_b = _binary(pred)
    if not gt_b.any() and not pred_b.any():
        return 0.0
    if not gt_b.any() or not pred_b.any():
        return None
    sampling = tuple(float(v) for v in spacing) if spacing else None
    surface_gt = _surface(gt_b)
    surface_pred = _surface(pred_b)
    dt_pred = ndimage.distance_transform_edt(~surface_pred, sampling=sampling)
    dt_gt = ndimage.distance_transform_edt(~surface_gt, sampling=sampling)
    distances = np.concatenate([dt_pred[surface_gt], dt_gt[surface_pred]])
    if distances.size == 0:
        return 0.0
    return float(np.percentile(distances, 95))


def segmentation_metrics(
    gt: np.ndarray, pred: np.ndarray, spacing: list[float] | None = None
) -> dict[str, Any]:
    precision, recall = precision_recall(gt, pred)
    hd = hd95(gt, pred, spacing)
    return {
        "dice": round(dice(gt, pred), 6),
        "iou": round(iou(gt, pred), 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "hd95": None if hd is None else round(hd, 4),
    }
