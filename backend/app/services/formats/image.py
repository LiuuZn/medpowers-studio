"""二维影像规范化：单帧 DICOM / PNG / JPG / BMP / TIFF -> PNG。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from PIL import Image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_dicom_2d(ds: pydicom.Dataset) -> np.ndarray:
    arr = ds.pixel_array
    if arr.ndim == 3:
        frames = _safe_int(getattr(ds, "NumberOfFrames", None)) or 1
        if frames > 1:
            raise ValueError("二维任务不支持多帧 DICOM，请按单帧拆分")
        arr = arr[..., :3].mean(axis=-1) if arr.shape[-1] in (3, 4) else arr[0]
    if arr.ndim != 2:
        raise ValueError(f"无法解析二维 DICOM 像素阵列：shape={arr.shape}")

    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    arr = arr.astype(np.float32) * slope + intercept
    low = float(arr.min())
    high = float(arr.max())
    if high <= low:
        high = low + 1.0
    return np.clip((arr - low) / (high - low) * 65535.0, 0, 65535).astype(np.uint16)


def save_2d_array(arr: np.ndarray, out: Path) -> None:
    if arr.dtype == np.uint8:
        image = Image.fromarray(arr, mode="L")
    else:
        if arr.dtype != np.uint16:
            arr = np.clip(arr, 0, 65535).astype(np.uint16)
        image = Image.fromarray(arr)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")


def normalize_image(
    path: Path, source_kind: str, out_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_format = "dicom" if source_kind == "dicom_image" else path.suffix.lower()
    metadata: dict[str, Any] = {"source_format": source_format}
    if source_kind == "dicom_image":
        ds = pydicom.dcmread(str(path))
        arr = normalize_dicom_2d(ds)
        save_2d_array(arr, out_path)
        metadata["dtype"] = str(arr.dtype)
    else:
        with Image.open(path) as image:
            if image.mode not in ("L", "I", "I;16", "F"):
                image = image.convert("L")
            image.save(out_path, format="PNG")
        with Image.open(out_path) as saved:
            arr = np.asarray(saved)
        metadata["dtype"] = str(arr.dtype)

    height, width = int(arr.shape[0]), int(arr.shape[1])
    geometry = {"width": width, "height": height}
    metadata["shape"] = [height, width]
    return geometry, metadata
