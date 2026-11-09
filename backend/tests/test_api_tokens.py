from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiToken, User
from app.security import hash_api_token

from .helpers import unique


def _create_token(
    client: TestClient,
    headers: dict[str, str],
    *,
    scopes: list[str],
    name: str = "test-token",
    expires_in_days: int = 30,
) -> dict:
    response = client.post(
        "/api/auth/tokens",
        headers=headers,
        json={"name": name, "scopes": scopes, "expires_in_days": expires_in_days},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bearer(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def test_personal_access_token_scopes_and_revocation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    read_token = _create_token(client, admin_headers, scopes=["studio:read"])["token"]

    listed = client.get("/api/auth/tokens", headers=admin_headers)
    assert listed.status_code == 200
    assert any(item["prefix"] == read_token[:12] for item in listed.json())

    # 只读 scope 可以读取元数据
    assert client.get("/api/datasets", headers=_bearer(read_token)).status_code == 200
    assert client.get("/api/auth/me", headers=_bearer(read_token)).status_code == 200
    context = client.get("/api/auth/context", headers=_bearer(read_token))
    assert context.status_code == 200, context.text
    assert context.json()["auth_method"] == "token"
    assert context.json()["scopes"] == ["studio:read"]
    assert context.json()["capabilities"] == {
        "read": True,
        "data": False,
        "write": False,
        "experiment": False,
        "evaluate": False,
        "review_request": False,
        "dataset_manage": False,
    }

    # 下载/像素数据需要 studio:data，且在路由查库前就被拦截
    response = client.get("/api/cases/not-exist/slice", headers=_bearer(read_token))
    assert response.status_code == 403, response.text
    assert "studio:data" in response.text

    # 写操作需要 studio:write
    response = client.post(
        "/api/scan-protocols",
        headers=_bearer(read_token),
        json={"code": unique("scope"), "name": "scope test"},
    )
    assert response.status_code == 403, response.text

    data_token = _create_token(client, admin_headers, scopes=["studio:data"])["token"]
    # scope 通过后由业务返回 404，说明不是被鉴权层拦截
    assert client.get("/api/cases/not-exist/slice", headers=_bearer(data_token)).status_code == 404
    assert client.get("/api/datasets", headers=_bearer(data_token)).status_code == 403

    # 写数据集接口现在要求专门的 studio:dataset-manage，studio:write 不再放行
    write_token = _create_token(client, admin_headers, scopes=["studio:write"])["token"]
    created = client.post(
        "/api/scan-protocols",
        headers=_bearer(write_token),
        json={"code": unique("scope"), "name": "scope test"},
    )
    assert created.status_code == 403, created.text
    assert "studio:dataset-manage" in created.text

    # 即使用户是管理员，API 令牌也不能调用用户管理接口
    assert client.get("/api/users", headers=_bearer(write_token)).status_code == 403

    token_id = listed.json()[0]["id"]
    revoked = client.post(f"/api/auth/tokens/{token_id}/revoke", headers=admin_headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert client.get("/api/datasets", headers=_bearer(read_token)).status_code == 401
    assert client.delete(f"/api/auth/tokens/{token_id}", headers=admin_headers).status_code == 204
    assert all(
        item["id"] != token_id
        for item in client.get("/api/auth/tokens", headers=admin_headers).json()
    )


def test_api_token_hard_delete(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create_token(client, admin_headers, scopes=["studio:read"], name="delete-me")
    raw = created["token"]
    token_id = created["info"]["id"]
    assert client.get("/api/datasets", headers=_bearer(raw)).status_code == 200

    assert client.delete(f"/api/auth/tokens/{token_id}", headers=admin_headers).status_code == 204
    assert client.get("/api/datasets", headers=_bearer(raw)).status_code == 401
    assert all(
        item["id"] != token_id
        for item in client.get("/api/auth/tokens", headers=admin_headers).json()
    )


def test_api_token_cannot_manage_tokens(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    read_token = _create_token(client, admin_headers, scopes=["studio:read"])["token"]
    assert client.get("/api/auth/tokens", headers=_bearer(read_token)).status_code == 403
    assert (
        client.post(
            "/api/auth/tokens",
            headers=_bearer(read_token),
            json={"name": "escalate", "scopes": ["studio:write"], "expires_in_days": 30},
        ).status_code
        == 403
    )


def test_expired_token_and_deactivated_user(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    raw = _create_token(client, admin_headers, scopes=["studio:read"], name="expiring")["token"]
    with SessionLocal() as db:
        token = db.scalar(
            select(ApiToken).where(ApiToken.token_hash == hash_api_token(raw))
        )
        assert token is not None
        token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/datasets", headers=_bearer(raw)).status_code == 401

    username = f"token_user_{unique('u')}"
    created = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": "pass1234", "role": "annotator"},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    login = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    assert login.status_code == 200, login.text
    user_headers = _bearer(login.json()["access_token"])
    user_token = _create_token(client, user_headers, scopes=["studio:read"])["token"]
    assert client.get("/api/datasets", headers=_bearer(user_token)).status_code == 200

    assert (
        client.patch(
            f"/api/users/{user_id}", headers=admin_headers, json={"is_active": False}
        ).status_code
        == 200
    )
    assert client.get("/api/datasets", headers=_bearer(user_token)).status_code == 401


def test_device_authorization_flow(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    code_response = client.post(
        "/api/auth/device/code",
        json={"client_name": "medpowers-plugin-test", "scopes": ["studio:read"]},
    )
    assert code_response.status_code == 200, code_response.text
    code = code_response.json()
    assert code["user_code"].count("-") == 1
    assert code["verification_uri"].endswith("/device")

    pending = client.post("/api/auth/device/token", json={"device_code": code["device_code"]})
    assert pending.status_code == 400
    assert pending.json()["error"] == "authorization_pending"

    lookup = client.post(
        "/api/auth/device/lookup",
        headers=admin_headers,
        json={"user_code": code["user_code"]},
    )
    assert lookup.status_code == 200, lookup.text
    assert lookup.json()["client_name"] == "medpowers-plugin-test"
    assert lookup.json()["scopes"] == ["studio:read"]

    approved = client.post(
        "/api/auth/device/approve",
        headers=admin_headers,
        json={"user_code": code["user_code"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    token_response = client.post(
        "/api/auth/device/token", json={"device_code": code["device_code"]}
    )
    assert token_response.status_code == 200, token_response.text
    payload = token_response.json()
    assert payload["scope"] == "studio:read"
    assert payload["user"]["username"] == "admin"
    access_token = payload["access_token"]

    assert client.get("/api/datasets", headers=_bearer(access_token)).status_code == 200
    assert (
        client.get("/api/cases/not-exist/slice", headers=_bearer(access_token)).status_code
        == 403
    )

    repeated = client.post("/api/auth/device/token", json={"device_code": code["device_code"]})
    assert repeated.status_code == 400
    assert repeated.json()["error"] == "expired_token"

    tokens = client.get("/api/auth/tokens", headers=admin_headers).json()
    assert any(
        item["source"] == "device" and item["client_name"] == "medpowers-plugin-test"
        for item in tokens
    )


def test_device_authorization_denied(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    code = client.post(
        "/api/auth/device/code",
        json={"client_name": "denied-plugin", "scopes": ["studio:read"]},
    ).json()
    denied = client.post(
        "/api/auth/device/deny",
        headers=admin_headers,
        json={"user_code": code["user_code"]},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["status"] == "denied"

    polled = client.post("/api/auth/device/token", json={"device_code": code["device_code"]})
    assert polled.status_code == 400
    assert polled.json()["error"] == "access_denied"


def test_device_approval_requires_web_session(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    code = client.post(
        "/api/auth/device/code",
        json={"client_name": "jwt-required", "scopes": ["studio:read"]},
    ).json()
    read_token = _create_token(client, admin_headers, scopes=["studio:read"])["token"]
    response = client.post(
        "/api/auth/device/approve",
        headers=_bearer(read_token),
        json={"user_code": code["user_code"]},
    )
    assert response.status_code == 403, response.text


def test_token_records_belong_to_owner(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    username = f"token_owner_{unique('u')}"
    created = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": "pass1234", "role": "reviewer"},
    )
    assert created.status_code == 201, created.text
    login = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    user_headers = _bearer(login.json()["access_token"])
    user_token = _create_token(client, user_headers, scopes=["studio:read"], name="owner")["token"]
    token_id = client.get("/api/auth/tokens", headers=user_headers).json()[0]["id"]

    # 其他用户的令牌不共享，也不能被他人撤销
    admin_tokens = client.get("/api/auth/tokens", headers=admin_headers).json()
    assert all(item["id"] != token_id for item in admin_tokens)
    assert (
        client.delete(f"/api/auth/tokens/{token_id}", headers=admin_headers).status_code == 404
    )
    assert client.get("/api/datasets", headers=_bearer(user_token)).status_code == 200

    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == username))
        assert owner is not None


def test_password_reset_revokes_tokens(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    username = f"reset_user_{unique('u')}"
    created = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": "pass1234", "role": "annotator"},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    login = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    user_headers = _bearer(login.json()["access_token"])
    raw = _create_token(client, user_headers, scopes=["studio:read"])["token"]

    reset = client.post(
        f"/api/users/{user_id}/reset-password",
        headers=admin_headers,
        json={"password": "newpass1234"},
    )
    assert reset.status_code == 200, reset.text
    assert client.get("/api/datasets", headers=_bearer(raw)).status_code == 401
