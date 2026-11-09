from __future__ import annotations

from fastapi.testclient import TestClient

from .helpers import (
    create_task,
    link_dataset,
    mask_bytes,
    prepare_dataset,
    unique,
)


def _token(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    repo_key: str,
    scopes: list[str],
) -> str:
    response = client.post(
        "/api/auth/tokens",
        headers=admin_headers,
        json={
            "name": f"token-{repo_key}",
            "repo_key": repo_key,
            "scopes": scopes,
            "expires_in_days": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _approved_seg2d(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> tuple[dict, dict, dict]:
    dataset = prepare_dataset(client, admin_headers, "DR", "2d")
    task = create_task(client, admin_headers, "seg2d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]
    saved = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask",
        headers=annotator_headers,
        files={"file": ("mask.png", mask_bytes(64, 64), "image/png")},
    ).json()
    client.post(f"/api/annotations/{saved['id']}/submit", headers=annotator_headers)
    response = client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved", "comment": "通过"},
    )
    assert response.status_code == 200, response.text
    return dataset, task, case


def test_device_authorization_carries_repo_key_and_scopes(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    repo_key = unique("repo")
    code = client.post(
        "/api/auth/device/code",
        json={
            "client_name": "medpowers-pytest",
            "repo_key": repo_key,
            "scopes": ["studio:read", "studio:experiment"],
        },
    )
    assert code.status_code == 200, code.text
    body = code.json()
    approved = client.post(
        "/api/auth/device/approve",
        headers=admin_headers,
        json={"user_code": body["user_code"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["repo_key"] == repo_key
    token = client.post(
        "/api/auth/device/token", json={"device_code": body["device_code"]}
    )
    assert token.status_code == 200, token.text
    payload = token.json()
    assert payload["repo_key"] == repo_key
    assert "studio:experiment" in payload["scope"]
    context = client.get("/api/auth/context", headers=_bearer(payload["access_token"]))
    assert context.status_code == 200
    assert context.json()["repo_key"] == repo_key
    assert context.json()["capabilities"]["experiment"] is True


def test_token_cannot_write_annotations_or_admin(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset, task, case = _approved_seg2d(
        client, admin_headers, annotator_headers, reviewer_headers
    )
    token = _token(
        client,
        admin_headers,
        repo_key=unique("repo"),
        scopes=["studio:read", "studio:experiment"],
    )
    headers = _bearer(token)

    # token 不能写标注内容（即使拥有 experiment scope）
    response = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask",
        headers=headers,
        files={"file": ("mask.png", mask_bytes(64, 64), "image/png")},
    )
    assert response.status_code == 403, response.text

    # token 不能调用管理接口
    assert client.post("/api/tasks", headers=headers, json={}).status_code == 403
    assert client.get("/api/users", headers=headers).status_code == 403
    assert client.get("/api/admin/storage/usage", headers=headers).status_code == 403


def test_review_request_moves_approved_out_of_gold_pool(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    _, task, _ = _approved_seg2d(
        client, admin_headers, annotator_headers, reviewer_headers
    )
    token = _token(
        client,
        admin_headers,
        repo_key=unique("repo"),
        scopes=["studio:read", "studio:review-request"],
    )
    case_page = client.get(
        f"/api/tasks/{task['id']}/annotation-cases?status=approved", headers=admin_headers
    ).json()
    annotation_id = case_page["items"][0]["annotation_id"]

    response = client.post(
        f"/api/annotations/{annotation_id}/request-review",
        headers=_bearer(token),
        json={
            "reason": "评测显示该例边界可疑",
            "evidence": {"dice": 0.42, "eval_id": "eval-1"},
            "eval_id": "eval-1",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "review_requested"

    stats = client.get(f"/api/tasks/{task['id']}/stats", headers=admin_headers).json()
    assert stats["approved"] == 0
    assert stats["review_requested"] == 1

    queue = client.get(
        "/api/studio/review-requests?status=open", headers=admin_headers
    ).json()
    assert len(queue) == 1
    assert queue[0]["annotation_id"] == annotation_id
    assert queue[0]["repo_key"]
    assert queue[0]["evidence"]["dice"] == 0.42

    # 复核通过后回到 approved，申请记录关闭
    response = client.post(
        f"/api/annotations/{annotation_id}/review",
        headers=reviewer_headers,
        json={"decision": "approved", "comment": "复核无误"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert (
        client.get("/api/studio/review-requests?status=open", headers=admin_headers).json()
        == []
    )


def test_review_request_rejected_returns_to_in_progress(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    _, task, _ = _approved_seg2d(
        client, admin_headers, annotator_headers, reviewer_headers
    )
    token = _token(
        client,
        admin_headers,
        repo_key=unique("repo"),
        scopes=["studio:review-request"],
    )
    annotation_id = client.get(
        f"/api/tasks/{task['id']}/annotation-cases?status=approved", headers=admin_headers
    ).json()["items"][0]["annotation_id"]
    client.post(
        f"/api/annotations/{annotation_id}/request-review",
        headers=_bearer(token),
        json={"reason": "边界不一致"},
    )
    response = client.post(
        f"/api/annotations/{annotation_id}/review",
        headers=reviewer_headers,
        json={"decision": "rejected", "comment": "确认需修改"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "in_progress"


def test_experiment_metrics_and_external_evaluation_are_idempotent(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    task = create_task(client, admin_headers, "keyframe3d")
    token = _token(
        client,
        admin_headers,
        repo_key=unique("repo"),
        scopes=["studio:read", "studio:experiment", "studio:evaluate"],
    )
    headers = _bearer(token)
    exp_id = "EXP-001"

    payload = {
        "exp_id": exp_id,
        "task_code": task["code"],
        "status": "running",
        "title": "keyframe baseline",
        "machine": "机器A",
        "git_commit": "abc123",
        "config": {"lr": 1e-4, "amp": "bf16"},
    }
    response = client.post("/api/studio/experiments", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["repo_key"]
    assert response.json()["status"] == "running"

    points = {
        "points": [
            {"name": "train/loss", "value": 0.9, "step": 1, "split": "train"},
            {"name": "train/loss", "value": 0.8, "step": 2, "split": "train"},
            {
                "name": "val/dice",
                "value": 0.7,
                "step": 2,
                "split": "val",
                "class": "1",
            },
        ]
    }
    assert (
        client.post(
            f"/api/studio/experiments/{exp_id}/metrics:batch", headers=headers, json=points
        ).json()["accepted"]
        == 3
    )
    # 同键重推覆盖，不重复
    assert (
        client.post(
            f"/api/studio/experiments/{exp_id}/metrics:batch",
            headers=headers,
            json={
                "points": [
                    {"name": "train/loss", "value": 0.75, "step": 2, "split": "train"}
                ]
            },
        ).json()["accepted"]
        == 1
    )
    metrics = client.get(
        f"/api/studio/experiments/{exp_id}/metrics?name=train/loss", headers=headers
    ).json()
    assert len(metrics) == 2
    assert metrics[1]["value"] == 0.75

    evaluation = {
        "eval_id": "local-eval-001",
        "source": "external",
        "task_code": task["code"],
        "gt_statuses": ["approved"],
        "dataset_version": "dv-001",
        "summary": {"mean_dice": 0.88},
        "per_case": [{"case_uid": "case-1", "dice": 0.88}],
        "report_sha256": "deadbeef",
    }
    response = client.post(
        f"/api/studio/experiments/{exp_id}/evaluations", headers=headers, json=evaluation
    )
    assert response.status_code == 200, response.text
    assert response.json()["eval_id"] == "local-eval-001"
    # 重推同一 eval_id 覆盖
    evaluation["summary"] = {"mean_dice": 0.9}
    response = client.post(
        f"/api/studio/experiments/{exp_id}/evaluations", headers=headers, json=evaluation
    )
    assert response.status_code == 200, response.text
    evaluations = client.get(
        f"/api/studio/experiments/{exp_id}/evaluations", headers=headers
    ).json()
    assert len(evaluations) == 1
    assert evaluations[0]["summary"]["mean_dice"] == 0.9

    # 任务下实验列表
    listed = client.get(
        f"/api/studio/tasks/{task['code']}/experiments", headers=headers
    ).json()
    assert len(listed) == 1
    assert listed[0]["exp_id"] == exp_id

    changes = client.get(
        "/api/studio/changes?since=2000-01-01T00:00:00Z", headers=admin_headers
    )
    assert changes.status_code == 200, changes.text
    assert any(
        item["kind"] == "experiment" and item["exp_id"] == exp_id
        for item in changes.json()["items"]
    )


def test_scope_denials_and_repo_key_mismatch(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    task = create_task(client, admin_headers, "keyframe3d")
    read_only = _token(
        client, admin_headers, repo_key=unique("repo"), scopes=["studio:read"]
    )
    response = client.post(
        "/api/studio/experiments",
        headers=_bearer(read_only),
        json={"exp_id": "EXP-001", "task_code": task["code"]},
    )
    assert response.status_code == 403, response.text

    repo = unique("repo")
    experiment_token = _token(
        client,
        admin_headers,
        repo_key=repo,
        scopes=["studio:read", "studio:experiment"],
    )
    response = client.post(
        "/api/studio/experiments",
        headers=_bearer(experiment_token),
        json={"exp_id": "EXP-002", "task_code": task["code"], "repo_key": "other-repo"},
    )
    assert response.status_code == 403, response.text

    # 没有 review-request scope 不能申请复核
    response = client.post(
        "/api/annotations/not-exist/request-review",
        headers=_bearer(experiment_token),
        json={"reason": "test"},
    )
    assert response.status_code == 403, response.text


def test_task_readiness_exposes_contract_and_counts(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset, task, _ = _approved_seg2d(
        client, admin_headers, annotator_headers, reviewer_headers
    )
    contract = {
        "produced_by": "放射科医师 A，Slicer",
        "rule": "轴位最大层面勾画",
        "tolerance": "±1 层",
        "verified": True,
    }
    response = client.patch(
        f"/api/tasks/{task['id']}",
        headers=admin_headers,
        json={"annotation_contract": contract},
    )
    assert response.status_code == 200, response.text

    readiness = client.get(
        f"/api/studio/tasks/{task['code']}/readiness", headers=admin_headers
    ).json()
    assert readiness["total_cases"] == 1
    assert readiness["counts"]["approved"] == 1
    assert readiness["annotation_contract_complete"] is True
    assert readiness["annotation_contract"]["tolerance"] == "±1 层"
    assert len(readiness["datasets"]) == 1
    assert readiness["datasets"][0]["id"] == dataset["id"]
    assert readiness["class_case_counts"]["1"] == 1

    client.patch(
        f"/api/tasks/{task['id']}",
        headers=admin_headers,
        json={"annotation_contract": {**contract, "verified": False}},
    )
    readiness = client.get(
        f"/api/studio/tasks/{task['code']}/readiness", headers=admin_headers
    ).json()
    assert readiness["annotation_contract_complete"] is False

    meta = client.get("/api/studio/meta", headers=admin_headers).json()
    assert meta["capabilities"]["experiments"] is True
    assert meta["capabilities"]["native_evaluations"] is False
    assert meta["schema_version"]
