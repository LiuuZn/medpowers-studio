from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from contextlib import suppress
from pathlib import Path

from ..config import get_settings
from ..models import Case


def settings_root() -> Path:
    root = Path(get_settings().storage_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_key(key: str | Path) -> Path:
    """把 storage key 解析为本地绝对路径。

    迁移期旧数据可能仍是绝对路径；此时原样返回，保证历史数据可读。
    """

    path = Path(key).expanduser()
    if path.is_absolute():
        return path
    return settings_root() / path


def key_for(path: str | Path) -> str:
    """把本地路径转为相对 storage_root 的 key。

    不在 storage_root 下的路径保持绝对形式（迁移脚本会负责搬迁）。
    """

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(settings_root()).as_posix()
    except ValueError:
        return str(candidate)


def case_image_path(case: Case) -> Path:
    return resolve_key(case.image_path)


def blob_key(sha256: str) -> str:
    digest = sha256.lower()
    return f"blobs/sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def blob_path(sha256: str) -> Path:
    return resolve_key(blob_key(sha256))


def dataset_key(dataset_id: str) -> str:
    return f"datasets/{dataset_id}"


def dataset_dir(dataset_id: str) -> Path:
    path = resolve_key(dataset_key(dataset_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def case_dir(dataset_id: str, case_id: str) -> Path:
    path = dataset_dir(dataset_id) / "cases" / case_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotation_dir(task_id: str, case_id: str) -> Path:
    path = settings_root() / "annotations" / task_id / case_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotation_current_dir(task_id: str, case_id: str) -> Path:
    path = annotation_dir(task_id, case_id) / "current"
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotation_working_dir(task_id: str, case_id: str) -> Path:
    path = annotation_dir(task_id, case_id) / "working"
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotation_revision_dir(task_id: str, case_id: str, version: int) -> Path:
    path = annotation_dir(task_id, case_id) / "revisions" / f"v{version:04d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_dir(export_id: str) -> Path:
    path = settings_root() / "exports" / export_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def evaluation_dir(evaluation_id: str) -> Path:
    path = settings_root() / "evaluations" / evaluation_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def tmp_dir(name: str) -> Path:
    path = settings_root() / "tmp" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_name(value: str, fallback: str = "case") -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._-")
    return cleaned[:120] or fallback


def unique_name(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def hash_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def copy_to_blob(source: Path, sha256: str | None = None) -> tuple[str, str, int]:
    """把文件复制到内容寻址 Blob；返回 (key, sha256, size)。

    单次读取完成「复制 + 哈希」，避免 5TB 级迁移重复读盘。
    已存在相同哈希且大小一致时删除临时文件并复用。
    """

    source = source.expanduser().resolve()
    target_dir = settings_root() / "tmp" / "blob_parts"
    target_dir.mkdir(parents=True, exist_ok=True)
    temp = target_dir / f"{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as src, temp.open("wb") as out:
            while True:
                chunk = src.read(8 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
        hexdigest = digest.hexdigest()
        if sha256 and sha256 != hexdigest:
            raise ValueError("文件哈希与预期不一致，可能已被修改")
        target = blob_path(hexdigest)
        if target.exists() and target.stat().st_size == size:
            return blob_key(hexdigest), hexdigest, size
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, target)
        return blob_key(hexdigest), hexdigest, size
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def disk_usage() -> dict[str, int]:
    usage = shutil.disk_usage(settings_root())
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def storage_usage() -> dict[str, int]:
    root = settings_root()
    usage = shutil.disk_usage(root)
    blob_root = root / "blobs"
    blob_count = 0
    blob_bytes = 0
    if blob_root.exists():
        for path in blob_root.rglob("*"):
            if path.is_file():
                blob_count += 1
                with suppress(OSError):
                    blob_bytes += path.stat().st_size
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "blob_count": blob_count,
        "blob_bytes": blob_bytes,
    }


def assert_free_space(required_bytes: int) -> None:
    free = shutil.disk_usage(settings_root()).free
    reserve = int(get_settings().storage_min_free_gb) * 1024 * 1024 * 1024
    if required_bytes + reserve > free:
        raise ValueError(
            "存储空间不足：本次导入约需 "
            f"{required_bytes / 1024**3:.1f} GB，当前仅剩 {free / 1024**3:.1f} GB"
            f"（保留 {get_settings().storage_min_free_gb} GB 安全余量）"
        )
