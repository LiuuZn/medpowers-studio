from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="medpowers_studio_test_"))
atexit.register(lambda: shutil.rmtree(_TEST_ROOT, ignore_errors=True))

os.environ["MEDPOWERS_DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'test.db'}"
os.environ["MEDPOWERS_STORAGE_ROOT"] = str(_TEST_ROOT / "storage")
os.environ["MEDPOWERS_STORAGE_MIN_FREE_GB"] = "0"
os.environ["MEDPOWERS_JWT_SECRET"] = "test-secret-key-with-at-least-32-bytes"
os.environ["MEDPOWERS_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["MEDPOWERS_BOOTSTRAP_ADMIN_PASSWORD"] = "admin123"
# 测试会批量创建 token；放宽限流，避免用例之间互相 429。
os.environ["MEDPOWERS_AUTH_RATE_LIMIT_PER_MINUTE"] = "1000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

TEST_ROOT = _TEST_ROOT


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.rate_limit import rate_limiter

    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "admin", "admin123")


@pytest.fixture
def annotator_headers(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    import uuid

    suffix = uuid.uuid4().hex[:8]
    username = f"annotator_{suffix}"
    response = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": "pass1234", "role": "annotator"},
    )
    assert response.status_code == 201, response.text
    return _login(client, username, "pass1234")


@pytest.fixture
def reviewer_headers(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    import uuid

    suffix = uuid.uuid4().hex[:8]
    username = f"reviewer_{suffix}"
    response = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": "pass1234", "role": "reviewer"},
    )
    assert response.status_code == 201, response.text
    return _login(client, username, "pass1234")
