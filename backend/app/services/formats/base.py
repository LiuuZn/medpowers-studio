"""格式适配器的公共类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hierarchy import SeriesMetadata


@dataclass
class NormalizedAsset:
    """一次规范化产生的文件。"""

    path: Path
    case_uid: str
    data_kind: str
    canonical_format: str
    media_type: str
    geometry: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_manifest: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveredItem:
    """导入源中识别出的一个逻辑病例。"""

    case_uid: str
    files: list[Path]
    source_kind: str  # dicom_series / volume_file / image_file / dicom_image / table_file
    display_source: str
    data_kind: str
    patient_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    series_meta: SeriesMetadata = field(default_factory=SeriesMetadata)
    sheet_name: str | None = None
