from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .modalities import get_modality

DEFAULT_SEG_SCHEMA: dict[str, Any] = {
    "classes": [
        {"id": 0, "name": "背景", "color": "#000000"},
        {"id": 1, "name": "目标", "color": "#ff4d4f"},
    ]
}

DEFAULT_KEYFRAME_SCHEMA: dict[str, Any] = {
    "labels": [{"id": 1, "name": "关键帧", "color": "#1677ff"}]
}

DEFAULT_DET_SCHEMA: dict[str, Any] = {"labels": [{"id": 1, "name": "病灶", "color": "#fa8c16"}]}


@dataclass(frozen=True)
class TaskTypeSpec:
    code: str
    name: str
    dimension: str
    annotation_kind: str  # mask / keyframe / boxes
    description: str
    default_label_schema: dict[str, Any]


TASK_TYPES: dict[str, TaskTypeSpec] = {
    "seg3d": TaskTypeSpec(
        code="seg3d",
        name="三维图像分割",
        dimension="3d",
        annotation_kind="mask",
        description="在三维体数据上逐层勾画体素掩码",
        default_label_schema=DEFAULT_SEG_SCHEMA,
    ),
    "seg2d": TaskTypeSpec(
        code="seg2d",
        name="二维图像分割",
        dimension="2d",
        annotation_kind="mask",
        description="在二维影像上勾画像素掩码",
        default_label_schema=DEFAULT_SEG_SCHEMA,
    ),
    "keyframe3d": TaskTypeSpec(
        code="keyframe3d",
        name="三维关键帧选择",
        dimension="3d",
        annotation_kind="keyframe",
        description="在三维体数据中选取关键切片并赋予标签",
        default_label_schema=DEFAULT_KEYFRAME_SCHEMA,
    ),
    "det3d": TaskTypeSpec(
        code="det3d",
        name="三维图像检测",
        dimension="3d",
        annotation_kind="boxes",
        description="在三维体数据中标注三维包围框",
        default_label_schema=DEFAULT_DET_SCHEMA,
    ),
}


def get_task_type(code: str) -> TaskTypeSpec:
    try:
        return TASK_TYPES[code]
    except KeyError as exc:
        raise ValueError(f"不支持的任务类型：{code}") from exc


def public_task_types() -> list[dict]:
    return [
        {
            "code": t.code,
            "name": t.name,
            "dimension": t.dimension,
            "annotation_kind": t.annotation_kind,
            "description": t.description,
            "default_label_schema": t.default_label_schema,
        }
        for t in TASK_TYPES.values()
    ]


def assert_dimension_match(task_type: str, modality: str) -> None:
    task = get_task_type(task_type)
    modality_spec = get_modality(modality)
    if task.dimension != modality_spec.dimension:
        raise ValueError(
            f"维度不匹配：任务 {task.name} 需要 {task.dimension.upper()} 数据，"
            f"而模态 {modality_spec.name} 是 {modality_spec.dimension.upper()} 数据"
        )


def normalize_label_schema(task_type: str, schema: dict[str, Any] | None) -> dict[str, Any]:
    """校验并补全标签体系。返回规范化后的新字典。"""
    spec = get_task_type(task_type)
    if not schema:
        return {
            key: [dict(item) for item in value] for key, value in spec.default_label_schema.items()
        }

    if spec.annotation_kind == "mask":
        classes = schema.get("classes")
        if not isinstance(classes, list) or len(classes) < 2:
            raise ValueError("分割任务至少需要背景和一个前景类别")
        normalized = []
        seen_ids: set[int] = set()
        seen_names: set[str] = set()
        for index, item in enumerate(classes):
            if not isinstance(item, dict):
                raise ValueError("类别定义格式错误")
            try:
                class_id = int(item.get("id"))
            except (TypeError, ValueError) as exc:
                raise ValueError("类别 id 必须是整数") from exc
            if class_id < 0:
                raise ValueError("类别 id 不能为负数")
            if class_id in seen_ids:
                raise ValueError(f"类别 id 重复：{class_id}")
            if class_id != index:
                raise ValueError("分割类别 id 必须从 0 开始连续编号（0 为背景）")
            name = str(item.get("name", "")).strip()
            if not name:
                raise ValueError("类别名称不能为空")
            if name in seen_names:
                raise ValueError(f"类别名称重复：{name}")
            color = str(item.get("color") or "#888888")
            normalized.append({"id": class_id, "name": name, "color": color})
            seen_ids.add(class_id)
            seen_names.add(name)
        if 0 not in seen_ids:
            raise ValueError("分割类别必须包含 id=0 的背景类")
        return {"classes": normalized}

    labels = schema.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError("至少需要一个标签")
    normalized = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    for index, item in enumerate(labels):
        if not isinstance(item, dict):
            raise ValueError("标签定义格式错误")
        try:
            label_id = int(item.get("id", index + 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("标签 id 必须是整数") from exc
        if label_id <= 0:
            raise ValueError("标签 id 必须大于 0")
        if label_id in seen_ids:
            raise ValueError(f"标签 id 重复：{label_id}")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError("标签名称不能为空")
        if name in seen_names:
            raise ValueError(f"标签名称重复：{name}")
        color = str(item.get("color") or "#1677ff")
        normalized.append({"id": label_id, "name": name, "color": color})
        seen_ids.add(label_id)
        seen_names.add(name)
    return {"labels": normalized}


def label_ids(task_type: str, schema: dict[str, Any]) -> set[int]:
    spec = get_task_type(task_type)
    key = "classes" if spec.annotation_kind == "mask" else "labels"
    return {int(item["id"]) for item in schema.get(key, [])}


def validate_annotation_data(
    task_type: str, schema: dict[str, Any], data: dict[str, Any] | None
) -> dict[str, Any]:
    """校验关键帧/检测标注数据；分割任务的 data 只做浅校验。"""
    spec = get_task_type(task_type)
    data = data or {}
    valid_ids = label_ids(task_type, schema)

    if spec.annotation_kind == "keyframe":
        frames = data.get("frames", [])
        if not isinstance(frames, list):
            raise ValueError("frames 必须是数组")
        normalized = []
        seen: set[tuple[int, int]] = set()
        for frame in frames:
            if not isinstance(frame, dict):
                raise ValueError("关键帧格式错误")
            try:
                z_index = int(frame.get("z_index"))
                label_id = int(frame.get("label_id"))
            except (TypeError, ValueError) as exc:
                raise ValueError("关键帧的 z_index / label_id 必须是整数") from exc
            if z_index < 0:
                raise ValueError("关键帧 z_index 不能为负数")
            if label_id not in valid_ids:
                raise ValueError(f"未知标签 id：{label_id}")
            key = (label_id, z_index)
            if key in seen:
                continue
            seen.add(key)
            normalized.append({"label_id": label_id, "z_index": z_index})
        return {"frames": sorted(normalized, key=lambda x: (x["z_index"], x["label_id"]))}

    if spec.annotation_kind == "boxes":
        boxes = data.get("boxes", [])
        if not isinstance(boxes, list):
            raise ValueError("boxes 必须是数组")
        normalized = []
        for box in boxes:
            if not isinstance(box, dict):
                raise ValueError("包围框格式错误")
            try:
                label_id = int(box.get("label_id"))
                center = [float(v) for v in box.get("center_voxel", [])]
                size = [float(v) for v in box.get("size_voxel", [])]
            except (TypeError, ValueError) as exc:
                raise ValueError("包围框坐标格式错误") from exc
            if label_id not in valid_ids:
                raise ValueError(f"未知标签 id：{label_id}")
            if len(center) != 3 or len(size) != 3:
                raise ValueError("三维包围框需要 center_voxel / size_voxel 各 3 个数")
            if any(v < 0 for v in size):
                raise ValueError("包围框尺寸不能为负数")
            if size[0] == 0 or size[1] == 0 or size[2] == 0:
                raise ValueError("包围框尺寸不能为 0")
            item = {
                "label_id": label_id,
                "center_voxel": [round(v, 3) for v in center],
                "size_voxel": [round(v, 3) for v in size],
            }
            # 前端若已带世界坐标则保留，后端会在保存时统一重算
            if "center_world" in box:
                item["center_world"] = [round(float(v), 4) for v in box["center_world"]]
            if "size_world" in box:
                item["size_world"] = [round(float(v), 4) for v in box["size_world"]]
            normalized.append(item)
        return {"boxes": normalized}

    # mask 任务的数据仅作元信息容器
    return dict(data)
