"""数据格式适配器注册表。"""

from __future__ import annotations

from .base import DiscoveredItem, NormalizedAsset
from .image import IMAGE_SUFFIXES, is_image_file
from .table import TABLE_SUFFIXES, is_table_file
from .volume import VOLUME_SUFFIXES, is_volume_file

__all__ = [
    "DiscoveredItem",
    "NormalizedAsset",
    "IMAGE_SUFFIXES",
    "TABLE_SUFFIXES",
    "VOLUME_SUFFIXES",
    "is_image_file",
    "is_table_file",
    "is_volume_file",
]
