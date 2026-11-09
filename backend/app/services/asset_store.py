"""统一 Blob 存取接口。

首期实现为本地内容寻址文件存储；后续接入 S3/MinIO 时只需替换本模块，
业务层继续使用 storage key。
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import storage


@dataclass(frozen=True)
class BlobRef:
    storage_key: str
    sha256: str
    size_bytes: int
    media_type: str


def put_file(path: str | Path, media_type: str = "application/octet-stream") -> BlobRef:
    key, digest, size = storage.copy_to_blob(Path(path))
    return BlobRef(storage_key=key, sha256=digest, size_bytes=size, media_type=media_type)


def put_bytes(content: bytes, media_type: str = "application/octet-stream") -> BlobRef:
    temp = storage.tmp_dir("blob_upload") / f"{uuid.uuid4().hex}.bin"
    temp.write_bytes(content)
    try:
        return put_file(temp, media_type)
    finally:
        temp.unlink(missing_ok=True)


def local_path(blob_or_key: object) -> Path:
    if isinstance(blob_or_key, BlobRef):
        return storage.resolve_key(blob_or_key.storage_key)
    if isinstance(blob_or_key, Path):
        return blob_or_key
    if hasattr(blob_or_key, "storage_key"):
        return storage.resolve_key(str(blob_or_key.storage_key))
    return storage.resolve_key(str(blob_or_key))


def open_stream(blob_or_key: object) -> BinaryIO:
    return local_path(blob_or_key).open("rb")


def copy_out(blob_or_key: object, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_path(blob_or_key), destination)
    return destination


def usage() -> dict[str, int]:
    return storage.storage_usage()
