from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.constants import (
    ANNOTATION_APPROVED,
    ANNOTATION_EDITABLE_STATUSES,
    ANNOTATION_IN_PROGRESS,
    ANNOTATION_REJECTED,
    ANNOTATION_REVIEW_REQUESTED,
    ANNOTATION_REVIEWABLE_STATUSES,
    ANNOTATION_SUBMITTED,
    REVIEW_REQUEST_APPROVED,
    REVIEW_REQUEST_CANCELLED,
    REVIEW_REQUEST_OPEN,
    REVIEW_REQUEST_REJECTED,
)
from ..domain.task_types import get_task_type, normalize_label_schema, validate_annotation_data
from ..models import (
    Annotation,
    AnnotationReviewRequest,
    AnnotationRevision,
    Case,
    Task,
    User,
)
from ..schemas import AnnotationOut, UserBrief
from . import imaging, storage


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _annotation_dir(task_id: str, case_id: str) -> Path:
    return storage.annotation_dir(task_id, case_id)


def ensure_annotation(db: Session, task: Task, case: Case, user: User) -> Annotation:
    annotation = db.scalar(
        select(Annotation).where(Annotation.task_id == task.id, Annotation.case_id == case.id)
    )
    if annotation:
        return annotation
    annotation = Annotation(
        task_id=task.id,
        case_id=case.id,
        status=ANNOTATION_IN_PROGRESS,
        data=default_data(task.task_type),
        annotator_id=user.id,
        version=0,
    )
    db.add(annotation)
    db.flush()
    return annotation


def default_data(task_type: str) -> dict[str, Any]:
    kind = get_task_type(task_type).annotation_kind
    if kind == "keyframe":
        return {"frames": []}
    if kind == "boxes":
        return {"boxes": []}
    return {}


def is_editable(annotation: Annotation) -> bool:
    return annotation.status in ANNOTATION_EDITABLE_STATUSES


def assert_editable(annotation: Annotation) -> None:
    if not is_editable(annotation):
        raise ValueError("当前标注已提交或已通过审核，不能直接修改；请先由管理员撤回")


def mask_available(annotation: Annotation) -> bool:
    if annotation.mask_path and storage.resolve_key(annotation.mask_path).exists():
        return True
    working = storage.annotation_working_dir(annotation.task_id, annotation.case_id)
    return any(working.glob("z*.png"))


def save_data(
    db: Session,
    task: Task,
    case: Case,
    user: User,
    data: dict[str, Any],
    note: str = "",
) -> Annotation:
    task_spec = get_task_type(task.task_type)
    if task_spec.annotation_kind == "mask":
        raise ValueError("分割任务请通过掩码接口保存")

    annotation = ensure_annotation(db, task, case, user)
    assert_editable(annotation)
    normalized = validate_annotation_data(task.task_type, task.label_schema, data)

    if task_spec.annotation_kind == "boxes":
        boxes = []
        for box in normalized.get("boxes", []):
            center_world, size_world = imaging.voxel_box_to_world(
                box["center_voxel"], box["size_voxel"], case.geometry
            )
            item = dict(box)
            item["center_world"] = center_world
            item["size_world"] = size_world
            boxes.append(item)
        normalized = {"boxes": boxes}

    annotation.data = normalized
    annotation.status = ANNOTATION_IN_PROGRESS
    annotation.annotator_id = user.id
    current = storage.annotation_current_dir(task.id, case.id)
    data_path = current / "data.json"
    _write_json(data_path, normalized)
    annotation.data_path = storage.key_for(data_path)
    db.commit()
    db.refresh(annotation)
    return annotation


def _mask_class_count(task: Task) -> int:
    return len(task.label_schema.get("classes", []))


def _ensure_working_dir_data(task: Task, case: Case, annotation: Annotation) -> dict[str, Any]:
    working = storage.annotation_working_dir(task.id, case.id)
    files = sorted(working.glob("z*.png"))
    data = {
        "slice_count": len(files),
        "edited_slices": [int(p.stem[1:]) for p in files if p.stem[1:].isdigit()],
    }
    annotation.data = data
    current = storage.annotation_current_dir(task.id, case.id)
    data_path = current / "data.json"
    _write_json(data_path, data)
    annotation.data_path = storage.key_for(data_path)
    return data


def save_mask_slice(
    db: Session,
    task: Task,
    case: Case,
    user: User,
    axis: str,
    index: int,
    content: bytes,
) -> Annotation:
    if task.task_type != "seg3d":
        raise ValueError("只有三维分割任务支持逐层保存掩码")
    if axis != "axial":
        raise ValueError("首版仅支持轴位逐层勾画")
    if case.image_format != "nrrd":
        raise ValueError("该病例不是三维体数据")

    annotation = ensure_annotation(db, task, case, user)
    assert_editable(annotation)
    height, width = imaging.slice_shape(case, "axial", index)
    imaging.save_mask_slice(
        task.id, case.id, index, content, (height, width), _mask_class_count(task)
    )
    annotation.status = ANNOTATION_IN_PROGRESS
    annotation.annotator_id = user.id
    _ensure_working_dir_data(task, case, annotation)
    annotation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(annotation)
    return annotation


def save_mask_2d(db: Session, task: Task, case: Case, user: User, content: bytes) -> Annotation:
    if task.task_type != "seg2d":
        raise ValueError("只有二维分割任务支持整图掩码")
    annotation = ensure_annotation(db, task, case, user)
    assert_editable(annotation)
    height, width = imaging.slice_shape(case, "axial", 0)
    current = storage.annotation_current_dir(task.id, case.id)
    mask_path = current / "mask.png"
    imaging.save_2d_mask(mask_path, content, (height, width), _mask_class_count(task))

    import numpy as np
    from PIL import Image

    with Image.open(mask_path) as image:
        arr = np.asarray(image.convert("L"))
    data = {
        "width": int(width),
        "height": int(height),
        "foreground_pixels": int((arr != 0).sum()),
        "classes_present": sorted(int(v) for v in np.unique(arr) if v != 0),
    }
    annotation.data = data
    annotation.data_path = storage.key_for(current / "data.json")
    _write_json(storage.resolve_key(annotation.data_path), data)
    annotation.mask_path = storage.key_for(mask_path)
    annotation.status = ANNOTATION_IN_PROGRESS
    annotation.annotator_id = user.id
    db.commit()
    db.refresh(annotation)
    return annotation


def submit(db: Session, task: Task, case: Case, annotation: Annotation, user: User) -> Annotation:
    assert_editable(annotation)
    kind = get_task_type(task.task_type).annotation_kind
    current = storage.annotation_current_dir(task.id, case.id)

    if kind == "mask":
        if task.task_type == "seg3d":
            mask_path = current / "mask.nrrd"
            stats = imaging.assemble_seg3d_mask(case, task.id, mask_path)
            data = dict(annotation.data)
            data.update(stats)
            annotation.data = data
            _write_json(current / "data.json", data)
            annotation.data_path = storage.key_for(current / "data.json")
            annotation.mask_path = storage.key_for(mask_path)
        else:
            mask_path = current / "mask.png"
            if not mask_path.exists():
                raise ValueError("尚未保存任何掩码")
            import numpy as np
            from PIL import Image

            with Image.open(mask_path) as image:
                arr = np.asarray(image.convert("L"))
            if not arr.any():
                raise ValueError("掩码为空，无法提交")
            annotation.mask_path = storage.key_for(mask_path)
            annotation.data_path = storage.key_for(current / "data.json")
    else:
        data = annotation.data or {}
        key = "frames" if kind == "keyframe" else "boxes"
        if not data.get(key):
            raise ValueError("标注内容为空，无法提交")
        _write_json(current / "data.json", data)
        annotation.data_path = storage.key_for(current / "data.json")

    if annotation.data_path is None:
        raise ValueError("标注数据尚未保存")

    annotation.version += 1
    revision = storage.annotation_revision_dir(task.id, case.id, annotation.version)
    shutil.copy2(storage.resolve_key(annotation.data_path), revision / "data.json")
    mask_key = None
    if annotation.mask_path and storage.resolve_key(annotation.mask_path).exists():
        mask_name = Path(annotation.mask_path).name
        shutil.copy2(storage.resolve_key(annotation.mask_path), revision / mask_name)
        mask_key = storage.key_for(revision / mask_name)

    db.add(
        AnnotationRevision(
            annotation_id=annotation.id,
            version=annotation.version,
            data=annotation.data,
            data_path=storage.key_for(revision / "data.json"),
            mask_path=mask_key,
            created_by_id=user.id,
            note="提交",
        )
    )
    annotation.status = ANNOTATION_SUBMITTED
    annotation.submitted_at = datetime.now(UTC)
    annotation.reviewer_id = None
    annotation.reviewed_at = None
    annotation.review_comment = ""
    db.commit()
    db.refresh(annotation)
    return annotation


def review(
    db: Session,
    annotation: Annotation,
    reviewer: User,
    decision: str,
    comment: str,
) -> Annotation:
    if annotation.status not in ANNOTATION_REVIEWABLE_STATUSES:
        raise ValueError("只有已提交或待复核的标注可以审核")
    if decision not in (ANNOTATION_APPROVED, ANNOTATION_REJECTED):
        raise ValueError("审核结论必须是 approved 或 rejected")

    was_review_requested = annotation.status == ANNOTATION_REVIEW_REQUESTED
    # 待复核标注被驳回时回到标注员工作区（in_progress），而不是普通驳回状态。
    annotation.status = (
        ANNOTATION_IN_PROGRESS
        if was_review_requested and decision == ANNOTATION_REJECTED
        else decision
    )
    annotation.reviewer_id = reviewer.id
    annotation.reviewed_at = datetime.now(UTC)
    annotation.review_comment = comment

    if was_review_requested:
        open_requests = db.scalars(
            select(AnnotationReviewRequest).where(
                AnnotationReviewRequest.annotation_id == annotation.id,
                AnnotationReviewRequest.status == REVIEW_REQUEST_OPEN,
            )
        ).all()
        for request in open_requests:
            request.status = (
                REVIEW_REQUEST_APPROVED
                if decision == ANNOTATION_APPROVED
                else REVIEW_REQUEST_REJECTED
            )
            request.resolved_at = datetime.now(UTC)
            request.resolver_id = reviewer.id
            request.resolution_note = comment

    db.commit()
    db.refresh(annotation)
    return annotation


def request_review(
    db: Session,
    annotation: Annotation,
    user: User,
    *,
    reason: str,
    evidence: dict[str, Any] | None = None,
    eval_id: str | None = None,
    token_id: str | None = None,
    repo_key: str = "",
) -> tuple[Annotation, AnnotationReviewRequest]:
    """把 approved 标注转为 review_requested；不改内容/掩码/版本/revision。

    这是训练仓库/插件唯一允许写标注状态的入口。
    """
    if annotation.status != ANNOTATION_APPROVED:
        raise ValueError("只有已通过审核的标注可以申请复核")
    reason = reason.strip()
    if not reason:
        raise ValueError("复核申请必须填写原因")

    annotation.status = ANNOTATION_REVIEW_REQUESTED
    annotation.reviewer_id = None
    annotation.reviewed_at = None
    annotation.review_comment = f"复核申请：{reason}"
    request = AnnotationReviewRequest(
        annotation_id=annotation.id,
        user_id=user.id,
        token_id=token_id,
        repo_key=repo_key,
        reason=reason,
        evidence=evidence or {},
        eval_id=eval_id,
        status=REVIEW_REQUEST_OPEN,
    )
    db.add(request)
    db.commit()
    db.refresh(annotation)
    db.refresh(request)
    return annotation, request


def reopen(db: Session, annotation: Annotation, user: User) -> Annotation:
    if annotation.status == ANNOTATION_IN_PROGRESS:
        return annotation
    if annotation.status == ANNOTATION_REVIEW_REQUESTED:
        open_requests = db.scalars(
            select(AnnotationReviewRequest).where(
                AnnotationReviewRequest.annotation_id == annotation.id,
                AnnotationReviewRequest.status == REVIEW_REQUEST_OPEN,
            )
        ).all()
        for request in open_requests:
            request.status = REVIEW_REQUEST_CANCELLED
            request.resolved_at = datetime.now(UTC)
            request.resolver_id = user.id
            request.resolution_note = "管理员撤回"
    annotation.status = ANNOTATION_IN_PROGRESS
    annotation.reviewer_id = None
    annotation.reviewed_at = None
    annotation.review_comment = ""
    annotation.annotator_id = user.id
    db.commit()
    db.refresh(annotation)
    return annotation


def annotation_out(annotation: Annotation | None, task: Task, case: Case) -> AnnotationOut:
    if annotation is None:
        return AnnotationOut(
            id=None,
            task_id=task.id,
            case_id=case.id,
            status="pending",
            data=default_data(task.task_type),
            version=0,
            mask_available=False,
        )
    return AnnotationOut(
        id=annotation.id,
        task_id=annotation.task_id,
        case_id=annotation.case_id,
        status=annotation.status,
        data=annotation.data or {},
        version=annotation.version,
        mask_available=mask_available(annotation),
        annotator=_user_brief(annotation.annotator),
        reviewer=_user_brief(annotation.reviewer),
        submitted_at=annotation.submitted_at,
        reviewed_at=annotation.reviewed_at,
        review_comment=annotation.review_comment,
        updated_at=annotation.updated_at,
    )


def _user_brief(user: User | None) -> UserBrief | None:
    if not user:
        return None
    return UserBrief(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )


def read_current_data(task: Task, case: Case, annotation: Annotation | None) -> dict[str, Any]:
    if annotation and annotation.data_path:
        path = storage.resolve_key(annotation.data_path)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    return annotation.data if annotation else default_data(task.task_type)


def normalized_schema(task: Task) -> dict[str, Any]:
    return normalize_label_schema(task.task_type, task.label_schema)
