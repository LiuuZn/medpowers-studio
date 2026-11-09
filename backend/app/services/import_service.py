from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pydicom
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.modalities import ModalitySpec, get_modality
from ..models import Blob, Case, CaseAsset, Dataset, new_id
from ..schemas import ImportIssue, ImportReport
from . import asset_store, hierarchy, storage
from .formats import image as image_formats
from .formats import table as table_formats
from .formats import volume as volume_formats
from .hierarchy import SeriesMetadata


@dataclass
class DiscoveredCase:
    case_uid: str
    files: list[Path]
    kind: str  # dicom_series / volume_file / image_file / dicom_image / table_file
    display_source: str
    data_kind: str
    patient_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    series_meta: SeriesMetadata = field(default_factory=SeriesMetadata)
    sheet_name: str | None = None


def _is_dicom(path: Path) -> bool:
    try:
        return pydicom.misc.is_dicom(str(path))
    except Exception:
        return False


def _read_header(path: Path) -> dict[str, Any]:
    ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    return {
        "patient_id": str(getattr(ds, "PatientID", "") or ""),
        "modality": str(getattr(ds, "Modality", "") or ""),
        "study_uid": str(getattr(ds, "StudyInstanceUID", "") or ""),
        "series_uid": str(getattr(ds, "SeriesInstanceUID", "") or ""),
        "sop_uid": str(getattr(ds, "SOPInstanceUID", "") or ""),
        "study_description": str(getattr(ds, "StudyDescription", "") or ""),
        "study_date": str(getattr(ds, "StudyDate", "") or ""),
        "accession_number": str(getattr(ds, "AccessionNumber", "") or ""),
        "patient_sex": str(getattr(ds, "PatientSex", "") or ""),
        "patient_age": str(getattr(ds, "PatientAge", "") or ""),
        "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
        "body_part": str(getattr(ds, "BodyPartExamined", "") or ""),
        "series_number": _safe_int(getattr(ds, "SeriesNumber", None)),
        "instance_number": _safe_int(getattr(ds, "InstanceNumber", None)),
        "rows": _safe_int(getattr(ds, "Rows", None)),
        "columns": _safe_int(getattr(ds, "Columns", None)),
        "number_of_frames": _safe_int(getattr(ds, "NumberOfFrames", None)),
        "photometric": str(getattr(ds, "PhotometricInterpretation", "") or ""),
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _patient_key(patient_id: str) -> str | None:
    return hierarchy.patient_key_for_id(patient_id)


def _iter_files(root: Path, recursive: bool) -> list[Path]:
    if not root.is_dir():
        return [root]
    iterator = root.rglob("*") if recursive else root.iterdir()
    result = []
    for path in iterator:
        if not path.is_file():
            continue
        if path.name.startswith(".") or "__MACOSX" in path.parts:
            continue
        result.append(path)
    return sorted(result)


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _volume_case(path: Path, root: Path) -> DiscoveredCase:
    """读取 NRRD/NIfTI 头中的 DICOM 元数据；失败时退化为匿名序列。"""

    try:
        series_meta = hierarchy.read_volume_metadata(path)
    except Exception:  # noqa: BLE001 - 头信息异常不应阻止影像导入
        series_meta = SeriesMetadata()
    return DiscoveredCase(
        case_uid=path.stem,
        files=[path],
        kind="volume_file",
        display_source=_display(path, root),
        data_kind="volume3d",
        patient_key=hierarchy.patient_key_for_id(series_meta.patient_id),
        series_meta=series_meta,
    )


def _group_dicom_series(
    files: list[Path], root: Path
) -> tuple[list[DiscoveredCase], list[ImportIssue]]:
    groups: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    issues: list[ImportIssue] = []
    for path in files:
        try:
            header = _read_header(path)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                ImportIssue(source=_display(path, root), message=f"DICOM 头读取失败：{exc}")
            )
            continue
        key = header["series_uid"] or f"{path.parent.name}::{path.parent}"
        groups.setdefault(key, []).append((path, header))

    result: list[DiscoveredCase] = []
    for key, items in groups.items():
        items.sort(key=lambda item: (item[1].get("instance_number") or 0, item[0].name))
        first = items[0][1]
        display = _display(items[0][0].parent, root) or items[0][0].parent.name
        result.append(
            DiscoveredCase(
                case_uid=first["series_uid"] or key,
                files=[path for path, _ in items],
                kind="dicom_series",
                display_source=display,
                data_kind="volume3d",
                patient_key=_patient_key(first["patient_id"]),
                metadata=first,
                series_meta=SeriesMetadata.from_mapping(first),
            )
        )
    return result, issues


def discover_cases(
    source: Path, spec: ModalitySpec, recursive: bool = True
) -> tuple[list[DiscoveredCase], list[ImportIssue]]:
    source = source.expanduser().resolve()
    if not source.exists():
        raise ValueError(f"路径不存在：{source}")
    data_kind = spec.data_kind

    if source.is_file():
        return _discover_file(source, source, spec)

    files = _iter_files(source, recursive)
    discovered: list[DiscoveredCase] = []
    issues: list[ImportIssue] = []

    if data_kind == "volume3d":
        volume_files = [p for p in files if volume_formats.is_volume_file(p)]
        dicom_files = [p for p in files if p not in volume_files and _is_dicom(p)]
        discovered.extend(_volume_case(path, source) for path in volume_files)
        series, series_issues = (
            _group_dicom_series(dicom_files, source) if dicom_files else ([], [])
        )
        discovered.extend(series)
        issues.extend(series_issues)
    elif data_kind == "image2d":
        for path in files:
            if image_formats.is_image_file(path):
                discovered.append(
                    DiscoveredCase(
                        case_uid=path.stem,
                        files=[path],
                        kind="image_file",
                        display_source=_display(path, source),
                        data_kind="image2d",
                    )
                )
            elif _is_dicom(path):
                header = _read_header(path)
                discovered.append(
                    DiscoveredCase(
                        case_uid=header["sop_uid"] or path.stem,
                        files=[path],
                        kind="dicom_image",
                        display_source=_display(path, source),
                        data_kind="image2d",
                        patient_key=_patient_key(header["patient_id"]),
                        metadata=header,
                        series_meta=SeriesMetadata.from_mapping(header),
                    )
                )
    else:
        for path in files:
            if table_formats.is_table_file(path):
                discovered.append(
                    DiscoveredCase(
                        case_uid=path.stem,
                        files=[path],
                        kind="table_file",
                        display_source=_display(path, source),
                        data_kind="table",
                    )
                )

    if not discovered:
        issues.append(ImportIssue(source=str(source), message="未发现可导入的数据文件"))
    return discovered, issues


def _discover_file(
    path: Path, root: Path, spec: ModalitySpec
) -> tuple[list[DiscoveredCase], list[ImportIssue]]:
    if spec.data_kind == "volume3d":
        if volume_formats.is_volume_file(path):
            return [_volume_case(path, root)], []
        if _is_dicom(path):
            header = _read_header(path)
            return [
                DiscoveredCase(
                    case_uid=header["series_uid"] or header["sop_uid"] or path.stem,
                    files=[path],
                    kind="dicom_series",
                    display_source=_display(path, root),
                    data_kind="volume3d",
                    patient_key=_patient_key(header["patient_id"]),
                    metadata=header,
                    series_meta=SeriesMetadata.from_mapping(header),
                )
            ], []
        return [], [ImportIssue(source=str(path), message="不支持的三维影像格式")]

    if spec.data_kind == "image2d":
        if image_formats.is_image_file(path):
            return [
                DiscoveredCase(
                    case_uid=path.stem,
                    files=[path],
                    kind="image_file",
                    display_source=_display(path, root),
                    data_kind="image2d",
                )
            ], []
        if _is_dicom(path):
            header = _read_header(path)
            return [
                DiscoveredCase(
                    case_uid=header["sop_uid"] or path.stem,
                    files=[path],
                    kind="dicom_image",
                    display_source=_display(path, root),
                    data_kind="image2d",
                    patient_key=_patient_key(header["patient_id"]),
                    metadata=header,
                    series_meta=SeriesMetadata.from_mapping(header),
                )
            ], []
        return [], [ImportIssue(source=str(path), message="不支持的二维影像格式")]

    if table_formats.is_table_file(path):
        return [
            DiscoveredCase(
                case_uid=path.stem,
                files=[path],
                kind="table_file",
                display_source=_display(path, root),
                data_kind="table",
            )
        ], []
    return [], [ImportIssue(source=str(path), message="不支持的表格格式")]


def _instance_numbers(files: list[Path]) -> dict[Path, int]:
    numbers: dict[Path, int] = {}
    for path in files:
        try:
            numbers[path] = _read_header(path).get("instance_number") or 0
        except Exception:  # noqa: BLE001
            numbers[path] = 0
    return numbers


def _materialize_volume(
    item: DiscoveredCase, out_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    numbers = _instance_numbers(item.files) if item.kind == "dicom_series" else None
    return volume_formats.normalize_volume(item.files, item.kind, out_path, numbers)


def _materialize_image(
    item: DiscoveredCase, out_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    return image_formats.normalize_image(item.files[0], item.kind, out_path)


def _source_manifest(
    item: DiscoveredCase,
    metadata: dict[str, Any],
    canonical_format: str,
    sheet_name: str | None,
) -> dict[str, Any]:
    files = []
    total = 0
    for path in item.files:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        total += size
        if len(files) < 1000:
            files.append({"name": path.name, "size": size})
    return {
        "schema_version": 2,
        "source_kind": item.kind,
        "source_name": item.display_source,
        "source_format": metadata.get("source_format"),
        "canonical_format": canonical_format,
        "sheet_name": sheet_name,
        "file_count": len(item.files),
        "total_bytes": total,
        "files": files,
        "original_retained": False,
        "converter": "medpowers-studio/2",
    }


def _get_or_create_blob(db: Session, ref: asset_store.BlobRef) -> Blob:
    blob = db.scalar(select(Blob).where(Blob.sha256 == ref.sha256))
    if blob is not None:
        return blob
    blob = Blob(
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        media_type=ref.media_type,
        storage_key=ref.storage_key,
    )
    db.add(blob)
    db.flush()
    return blob


def _import_item(
    db: Session,
    dataset: Dataset,
    item: DiscoveredCase,
    existing: set[str],
    temp_dir: Path,
) -> tuple[list[str], int]:
    """导入一个逻辑病例，返回 (case_uid 列表, 写入字节数)。"""

    imported: list[str] = []
    stored_bytes = 0

    if item.data_kind == "volume3d":
        out = temp_dir / "image.nrrd"
        geometry, metadata = _materialize_volume(item, out)
        assets = [
            (item.case_uid, out, "nrrd", "application/octet-stream", geometry, metadata, None)
        ]
    elif item.data_kind == "image2d":
        out = temp_dir / "image.png"
        geometry, metadata = _materialize_image(item, out)
        assets = [(item.case_uid, out, "png", "image/png", geometry, metadata, None)]
    else:
        table_assets = table_formats.normalize_table(item.files[0], temp_dir)
        assets = []
        for sheet_name, out, geometry, metadata in table_assets:
            case_uid = item.case_uid
            if len(table_assets) > 1 or sheet_name != item.case_uid:
                case_uid = f"{item.case_uid}__{sheet_name}"
            assets.append(
                (
                    case_uid,
                    out,
                    "parquet",
                    table_formats.TABLE_MEDIA_TYPE,
                    geometry,
                    metadata,
                    sheet_name,
                )
            )

    for case_uid_raw, path, fmt, media_type, geometry, metadata, sheet_name in assets:
        base = storage.sanitize_name(case_uid_raw)
        case_uid = storage.unique_name(base, existing)
        existing.add(case_uid)
        case_id = new_id()
        with db.begin_nested():
            assignment = hierarchy.assign_hierarchy(
                db,
                dataset,
                case_uid,
                item.series_meta,
                patient_key_override=item.patient_key,
            )
            case_metadata = hierarchy.sanitize_metadata(metadata, assignment.patient_key)
            case_metadata.update(item.series_meta.safe_metadata(assignment.patient_key))
            case_metadata["source_name"] = item.display_source
            case_metadata["source_kind"] = item.kind
            case_metadata["source_format"] = metadata.get("source_format")
            case_metadata["canonical_format"] = fmt
            case_metadata["data_kind"] = item.data_kind
            case_metadata["original_retained"] = False
            if sheet_name:
                case_metadata["sheet_name"] = sheet_name

            case = Case(
                id=case_id,
                dataset_id=dataset.id,
                study_id=assignment.study.id,
                case_uid=case_uid,
                series_uid=assignment.series_uid,
                series_number=item.series_meta.series_number,
                series_description=item.series_meta.series_description,
                patient_key=assignment.patient_key,
                image_path="",
                image_format=fmt,
                data_kind=item.data_kind,
                geometry=geometry,
                source_kind=item.kind,
                source_path=item.display_source,
                metadata_json=case_metadata,
            )
            db.add(case)
            db.flush()

            ref = asset_store.put_file(path, media_type)
            blob = _get_or_create_blob(db, ref)
            case.image_path = ref.storage_key
            case.size_bytes = ref.size_bytes
            case.sha256 = ref.sha256
            db.add(
                CaseAsset(
                    case_id=case.id,
                    blob_id=blob.id,
                    role="canonical",
                    format=fmt,
                    metadata_json={"media_type": media_type},
                )
            )

            manifest = _source_manifest(item, metadata, fmt, sheet_name)
            manifest_ref = asset_store.put_bytes(
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            )
            manifest_blob = _get_or_create_blob(db, manifest_ref)
            db.add(
                CaseAsset(
                    case_id=case.id,
                    blob_id=manifest_blob.id,
                    role="source_manifest",
                    format="json",
                    metadata_json={},
                )
            )
            stored_bytes += ref.size_bytes
        imported.append(case_uid)

    return imported, stored_bytes


def import_from_path(
    db: Session,
    dataset: Dataset,
    source: str | Path,
    recursive: bool = True,
    acknowledge_source_discarded: bool = False,
) -> ImportReport:
    if not acknowledge_source_discarded:
        raise ValueError("请先确认已自行备份原始数据；平台只保留规范化格式")

    spec = get_modality(dataset.modality)
    source_path = Path(source).expanduser().resolve()
    discovered, issues = discover_cases(source_path, spec, recursive=recursive)
    report = ImportReport(errors=list(issues))

    total_bytes = 0
    for item in discovered:
        for path in item.files:
            with suppress(OSError):
                total_bytes += path.stat().st_size
    if total_bytes:
        storage.assert_free_space(total_bytes)

    existing = set(db.scalars(select(Case.case_uid).where(Case.dataset_id == dataset.id)).all())
    existing_series = {
        uid
        for uid in db.scalars(
            select(Case.series_uid).where(
                Case.dataset_id == dataset.id, Case.series_uid.is_not(None)
            )
        ).all()
        if uid
    }
    for item in discovered:
        series_uid = (item.series_meta.series_uid or "").strip()
        if series_uid and series_uid in existing_series:
            # 智能体重试/重复上传时按 SeriesInstanceUID 幂等跳过，不生成 _2 副本。
            report.skipped += 1
            report.warnings.append(
                f"跳过已存在序列：{item.display_source}（SeriesInstanceUID={series_uid}）"
            )
            continue
        temp_dir = storage.tmp_dir(f"import_{uuid.uuid4().hex}")
        try:
            imported, stored_bytes = _import_item(db, dataset, item, existing, temp_dir)
            report.imported += len(imported)
            report.converted += len(imported)
            report.stored_bytes += stored_bytes
            report.cases.extend(imported)
            if imported and series_uid:
                existing_series.add(series_uid)
        except Exception as exc:  # noqa: BLE001
            report.skipped += 1
            report.errors.append(ImportIssue(source=item.display_source, message=str(exc)))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    db.flush()
    dataset.case_count = int(
        db.scalar(select(func.count()).select_from(Case).where(Case.dataset_id == dataset.id))
        or 0
    )
    db.commit()
    return report


def save_upload(upload: UploadFile, dest: Path, max_mb: int) -> None:
    max_bytes = max_mb * 1024 * 1024
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"上传文件超过限制（{max_mb} MB）")
            out.write(chunk)


def extract_zip(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.startswith("__MACOSX/") or name.startswith(".") or "/." in name:
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:  # 忽略符号链接
                continue
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise ValueError("压缩包包含非法路径")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def import_from_upload(
    db: Session,
    dataset: Dataset,
    upload: UploadFile,
    max_upload_mb: int,
    acknowledge_source_discarded: bool = False,
) -> ImportReport:
    work = storage.tmp_dir(f"upload_{uuid.uuid4().hex}")
    try:
        zip_path = work / "upload.zip"
        save_upload(upload, zip_path, max_upload_mb)
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("上传文件不是有效的 ZIP 压缩包")
        extracted = work / "extracted"
        extracted.mkdir(parents=True, exist_ok=True)
        extract_zip(zip_path, extracted)
        return import_from_path(
            db,
            dataset,
            extracted,
            recursive=True,
            acknowledge_source_discarded=acknowledge_source_discarded,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
