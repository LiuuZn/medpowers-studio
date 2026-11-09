"""数据种类注册表。

平台把「影像/表格」抽象为数据种类（data kind），每种数据种类只保留一种
规范化格式。导入适配器、任务维度校验和前端查看器都以这里为唯一来源。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataKindSpec:
    code: str
    name: str
    dimension: str  # 3d / 2d / tabular
    canonical_format: str  # nrrd / png / parquet
    viewer: str  # slice / image / table
    description: str


DATA_KINDS: dict[str, DataKindSpec] = {
    "volume3d": DataKindSpec(
        code="volume3d",
        name="三维体数据",
        dimension="3d",
        canonical_format="nrrd",
        viewer="slice",
        description="CT/MR 等三维体数据，统一保存为压缩 NRRD",
    ),
    "image2d": DataKindSpec(
        code="image2d",
        name="二维影像",
        dimension="2d",
        canonical_format="png",
        viewer="image",
        description="DR、单帧 DICOM、PNG/JPG 等二维影像，统一保存为 PNG",
    ),
    "table": DataKindSpec(
        code="table",
        name="临床表格",
        dimension="tabular",
        canonical_format="parquet",
        viewer="table",
        description="CSV/XLSX/Parquet 等临床表格，统一保存为 Parquet",
    ),
}

DIMENSION_TO_DATA_KIND: dict[str, str] = {spec.dimension: spec.code for spec in DATA_KINDS.values()}


def get_data_kind(code: str) -> DataKindSpec:
    try:
        return DATA_KINDS[code]
    except KeyError as exc:
        raise ValueError(f"不支持的数据种类：{code}") from exc


def data_kind_for_dimension(dimension: str) -> str:
    try:
        return DIMENSION_TO_DATA_KIND[dimension]
    except KeyError as exc:
        raise ValueError(f"不支持的维度：{dimension}") from exc


def public_data_kinds() -> list[dict[str, str]]:
    return [
        {
            "code": spec.code,
            "name": spec.name,
            "dimension": spec.dimension,
            "canonical_format": spec.canonical_format,
            "viewer": spec.viewer,
            "description": spec.description,
        }
        for spec in DATA_KINDS.values()
    ]
