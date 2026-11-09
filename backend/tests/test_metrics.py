from __future__ import annotations

import numpy as np

from app.metrics.detection import box_iou
from app.metrics.detection import evaluate_case as evaluate_boxes
from app.metrics.keyframe import evaluate_case as evaluate_frames
from app.metrics.segmentation import dice, hd95, iou, segmentation_metrics


def test_segmentation_metrics() -> None:
    gt = np.zeros((8, 8), dtype=np.uint8)
    gt[2:6, 2:6] = 1
    pred = gt.copy()
    assert dice(gt, pred) == 1.0
    assert iou(gt, pred) == 1.0
    assert hd95(gt, pred) == 0.0

    pred[2:6, 2:4] = 0
    assert 0.0 < dice(gt, pred) < 1.0
    metrics = segmentation_metrics(gt, pred)
    assert round(metrics["dice"], 4) == 0.6667
    assert metrics["recall"] == 0.5

    empty = np.zeros_like(gt)
    assert dice(empty, empty) == 1.0
    assert hd95(empty, pred) is None
    assert hd95(empty, empty) == 0.0


def test_detection_metrics() -> None:
    gt = [
        {"label_id": 1, "center_world": [0, 0, 0], "size_world": [10, 10, 10]},
        {"label_id": 1, "center_world": [30, 0, 0], "size_world": [10, 10, 10]},
    ]
    pred = [
        {"label_id": 1, "center_world": [0, 0, 0], "size_world": [10, 10, 10]},
        {"label_id": 1, "center_world": [100, 0, 0], "size_world": [10, 10, 10]},
    ]
    assert box_iou(gt[0], pred[0]) == 1.0
    assert box_iou(gt[0], pred[1]) == 0.0
    result = evaluate_boxes(gt, pred, [1], threshold=0.5)
    assert result["tp"] == 1
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert result["mean_iou"] == 1.0


def test_keyframe_metrics() -> None:
    gt = [{"label_id": 1, "z_index": 10}]
    pred = [{"label_id": 1, "z_index": 11}]
    result = evaluate_frames(gt, pred, [1], tolerance=1)
    assert result["tp"] == 1
    assert result["mean_abs_error"] == 1.0
    result = evaluate_frames(gt, pred, [1], tolerance=0)
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 1
