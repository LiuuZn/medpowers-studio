"""DICOM Patient / Study / Series 层级解析与落库。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import SimpleITK as sitk
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Dataset, Patient, Study, new_id

# 不落库的隐私字段（大小写不敏感）
_PRIVATE_KEYS = {
    "patient_id",
    "patientid",
    "patientname",
    "patient_name",
    "patientbirthdate",
    "patient_birth_date",
    "patientbirthtime",
    "otherpatientids",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value).strip()


def _pick(mapping: dict[str, Any], *names: str) -> str:
    normalized = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        value = normalized.get(name.lower())
        text = _text(value)
        if text:
            return text
    return ""


def _parse_int(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class SeriesMetadata:
    """一个序列可提取到的 DICOM 级别元数据。"""

    patient_id: str = ""
    patient_sex: str = ""
    patient_age: str = ""
    study_uid: str = ""
    study_description: str = ""
    study_date: str = ""
    accession_number: str = ""
    series_uid: str = ""
    series_description: str = ""
    series_number: int | None = None
    modality: str = ""

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> SeriesMetadata:
        return cls(
            patient_id=_pick(mapping, "PatientID", "patient_id"),
            patient_sex=_pick(mapping, "PatientSex", "patient_sex"),
            patient_age=_pick(mapping, "PatientAge", "patient_age"),
            study_uid=_pick(mapping, "StudyInstanceUID", "study_uid"),
            study_description=_pick(mapping, "StudyDescription", "study_description"),
            study_date=_pick(mapping, "StudyDate", "study_date"),
            accession_number=_pick(mapping, "AccessionNumber", "accession_number"),
            series_uid=_pick(mapping, "SeriesInstanceUID", "series_uid"),
            series_description=_pick(mapping, "SeriesDescription", "series_description"),
            series_number=_parse_int(_pick(mapping, "SeriesNumber", "series_number")),
            modality=_pick(mapping, "Modality", "modality"),
        )

    def safe_metadata(self, patient_key: str) -> dict[str, Any]:
        data = {
            "patient_key": patient_key,
            "study_uid": self.study_uid,
            "series_uid": self.series_uid,
            "study_description": self.study_description,
            "study_date": self.study_date,
            "accession_number": self.accession_number,
            "series_description": self.series_description,
            "series_number": self.series_number,
            "modality": self.modality,
        }
        return {key: value for key, value in data.items() if value not in (None, "")}


def read_volume_metadata(path: str | Path) -> SeriesMetadata:
    """只读 NRRD/NIfTI 头信息，不加载像素。"""

    reader = sitk.ImageFileReader()
    source = Path(path)
    # Blob 文件名是纯 sha256、没有扩展名，需要显式指定 NRRD ImageIO。
    if source.suffix.lower() not in {".nrrd", ".nii", ".gz"}:
        reader.SetImageIO("NrrdImageIO")
    reader.SetFileName(str(source))
    reader.ReadImageInformation()
    mapping = {key: reader.GetMetaData(key) for key in reader.GetMetaDataKeys()}
    return SeriesMetadata.from_mapping(mapping)


def patient_key_for_id(patient_id: str) -> str | None:
    if not patient_id:
        return None
    salt = get_settings().patient_salt
    digest = hashlib.sha256(f"{salt}:{patient_id}".encode()).hexdigest()[:20]
    return f"p_{digest}"


def patient_key_for_study(study_uid: str) -> str | None:
    if not study_uid:
        return None
    salt = get_settings().patient_salt
    digest = hashlib.sha256(f"{salt}:study:{study_uid}".encode()).hexdigest()[:20]
    return f"p_study_{digest}"


def anonymous_patient_key(dataset_id: str, case_uid: str) -> str:
    salt = get_settings().patient_salt
    digest = hashlib.sha256(f"{salt}:anonymous:{dataset_id}:{case_uid}".encode()).hexdigest()[:20]
    return f"p_anon_{digest}"


def resolve_patient_key(
    dataset: Dataset,
    case_uid: str,
    metadata: SeriesMetadata,
    override: str | None = None,
) -> str:
    """确定患者标识。

    优先级：已有 patient_key > PatientID > StudyInstanceUID > 序列级匿名患者。
    最后一个回退保证没有患者信息的文件不会在患者级划分中互相泄漏。
    """

    return (
        override
        or patient_key_for_id(metadata.patient_id)
        or patient_key_for_study(metadata.study_uid)
        or anonymous_patient_key(dataset.id, case_uid)
    )


def sanitize_metadata(metadata: dict[str, Any], patient_key: str) -> dict[str, Any]:
    result = {
        key: value
        for key, value in metadata.items()
        if str(key).lower() not in _PRIVATE_KEYS
    }
    result["patient_key"] = patient_key
    return result


def _ensure_patient(
    db: Session,
    patient_key: str,
    metadata: SeriesMetadata,
) -> Patient:
    patient = db.scalar(select(Patient).where(Patient.patient_key == patient_key))
    if patient is None:
        patient = Patient(
            id=new_id(),
            patient_key=patient_key,
            sex=metadata.patient_sex,
            age=metadata.patient_age,
            metadata_json={},
        )
        db.add(patient)
        db.flush()
        return patient
    if metadata.patient_sex and not patient.sex:
        patient.sex = metadata.patient_sex
    if metadata.patient_age and not patient.age:
        patient.age = metadata.patient_age
    return patient


def _ensure_study(
    db: Session,
    patient: Patient,
    study_uid: str,
    metadata: SeriesMetadata,
) -> Study:
    study = db.scalar(
        select(Study).where(Study.patient_id == patient.id, Study.study_uid == study_uid)
    )
    if study is None:
        study = Study(
            id=new_id(),
            patient_id=patient.id,
            study_uid=study_uid,
            description=metadata.study_description,
            study_date=metadata.study_date,
            accession_number=metadata.accession_number,
            metadata_json={
                key: value
                for key, value in {
                    "study_uid": study_uid,
                    "study_description": metadata.study_description,
                    "study_date": metadata.study_date,
                    "accession_number": metadata.accession_number,
                    "modality": metadata.modality,
                }.items()
                if value not in (None, "")
            },
        )
        db.add(study)
        db.flush()
        return study
    if metadata.study_description and not study.description:
        study.description = metadata.study_description
    if metadata.study_date and not study.study_date:
        study.study_date = metadata.study_date
    if metadata.accession_number and not study.accession_number:
        study.accession_number = metadata.accession_number
    return study


@dataclass(slots=True)
class HierarchyAssignment:
    patient: Patient
    study: Study
    patient_key: str
    study_uid: str
    series_uid: str


def assign_hierarchy(
    db: Session,
    dataset: Dataset,
    case_uid: str,
    metadata: SeriesMetadata,
    patient_key_override: str | None = None,
) -> HierarchyAssignment:
    """创建或复用 Patient/Study，并返回序列应写入的层级字段。"""

    patient_key = resolve_patient_key(dataset, case_uid, metadata, patient_key_override)
    study_uid = metadata.study_uid or f"local:{patient_key}"
    series_uid = metadata.series_uid or f"local:{case_uid}"
    patient = _ensure_patient(db, patient_key, metadata)
    study = _ensure_study(db, patient, study_uid, metadata)
    return HierarchyAssignment(
        patient=patient,
        study=study,
        patient_key=patient_key,
        study_uid=study_uid,
        series_uid=series_uid,
    )
