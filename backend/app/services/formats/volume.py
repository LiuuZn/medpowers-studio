"""三维体数据规范化：DICOM Series / NRRD / NIfTI -> 压缩 NRRD。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import SimpleITK as sitk

VOLUME_SUFFIXES = {".nrrd", ".nii", ".nii.gz"}


def is_volume_file(path: Path) -> bool:
    return path.suffix.lower() in VOLUME_SUFFIXES or path.name.lower().endswith(".nii.gz")


def read_dicom_series(
    files: list[Path], instance_numbers: dict[Path, int] | None = None
) -> sitk.Image:
    reader = sitk.ImageSeriesReader()
    numbers = instance_numbers or {}
    ordered = sorted(files, key=lambda p: (numbers.get(p, 0), p.name))
    reader.SetFileNames([str(p) for p in ordered])
    image = reader.Execute()
    if image.GetDimension() != 3:
        raise ValueError(f"DICOM 序列维度为 {image.GetDimension()}D，三维任务需要 3D 体数据")
    return image


def read_volume(
    files: list[Path], source_kind: str, instance_numbers: dict[Path, int] | None = None
) -> sitk.Image:
    if source_kind == "dicom_series":
        return read_dicom_series(files, instance_numbers)
    image = sitk.ReadImage(str(files[0]))
    if image.GetDimension() != 3:
        raise ValueError(f"影像维度为 {image.GetDimension()}D，三维任务需要 3D 体数据")
    return image


def geometry_from_image(image: sitk.Image) -> dict[str, Any]:
    spacing = [float(v) if v > 0 else 1.0 for v in image.GetSpacing()]
    return {
        "size": [int(v) for v in image.GetSize()],  # x, y, z
        "spacing": spacing,
        "origin": [float(v) for v in image.GetOrigin()],
        "direction": [float(v) for v in image.GetDirection()],
        "array_shape": [
            int(image.GetSize()[2]),
            int(image.GetSize()[1]),
            int(image.GetSize()[0]),
        ],
    }


def normalize_volume(
    files: list[Path],
    source_kind: str,
    out_path: Path,
    instance_numbers: dict[Path, int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    image = read_volume(files, source_kind, instance_numbers)
    geometry = geometry_from_image(image)
    metadata = {
        "shape": geometry["array_shape"],
        "spacing": geometry["spacing"],
        "source_format": "dicom" if source_kind == "dicom_series" else files[0].suffix.lower(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path), True)
    return geometry, metadata
