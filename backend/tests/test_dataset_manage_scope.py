from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Dataset, ImportJob

from .conftest import TEST_ROOT
from .helpers import make_volume_nrrd, png_bytes, unique, zip_predictions

SCOPES = ["studio:read", "studio:data", "studio:dataset-manage"]


def _create_token(
    client: TestClient,
    headers: dict[str, str],
    *,
    scopes: list[str] = SCOPES,
    repo_key: str = "qc-repo",
) -> dict:
    response = client.post(
        "/api/auth/tokens",
        headers=headers,
        json={
            "name": unique("dataset-manage"),
            "repo_key": repo_key,
            "scopes": scopes,
            "expires_in_days": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_protocol(client: TestClient, headers: dict[str, str], modality: str = "DR") -> dict:
    code = unique("protocol")
    response = client.post(
        "/api/scan-protocols",
        headers=headers,
        json={"code": code, "name": f"流程 {code}", "modality_scope": [modality]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_dataset(
    client: TestClient, headers: dict[str, str], protocol_id: str, modality: str = "DR"
) -> dict:
    response = client.post(
        "/api/datasets",
        headers=headers,
        json={
            "code": unique("dataset"),
            "name": "令牌创建的数据集",
            "modality": modality,
            "scan_protocol_id": protocol_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _dataset_payload(protocol_id: str, modality: str = "DR") -> dict:
    return {
        "code": unique("dataset"),
        "name": "令牌创建的数据集",
        "modality": modality,
        "scan_protocol_id": protocol_id,
    }


def test_dataset_manage_scope_full_flow(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = _create_token(client, admin_headers)
    token_headers = _bearer(created["token"])

    # 新建扫描流程 + 数据集（scope 中间件与路由依赖都放行）
    protocol = _create_protocol(client, token_headers)
    dataset = _create_dataset(client, token_headers, protocol["id"])
    assert dataset["created_by_token_id"] == created["info"]["id"]
    assert dataset["created_by_repo_key"] == "qc-repo"
    assert dataset["created_by"]["username"] == "admin"

    # 修改属性
    updated = client.patch(
        f"/api/datasets/{dataset['id']}",
        headers=token_headers,
        json={"name": "改名后的数据集", "description": "令牌更新"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "改名后的数据集"

    # ZIP 上传（2D PNG）
    content = zip_predictions(
        {"case_0.png": png_bytes(np.full((64, 64), 40, dtype=np.uint8))}
    )
    report = client.post(
        f"/api/datasets/{dataset['id']}/import-upload",
        headers=token_headers,
        files={"file": ("cases.zip", content, "application/zip")},
        data={"acknowledge_source_discarded": "true"},
    )
    assert report.status_code == 200, report.text
    assert report.json()["imported"] == 1, report.text

    ready = client.post(f"/api/datasets/{dataset['id']}/ready", headers=token_headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"

    # 只增不删：破坏性接口仍要求网页管理员
    assert client.delete(f"/api/datasets/{dataset['id']}", headers=token_headers).status_code == 403
    assert (
        client.post(f"/api/datasets/{dataset['id']}/archive", headers=token_headers).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/scan-protocols/{protocol['id']}",
            headers=token_headers,
            json={"name": "不允许改名"},
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/scan-protocols/{protocol['id']}", headers=token_headers).status_code
        == 403
    )


def test_dataset_manage_scope_is_required(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    protocol = _create_protocol(client, admin_headers)
    payload = _dataset_payload(protocol["id"])

    read_token = _bearer(_create_token(client, admin_headers, scopes=["studio:read"])["token"])
    response = client.post("/api/datasets", headers=read_token, json=payload)
    assert response.status_code == 403, response.text
    assert "studio:dataset-manage" in response.text

    # 旧的 studio:write 令牌不再能写数据集/扫描流程
    write_token = _bearer(_create_token(client, admin_headers, scopes=["studio:write"])["token"])
    response = client.post("/api/datasets", headers=write_token, json=payload)
    assert response.status_code == 403, response.text
    assert "studio:dataset-manage" in response.text
    response = client.post(
        "/api/scan-protocols",
        headers=write_token,
        json={"code": unique("protocol"), "name": "流程", "modality_scope": ["DR"]},
    )
    assert response.status_code == 403, response.text


def test_dataset_manage_requires_admin_owned_token(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    username = unique("token_user")
    created_user = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": "pass1234", "role": "annotator"},
    )
    assert created_user.status_code == 201, created_user.text
    login = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    assert login.status_code == 200, login.text
    user_headers = _bearer(login.json()["access_token"])

    token = _create_token(
        client, user_headers, scopes=["studio:read", "studio:dataset-manage"]
    )["token"]
    response = client.post(
        "/api/scan-protocols",
        headers=_bearer(token),
        json={"code": unique("protocol"), "name": "流程", "modality_scope": ["DR"]},
    )
    assert response.status_code == 403, response.text
    assert "管理员" in response.text


def test_auth_context_reports_dataset_manage(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    token = _create_token(client, admin_headers)["token"]
    context = client.get("/api/auth/context", headers=_bearer(token))
    assert context.status_code == 200, context.text
    assert context.json()["capabilities"]["dataset_manage"] is True


def test_import_skips_existing_series_uid(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    protocol = _create_protocol(client, admin_headers, modality="CT")
    dataset = _create_dataset(client, admin_headers, protocol["id"], modality="CT")
    second = _create_dataset(client, admin_headers, protocol["id"], modality="CT")
    source = TEST_ROOT / "sources" / unique("dedup")
    make_volume_nrrd(source / "volume.nrrd", series_uid="1.2.826.0.1.3680043.10.999")

    payload = {"path": str(source), "acknowledge_source_discarded": True}
    first = client.post(
        f"/api/datasets/{dataset['id']}/import-path", headers=admin_headers, json=payload
    )
    assert first.status_code == 200, first.text
    assert first.json()["imported"] == 1

    second_report = client.post(
        f"/api/datasets/{dataset['id']}/import-path", headers=admin_headers, json=payload
    )
    assert second_report.status_code == 200, second_report.text
    body = second_report.json()
    assert body["imported"] == 0, body
    assert body["skipped"] == 1, body
    assert any("SeriesInstanceUID" in warning for warning in body["warnings"]), body

    detail = client.get(f"/api/datasets/{dataset['id']}", headers=admin_headers).json()
    assert detail["case_count"] == 1

    # 去重只作用于同一数据集
    other = client.post(
        f"/api/datasets/{second['id']}/import-path", headers=admin_headers, json=payload
    )
    assert other.status_code == 200, other.text
    assert other.json()["imported"] == 1, other.text


def test_token_import_job_quota(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create_token(client, admin_headers)
    token_headers = _bearer(created["token"])
    protocol = _create_protocol(client, token_headers)
    dataset = _create_dataset(client, token_headers, protocol["id"])

    with SessionLocal() as db:
        stored = db.scalar(select(Dataset).where(Dataset.id == dataset["id"]))
        assert stored is not None
        for _ in range(3):
            db.add(
                ImportJob(
                    dataset_id=stored.id,
                    source_type="path",
                    source_path="/nonexistent/source",
                    recursive=True,
                    status="queued",
                    created_by_token_id=created["info"]["id"],
                    created_by_repo_key="qc-repo",
                )
            )
        db.commit()

    response = client.post(
        f"/api/datasets/{dataset['id']}/import-jobs",
        headers=token_headers,
        json={
            "path": str(TEST_ROOT / "sources"),
            "acknowledge_source_discarded": True,
        },
    )
    assert response.status_code == 429, response.text
    assert "不能超过 3 个" in response.text

    # 网页管理员不受令牌配额限制
    admin_response = client.post(
        f"/api/datasets/{dataset['id']}/import-jobs",
        headers=admin_headers,
        json={
            "path": "/nonexistent/admin-source",
            "acknowledge_source_discarded": True,
        },
    )
    assert admin_response.status_code == 202, admin_response.text
