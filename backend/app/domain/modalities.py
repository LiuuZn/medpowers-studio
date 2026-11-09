from __future__ import annotations

from dataclasses import dataclass

from .data_kinds import data_kind_for_dimension, get_data_kind


@dataclass(frozen=True)
class ModalitySpec:
    code: str
    name: str
    dimension: str  # 2d / 3d / tabular
    description: str
    data_kind: str = ""  # volume3d / image2d / table；为空时按 dimension 推导


# 新增模态只需在此登记，数据集维度与数据种类会自动推导。
MODALITIES: dict[str, ModalitySpec] = {
    "DR": ModalitySpec("DR", "2D DR", "2d", "二维数字 X 线摄影"),
    "CT": ModalitySpec("CT", "3D CT", "3d", "三维 CT 体数据"),
    "MR": ModalitySpec("MR", "3D MR", "3d", "三维 MR 体数据"),
    "TABLE": ModalitySpec("TABLE", "临床表格", "tabular", "不涉及医学影像的临床表格数据"),
}


def get_modality(code: str) -> ModalitySpec:
    try:
        spec = MODALITIES[code]
    except KeyError as exc:
        raise ValueError(f"不支持的模态：{code}") from exc
    if spec.data_kind:
        return spec
    return ModalitySpec(
        code=spec.code,
        name=spec.name,
        dimension=spec.dimension,
        description=spec.description,
        data_kind=data_kind_for_dimension(spec.dimension),
    )


def modality_dimension(code: str) -> str:
    return get_modality(code).dimension


def modality_data_kind(code: str) -> str:
    return get_modality(code).data_kind


def public_modalities() -> list[dict]:
    return [
        {
            "code": spec.code,
            "name": spec.name,
            "dimension": spec.dimension,
            "data_kind": spec.data_kind
            or get_data_kind(data_kind_for_dimension(spec.dimension)).code,
            "description": spec.description,
        }
        for spec in MODALITIES.values()
    ]
