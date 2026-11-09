from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from fastapi.testclient import TestClient
from PIL import Image

from .conftest import TEST_ROOT


def unique(prefix: str = "x") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def create_protocol(
    client: TestClient,
    headers: dict[str, str],
    modality: str = "CT",
    code: str | None = None,
) -> dict:
    code = code or unique("protocol")
    response = client.post(
        "/api/scan-protocols",
        headers=headers,
        json={
            "code": code,
            "name": f"流程 {code}",
            "modality_scope": [modality],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_dataset(
    client: TestClient,
    headers: dict[str, str],
    protocol_id: str,
    modality: str = "CT",
    code: str | None = None,
) -> dict:
    code = code or unique("dataset")
    response = client.post(
        "/api/datasets",
        headers=headers,
        json={
            "code": code,
            "name": f"数据集 {code}",
            "modality": modality,
            "scan_protocol_id": protocol_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def mark_ready(client: TestClient, headers: dict[str, str], dataset_id: str) -> dict:
    response = client.post(f"/api/datasets/{dataset_id}/ready", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def make_2d_png(path: Path, width: int = 64, height: int = 64, value: int = 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.full((height, width), value, dtype=np.uint8)
    array[height // 4 : height // 2, width // 4 : width // 2] = 180
    Image.fromarray(array).save(path)
    return path


def make_mask_png(
    path: Path,
    width: int = 64,
    height: int = 64,
    label: int = 1,
    box: tuple[int, int, int, int] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((height, width), dtype=np.uint8)
    y0, y1, x0, x1 = box or (height // 4, height // 2, width // 4, width // 2)
    array[y0:y1, x0:x1] = label
    Image.fromarray(array).save(path)
    return path


def make_volume_nrrd(
    path: Path,
    z: int = 8,
    y: int = 32,
    x: int = 32,
    *,
    patient_id: str | None = None,
    study_uid: str | None = None,
    series_uid: str | None = None,
    study_description: str = "测试检查",
    series_description: str = "测试序列",
    series_number: int = 1,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((z, y, x), dtype=np.int16)
    array[z // 4 : z // 2, y // 4 : y // 2, x // 4 : x // 2] = 120
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((1.1, 1.2, 2.0))
    image.SetOrigin((10.0, 20.0, 30.0))
    if patient_id:
        image.SetMetaData("PatientID", patient_id)
        image.SetMetaData("PatientSex", "F")
        image.SetMetaData("PatientAge", "060Y")
    if study_uid:
        image.SetMetaData("StudyInstanceUID", study_uid)
        image.SetMetaData("StudyDescription", study_description)
        image.SetMetaData("StudyDate", "20260101")
        image.SetMetaData("AccessionNumber", "ACC-TEST-001")
    if series_uid:
        image.SetMetaData("SeriesInstanceUID", series_uid)
        image.SetMetaData("SeriesDescription", series_description)
        image.SetMetaData("SeriesNumber", str(series_number))
    sitk.WriteImage(image, str(path), True)
    return path


def import_2d(client: TestClient, headers: dict[str, str], dataset_id: str, count: int = 1) -> dict:
    source = TEST_ROOT / "sources" / unique("src2d")
    for index in range(count):
        make_2d_png(source / f"case_{index}.png", value=30 + index)
    response = client.post(
        f"/api/datasets/{dataset_id}/import-path",
        headers=headers,
        json={"path": str(source), "acknowledge_source_discarded": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def import_3d(client: TestClient, headers: dict[str, str], dataset_id: str, count: int = 1) -> dict:
    source = TEST_ROOT / "sources" / unique("src3d")
    for index in range(count):
        make_volume_nrrd(source / f"volume_{index}.nrrd")
    response = client.post(
        f"/api/datasets/{dataset_id}/import-path",
        headers=headers,
        json={"path": str(source), "acknowledge_source_discarded": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_task(
    client: TestClient,
    headers: dict[str, str],
    task_type: str,
    code: str | None = None,
    label_schema: dict | None = None,
) -> dict:
    code = code or unique(task_type)
    payload = {
        "code": code,
        "name": f"任务 {code}",
        "task_type": task_type,
        "annotation_guide": "测试标注指南",
    }
    if label_schema is not None:
        payload["label_schema"] = label_schema
    response = client.post("/api/tasks", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def link_dataset(
    client: TestClient, headers: dict[str, str], task_id: str, dataset_id: str
) -> dict:
    response = client.post(
        f"/api/tasks/{task_id}/datasets",
        headers=headers,
        json={"dataset_id": dataset_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def prepare_dataset(
    client: TestClient,
    headers: dict[str, str],
    modality: str,
    dimension: str,
    count: int = 1,
) -> dict:
    protocol = create_protocol(client, headers, modality=modality)
    dataset = create_dataset(client, headers, protocol["id"], modality=modality)
    if dimension == "2d":
        report = import_2d(client, headers, dataset["id"], count=count)
    else:
        report = import_3d(client, headers, dataset["id"], count=count)
    assert report["imported"] == count, report
    return mark_ready(client, headers, dataset["id"])


def png_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array.astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def mask_bytes(width: int = 64, height: int = 64, label: int = 1) -> bytes:
    array = np.zeros((height, width), dtype=np.uint8)
    array[height // 4 : height // 2, width // 4 : width // 2] = label
    return png_bytes(array)


def zip_predictions(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()
