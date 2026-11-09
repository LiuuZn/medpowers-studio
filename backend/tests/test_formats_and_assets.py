from __future__ import annotations

import io
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Blob, Case, CaseAsset

from .conftest import TEST_ROOT
from .helpers import create_dataset, create_protocol, unique


def _csv_bytes() -> bytes:
    return b"patient_id,age,label\nP1,60,1\nP2,45,0\n"


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    first = workbook.active
    first.title = "随访"
    first.append(["patient_id", "score"])
    first.append(["P1", 3])
    second = workbook.create_sheet("基线")
    second.append(["patient_id", "score"])
    second.append(["P2", 7])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _parquet_bytes() -> bytes:
    table = pa.table({"patient_id": ["P3", "P4"], "value": [1.5, 2.5]})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _import_files(
    client: TestClient, headers: dict[str, str], dataset_id: str, files: dict[str, bytes]
) -> dict:
    source = TEST_ROOT / "sources" / unique("table_src")
    source.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (source / name).write_bytes(content)
    response = client.post(
        f"/api/datasets/{dataset_id}/import-path",
        headers=headers,
        json={"path": str(source), "acknowledge_source_discarded": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _table_dataset(client: TestClient, headers: dict[str, str]) -> dict:
    protocol = create_protocol(client, headers, modality="TABLE")
    return create_dataset(client, headers, protocol["id"], modality="TABLE")


def test_table_import_and_preview(client: TestClient, admin_headers: dict[str, str]) -> None:
    dataset = _table_dataset(client, admin_headers)
    report = _import_files(
        client,
        admin_headers,
        dataset["id"],
        {
            "labs.csv": _csv_bytes(),
            "followup.xlsx": _xlsx_bytes(),
            "values.parquet": _parquet_bytes(),
        },
    )
    assert report["imported"] == 4, report
    assert report["stored_bytes"] > 0

    cases = client.get(
        f"/api/datasets/{dataset['id']}/cases?page_size=50", headers=admin_headers
    ).json()["items"]
    assert {case["data_kind"] for case in cases} == {"table"}
    assert {case["image_format"] for case in cases} == {"parquet"}
    assert any(case["case_uid"].endswith("__随访") for case in cases)
    assert any(case["case_uid"].endswith("__基线") for case in cases)

    csv_case = next(case for case in cases if case["case_uid"] == "labs")
    info = client.get(f"/api/cases/{csv_case['id']}/table-info", headers=admin_headers)
    assert info.status_code == 200, info.text
    assert info.json()["row_count"] == 2
    assert [column["name"] for column in info.json()["columns"]] == [
        "patient_id",
        "age",
        "label",
    ]

    page = client.get(f"/api/cases/{csv_case['id']}/table?offset=1&limit=1", headers=admin_headers)
    assert page.status_code == 200, page.text
    payload = page.json()
    assert payload["total"] == 2
    assert payload["rows"] == [["P2", 45, 0]]

    # 表格不能走切片接口
    assert (
        client.get(f"/api/cases/{csv_case['id']}/slice-info", headers=admin_headers).status_code
        == 400
    )

    with SessionLocal() as db:
        case = db.get(Case, csv_case["id"])
        assert case is not None
        assert not Path(case.image_path).is_absolute()
        assert case.image_path.startswith("blobs/sha256/")
        assert case.sha256 and case.size_bytes > 0
        assets = db.scalars(select(CaseAsset).where(CaseAsset.case_id == case.id)).all()
        assert {asset.role for asset in assets} == {"canonical", "source_manifest"}


def test_content_dedup_and_reference_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    dataset = _table_dataset(client, admin_headers)
    _import_files(client, admin_headers, dataset["id"], {"same.csv": _csv_bytes()})
    _import_files(client, admin_headers, dataset["id"], {"same.csv": _csv_bytes()})

    with SessionLocal() as db:
        cases = db.scalars(select(Case).where(Case.dataset_id == dataset["id"])).all()
        assert len(cases) == 2
        hashes = {case.sha256 for case in cases}
        assert len(hashes) == 1
        digest = hashes.pop()
        count = db.scalar(select(func.count()).select_from(Blob).where(Blob.sha256 == digest))
        assert count == 1

    response = client.post(
        f"/api/datasets/{dataset['id']}/import-path",
        headers=admin_headers,
        json={
            "path": str(TEST_ROOT),
            "mode": "reference",
            "acknowledge_source_discarded": True,
        },
    )
    assert response.status_code == 422

    response = client.post(
        f"/api/datasets/{dataset['id']}/import-path",
        headers=admin_headers,
        json={"path": str(TEST_ROOT)},
    )
    assert response.status_code == 400
    assert "备份" in response.json()["detail"]


def test_nifti_is_normalized_to_nrrd(client: TestClient, admin_headers: dict[str, str]) -> None:
    import numpy as np
    import SimpleITK as sitk

    protocol = create_protocol(client, admin_headers, modality="CT")
    dataset = create_dataset(client, admin_headers, protocol["id"], modality="CT")
    source = TEST_ROOT / "sources" / unique("nifti")
    source.mkdir(parents=True, exist_ok=True)
    image = sitk.GetImageFromArray(np.ones((4, 16, 16), dtype=np.int16))
    image.SetSpacing((1.0, 1.0, 2.0))
    sitk.WriteImage(image, str(source / "scan.nii.gz"))

    response = client.post(
        f"/api/datasets/{dataset['id']}/import-path",
        headers=admin_headers,
        json={"path": str(source), "acknowledge_source_discarded": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1

    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]
    assert case["data_kind"] == "volume3d"
    assert case["image_format"] == "nrrd"
    info = client.get(f"/api/cases/{case['id']}/slice-info", headers=admin_headers)
    assert info.status_code == 200, info.text
    assert info.json()["dimension"] == "3d"
    assert info.json()["slices"] == 4


def test_background_import_job(client: TestClient, admin_headers: dict[str, str]) -> None:
    import time

    dataset = _table_dataset(client, admin_headers)
    source = TEST_ROOT / "sources" / unique("job_src")
    source.mkdir(parents=True, exist_ok=True)
    (source / "job.csv").write_bytes(_csv_bytes())

    response = client.post(
        f"/api/datasets/{dataset['id']}/import-jobs",
        headers=admin_headers,
        json={
            "path": str(source),
            "recursive": True,
            "acknowledge_source_discarded": True,
        },
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] in {"queued", "running"}

    deadline = time.time() + 15
    while time.time() < deadline:
        job = client.get(
            f"/api/datasets/{dataset['id']}/import-jobs/{job['id']}",
            headers=admin_headers,
        ).json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.2)

    assert job["status"] == "succeeded", job
    assert job["imported"] == 1
    assert job["stored_bytes"] > 0
