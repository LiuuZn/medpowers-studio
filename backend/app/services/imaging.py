from __future__ import annotations

import io
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import SimpleITK as sitk
from PIL import Image

from ..config import get_settings
from ..models import Case
from . import storage


@dataclass
class VolumeEntry:
    mtime: float
    array: np.ndarray
    geometry: dict[str, Any]
    default_window: float
    default_level: float


_CACHE: OrderedDict[str, VolumeEntry] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cache_size() -> int:
    return max(1, int(get_settings().slice_cache_volumes))


def _read_sitk(path: Path, image_format: str = "nrrd") -> sitk.Image:
    """Blob 文件名是纯 sha256、没有扩展名，需要显式指定 ImageIO。"""

    reader = sitk.ImageFileReader()
    if image_format == "nrrd":
        reader.SetImageIO("NrrdImageIO")
    reader.SetFileName(str(path))
    return reader.Execute()


def load_volume(path: str) -> VolumeEntry:
    resolved = str(Path(path).expanduser().resolve())
    stat = Path(resolved).stat()
    with _CACHE_LOCK:
        cached = _CACHE.get(resolved)
        if cached and cached.mtime == stat.st_mtime:
            _CACHE.move_to_end(resolved)
            return cached

    image = _read_sitk(Path(resolved))
    array = sitk.GetArrayFromImage(image)  # (z, y, x)
    window, level = default_window_level(array)
    geometry = {
        "size": list(image.GetSize()),  # ITK order: x, y, z
        "spacing": list(image.GetSpacing()),
        "origin": list(image.GetOrigin()),
        "direction": list(image.GetDirection()),
        "array_shape": list(array.shape),
    }
    entry = VolumeEntry(
        mtime=stat.st_mtime,
        array=array,
        geometry=geometry,
        default_window=window,
        default_level=level,
    )
    with _CACHE_LOCK:
        _CACHE[resolved] = entry
        _CACHE.move_to_end(resolved)
        while len(_CACHE) > _cache_size():
            _CACHE.popitem(last=False)
    return entry


def _sample_array(array: np.ndarray, max_samples: int = 500_000) -> np.ndarray:
    flat = np.asarray(array).ravel()
    if flat.size <= max_samples:
        return flat
    step = max(1, flat.size // max_samples)
    return flat[::step]


def default_window_level(array: np.ndarray) -> tuple[float, float]:
    sample = _sample_array(array)
    sample = sample[np.isfinite(sample)]
    if sample.size == 0:
        return 1.0, 0.0
    low, high = np.percentile(sample, [1.0, 99.0])
    if high <= low:
        high = low + 1.0
    return float(high - low), float((high + low) / 2.0)


def apply_window(array: np.ndarray, window: float | None, level: float | None) -> np.ndarray:
    arr = np.asarray(array, dtype=np.float32)
    if window is None or level is None:
        window, level = default_window_level(arr)
    window = max(float(window), 1e-6)
    low = float(level) - window / 2.0
    high = float(level) + window / 2.0
    arr = np.nan_to_num(arr, nan=low, posinf=high, neginf=low)
    scaled = (arr - low) / max(high - low, 1e-6)
    scaled = np.clip(scaled, 0.0, 1.0)
    return (scaled * 255.0).astype(np.uint8)


def png_bytes(array_uint8: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array_uint8).save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def read_2d_array(path: str) -> np.ndarray:
    with Image.open(path) as image:
        if image.mode not in ("L", "I", "I;16", "F"):
            image = image.convert("L")
        return np.asarray(image)


def case_dimension(case: Case) -> str:
    if case.data_kind == "table":
        return "tabular"
    if case.data_kind == "volume3d":
        return "3d"
    if case.data_kind == "image2d":
        return "2d"
    # 兼容未回填 data_kind 的旧数据
    return "3d" if case.image_format == "nrrd" else "2d"


def get_volume(case: Case) -> VolumeEntry:
    if case_dimension(case) != "3d":
        raise ValueError("该病例不是三维体数据")
    return load_volume(str(storage.case_image_path(case)))


def slice_info(case: Case) -> dict[str, Any]:
    dimension = case_dimension(case)
    if dimension == "tabular":
        raise ValueError("表格数据不支持切片预览")
    if dimension == "3d":
        entry = get_volume(case)
        size = entry.geometry["size"]
        return {
            "case_id": case.id,
            "case_uid": case.case_uid,
            "modality": case.dataset.modality,
            "dimension": "3d",
            "width": int(size[0]),
            "height": int(size[1]),
            "slices": int(size[2]),
            "spacing": [float(v) for v in entry.geometry["spacing"]],
            "origin": [float(v) for v in entry.geometry["origin"]],
            "direction": [float(v) for v in entry.geometry["direction"]],
            "default_window": entry.default_window,
            "default_level": entry.default_level,
            "axes": ["axial", "coronal", "sagittal"],
        }
    array = read_2d_array(str(storage.case_image_path(case)))
    window, level = default_window_level(array)
    height, width = array.shape[:2]
    return {
        "case_id": case.id,
        "case_uid": case.case_uid,
        "modality": case.dataset.modality,
        "dimension": "2d",
        "width": int(width),
        "height": int(height),
        "slices": 1,
        "spacing": None,
        "origin": None,
        "direction": None,
        "default_window": window,
        "default_level": level,
        "axes": ["axial"],
    }


def _extract_slice(case: Case, axis: str, index: int) -> np.ndarray:
    if case_dimension(case) == "tabular":
        raise ValueError("表格数据不支持切片预览")
    if case_dimension(case) == "3d":
        entry = get_volume(case)
        arr = entry.array
        z, y, x = arr.shape
        if axis == "axial":
            if not 0 <= index < z:
                raise ValueError("切片索引超出范围")
            return arr[index, :, :]
        if axis == "coronal":
            if not 0 <= index < y:
                raise ValueError("切片索引超出范围")
            return arr[:, index, :]
        if axis == "sagittal":
            if not 0 <= index < x:
                raise ValueError("切片索引超出范围")
            return arr[:, :, index]
        raise ValueError(f"不支持的切面：{axis}")
    if axis != "axial":
        raise ValueError("二维影像只支持轴位")
    return read_2d_array(str(storage.case_image_path(case)))


def slice_shape(case: Case, axis: str = "axial", index: int = 0) -> tuple[int, int]:
    arr = _extract_slice(case, axis, index)
    return int(arr.shape[0]), int(arr.shape[1])


def slice_png(
    case: Case,
    axis: str = "axial",
    index: int = 0,
    window: float | None = None,
    level: float | None = None,
) -> bytes:
    arr = _extract_slice(case, axis, index)
    return png_bytes(apply_window(arr, window, level))


def mask_slice_file(task_id: str, case_id: str, index: int) -> Path:
    return storage.annotation_working_dir(task_id, case_id) / f"z{index:04d}.png"


def read_mask_slice(task_id: str, case_id: str, index: int) -> bytes | None:
    path = mask_slice_file(task_id, case_id, index)
    if not path.exists():
        return None
    return path.read_bytes()


def validate_label_map(array: np.ndarray, class_count: int) -> np.ndarray:
    arr = np.asarray(array)
    if arr.ndim != 2:
        raise ValueError("掩码必须是二维图像")
    arr = arr.astype(np.uint8)
    max_label = int(arr.max()) if arr.size else 0
    if max_label >= class_count:
        raise ValueError(f"掩码包含未定义类别：{max_label}（已定义 0-{class_count - 1}）")
    return arr


def save_mask_slice(
    task_id: str,
    case_id: str,
    index: int,
    content: bytes,
    expected_shape: tuple[int, int],
    class_count: int,
) -> np.ndarray:
    with Image.open(io.BytesIO(content)) as image:
        if image.mode not in ("L", "I", "I;16"):
            image = image.convert("L")
        arr = np.asarray(image)
    arr = validate_label_map(arr, class_count)
    if arr.shape != expected_shape:
        raise ValueError(
            f"掩码尺寸 {arr.shape[1]}x{arr.shape[0]} 与影像切片 "
            f"{expected_shape[1]}x{expected_shape[0]} 不一致"
        )
    path = mask_slice_file(task_id, case_id, index)
    tmp = path.with_suffix(".tmp")
    Image.fromarray(arr).save(tmp, format="PNG")
    tmp.replace(path)
    return arr


def save_2d_mask(
    path: Path, content: bytes, expected_shape: tuple[int, int], class_count: int
) -> np.ndarray:
    with Image.open(io.BytesIO(content)) as image:
        if image.mode not in ("L", "I", "I;16"):
            image = image.convert("L")
        arr = np.asarray(image)
    arr = validate_label_map(arr, class_count)
    if arr.shape != expected_shape:
        raise ValueError(
            f"掩码尺寸 {arr.shape[1]}x{arr.shape[0]} 与影像 "
            f"{expected_shape[1]}x{expected_shape[0]} 不一致"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    Image.fromarray(arr).save(tmp, format="PNG")
    tmp.replace(path)
    return arr


def assemble_seg3d_mask(case: Case, task_id: str, out_path: Path) -> dict[str, Any]:
    entry = get_volume(case)
    z, y, x = entry.array.shape
    working = storage.annotation_working_dir(task_id, case.id)
    files = sorted(working.glob("z*.png"))
    if not files:
        raise ValueError("尚未保存任何切片掩码")

    mask = np.zeros((z, y, x), dtype=np.uint8)
    nonempty_slices = 0
    for path in files:
        try:
            index = int(path.stem[1:])
        except ValueError:
            continue
        if not 0 <= index < z:
            continue
        with Image.open(path) as image:
            arr = np.asarray(image.convert("L") if image.mode not in ("L", "I", "I;16") else image)
        arr = arr.astype(np.uint8)
        if arr.shape != (y, x):
            raise ValueError(f"切片 {index} 掩码尺寸与影像不一致：{arr.shape} vs {(y, x)}")
        if arr.any():
            nonempty_slices += 1
        mask[index, :, :] = arr

    if not mask.any():
        raise ValueError("掩码为空，无法提交")

    reference = _read_sitk(storage.case_image_path(case))
    mask_image = sitk.GetImageFromArray(mask)
    mask_image.CopyInformation(reference)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(mask_image, str(out_path), True)
    return {
        "slice_count": len(files),
        "nonempty_slices": nonempty_slices,
        "foreground_voxels": int(mask.astype(bool).sum()),
        "classes_present": sorted(int(v) for v in np.unique(mask) if v != 0),
    }


def voxel_box_to_world(
    center_voxel: list[float], size_voxel: list[float], geometry: dict[str, Any]
) -> tuple[list[float], list[float]]:
    """把 ITK 索引坐标（x,y,z）的轴对齐框转换为 RAS 世界坐标 AABB。"""
    direction = np.asarray(geometry.get("direction", [1, 0, 0, 0, 1, 0, 0, 0, 1]), dtype=float)
    direction = direction.reshape(3, 3)
    spacing = np.asarray(geometry.get("spacing", [1, 1, 1]), dtype=float)
    origin = np.asarray(geometry.get("origin", [0, 0, 0]), dtype=float)
    center = np.asarray(center_voxel, dtype=float)
    size = np.asarray(size_voxel, dtype=float)

    corners = []
    for sx in (-0.5, 0.5):
        for sy in (-0.5, 0.5):
            for sz in (-0.5, 0.5):
                idx = center + size * np.array([sx, sy, sz])
                world = origin + direction @ (spacing * idx)
                corners.append(world)
    corners_arr = np.stack(corners, axis=0)
    min_corner = corners_arr.min(axis=0)
    max_corner = corners_arr.max(axis=0)
    center_world = (min_corner + max_corner) / 2.0
    size_world = max_corner - min_corner
    return [round(float(v), 4) for v in center_world], [round(float(v), 4) for v in size_world]
