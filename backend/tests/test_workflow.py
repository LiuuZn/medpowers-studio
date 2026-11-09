from __future__ import annotations

import json
from pathlib import Path

import SimpleITK as sitk
from fastapi.testclient import TestClient

from .helpers import (
    TEST_ROOT,
    create_dataset,
    create_protocol,
    create_task,
    import_3d,
    link_dataset,
    make_volume_nrrd,
    mark_ready,
    mask_bytes,
    prepare_dataset,
    unique,
    zip_predictions,
)


def test_health_and_auth(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get("/api/health").status_code == 200
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code
        == 401
    )
    me = client.get("/api/auth/me", headers=admin_headers)
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_scan_protocol_scope_and_dataset_creation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    protocol = create_protocol(client, admin_headers, modality="CT")
    dataset = create_dataset(client, admin_headers, protocol["id"], modality="CT")
    assert dataset["dimension"] == "3d"
    assert dataset["scan_protocol"]["id"] == protocol["id"]

    # 模态不在扫描流程适用范围内
    response = client.post(
        "/api/datasets",
        headers=admin_headers,
        json={
            "code": unique("bad"),
            "name": "bad",
            "modality": "DR",
            "scan_protocol_id": protocol["id"],
        },
    )
    assert response.status_code == 400, response.text

    # 扫描流程必填
    response = client.post(
        "/api/datasets",
        headers=admin_headers,
        json={"code": unique("bad"), "name": "bad", "modality": "CT"},
    )
    assert response.status_code == 422

    # 已使用流程缩小适用范围要拒绝
    response = client.patch(
        f"/api/scan-protocols/{protocol['id']}",
        headers=admin_headers,
        json={"modality_scope": ["MR"]},
    )
    assert response.status_code == 400, response.text


def test_strict_dimension_matching(client: TestClient, admin_headers: dict[str, str]) -> None:
    ct_dataset = prepare_dataset(client, admin_headers, "CT", "3d")
    dr_dataset = prepare_dataset(client, admin_headers, "DR", "2d")

    seg2d = create_task(client, admin_headers, "seg2d")
    response = client.post(
        f"/api/tasks/{seg2d['id']}/datasets",
        headers=admin_headers,
        json={"dataset_id": ct_dataset["id"]},
    )
    assert response.status_code == 400, response.text
    link_dataset(client, admin_headers, seg2d["id"], dr_dataset["id"])

    seg3d = create_task(client, admin_headers, "seg3d")
    response = client.post(
        f"/api/tasks/{seg3d['id']}/datasets",
        headers=admin_headers,
        json={"dataset_id": dr_dataset["id"]},
    )
    assert response.status_code == 400, response.text
    link_dataset(client, admin_headers, seg3d["id"], ct_dataset["id"])
    response = client.post(
        f"/api/tasks/{seg3d['id']}/datasets",
        headers=admin_headers,
        json={"dataset_id": ct_dataset["id"]},
    )
    assert response.status_code == 409

    for task_type in ("keyframe3d", "det3d"):
        task = create_task(client, admin_headers, task_type)
        link_dataset(client, admin_headers, task["id"], ct_dataset["id"])


def test_dataset_import_dedup_and_pagination(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    protocol = create_protocol(client, admin_headers, modality="CT")
    dataset = create_dataset(client, admin_headers, protocol["id"], modality="CT")
    report = import_3d(client, admin_headers, dataset["id"], count=2)
    assert report["imported"] == 2
    assert sorted(report["cases"]) == ["volume_0", "volume_1"]

    report = import_3d(client, admin_headers, dataset["id"], count=2)
    assert report["imported"] == 2
    assert all(name.endswith("_2") for name in report["cases"])

    detail = client.get(f"/api/datasets/{dataset['id']}", headers=admin_headers).json()
    assert detail["case_count"] == 4
    page = client.get(
        f"/api/datasets/{dataset['id']}/cases?page=1&page_size=2", headers=admin_headers
    ).json()
    assert page["total"] == 4
    assert len(page["items"]) == 2


def test_nrrd_patient_study_series_hierarchy(
    client: TestClient, admin_headers: dict[str, str], annotator_headers: dict[str, str]
) -> None:
    protocol = create_protocol(client, admin_headers, modality="CT")
    dataset = create_dataset(client, admin_headers, protocol["id"], modality="CT")
    source = TEST_ROOT / "sources" / unique("hierarchy")
    make_volume_nrrd(
        source / "a.nrrd",
        patient_id="HIERARCHY-P1",
        study_uid="1.2.3.1",
        series_uid="1.2.3.1.1",
        series_description="序列 A",
        series_number=1,
    )
    make_volume_nrrd(
        source / "b.nrrd",
        patient_id="HIERARCHY-P1",
        study_uid="1.2.3.1",
        series_uid="1.2.3.1.2",
        series_description="序列 B",
        series_number=2,
    )
    make_volume_nrrd(
        source / "c.nrrd",
        patient_id="HIERARCHY-P2",
        study_uid="1.2.3.2",
        series_uid="1.2.3.2.1",
        series_number=1,
    )
    response = client.post(
        f"/api/datasets/{dataset['id']}/import-path",
        headers=admin_headers,
        json={"path": str(source), "acknowledge_source_discarded": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 3

    detail = client.get(f"/api/datasets/{dataset['id']}", headers=admin_headers).json()
    assert detail["case_count"] == 3
    assert detail["patient_count"] == 2
    assert detail["study_count"] == 2

    hierarchy = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy", headers=admin_headers
    ).json()
    assert hierarchy["total_patients"] == 2
    assert hierarchy["matched_patients"] == 2
    assert hierarchy["total_studies"] == 2
    assert hierarchy["total_series"] == 3
    assert hierarchy["unassigned_series"] == 0

    patient_one = next(item for item in hierarchy["items"] if item["series_count"] == 2)
    assert patient_one["study_count"] == 1
    assert patient_one["studies"][0]["study_uid"] == "1.2.3.1"
    assert patient_one["studies"][0]["series_count"] == 2
    assert {
        series["series_uid"] for series in patient_one["studies"][0]["series"]
    } == {"1.2.3.1.1", "1.2.3.1.2"}

    study_view = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy",
        headers=admin_headers,
        params={"level": "study"},
    ).json()
    assert study_view["level"] == "study"
    assert study_view["total"] == 2
    assert study_view["matched_studies"] == 2
    assert {item["study_uid"] for item in study_view["items"]} == {"1.2.3.1", "1.2.3.2"}
    assert all(item["node_type"] == "study" for item in study_view["items"])
    study_one = next(item for item in study_view["items"] if item["series_count"] == 2)
    assert study_one["patient_id"] == patient_one["patient_id"]
    assert {
        series["series_uid"] for series in study_one["series"]
    } == {"1.2.3.1.1", "1.2.3.1.2"}

    series_view = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy",
        headers=admin_headers,
        params={"level": "series"},
    ).json()
    assert series_view["level"] == "series"
    assert series_view["total"] == 3
    assert series_view["matched_series"] == 3
    assert all(
        item["node_type"] == "series" and item["patient_key"]
        for item in series_view["items"]
    )

    study_search = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy",
        headers=admin_headers,
        params={"level": "study", "search": "1.2.3.2"},
    ).json()
    assert study_search["total"] == 1
    assert study_search["items"][0]["study_uid"] == "1.2.3.2"

    series_search = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy",
        headers=admin_headers,
        params={"level": "series", "search": "1.2.3.2"},
    ).json()
    assert series_search["total"] == 1
    assert series_search["items"][0]["study_uid"] == "1.2.3.2"
    assert series_search["matched_patients"] == 1

    matched = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy",
        headers=admin_headers,
        params={"search": "1.2.3.2"},
    ).json()
    assert matched["matched_patients"] == 1
    assert matched["total_patients"] == 2

    cases = client.get(
        f"/api/datasets/{dataset['id']}/cases", headers=admin_headers
    ).json()["items"]
    assert all(case["series_uid"] for case in cases)
    assert all("patient_id" not in case["metadata_json"] for case in cases)
    assert all(case["metadata_json"].get("patient_key") for case in cases)

    mark_ready(client, admin_headers, dataset["id"])
    task = create_task(client, admin_headers, "keyframe3d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    summaries = client.get(
        f"/api/datasets/{dataset['id']}/tasks", headers=admin_headers
    ).json()
    assert len(summaries) == 1
    assert summaries[0]["task_id"] == task["id"]
    assert summaries[0]["total_series"] == 3
    assert summaries[0]["pending"] == 3

    case = cases[0]
    response = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}",
        headers=annotator_headers,
        json={"data": {"frames": [{"label_id": 1, "z_index": 1}]}},
    )
    assert response.status_code == 200, response.text

    summaries = client.get(
        f"/api/datasets/{dataset['id']}/tasks", headers=admin_headers
    ).json()
    assert summaries[0]["in_progress"] == 1
    assert summaries[0]["pending"] == 2

    task_hierarchy = client.get(
        f"/api/datasets/{dataset['id']}/hierarchy",
        headers=admin_headers,
        params={"task_id": task["id"]},
    ).json()
    statuses = [
        series["annotation_status"]
        for patient in task_hierarchy["items"]
        for study in patient["studies"]
        for series in study["series"]
    ]
    assert statuses.count("in_progress") == 1
    assert statuses.count("pending") == 2


def test_seg2d_annotation_submit_and_review(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset = prepare_dataset(client, admin_headers, "DR", "2d")
    task = create_task(client, admin_headers, "seg2d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]

    pending = client.get(
        f"/api/tasks/{task['id']}/annotation-cases?status=pending", headers=admin_headers
    ).json()
    assert pending["total"] == 1
    assert pending["items"][0]["status"] == "pending"

    annotation = client.get(
        f"/api/tasks/{task['id']}/annotations/{case['id']}", headers=admin_headers
    ).json()
    assert annotation["status"] == "pending"

    response = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask",
        headers=annotator_headers,
        files={"file": ("mask.png", mask_bytes(64, 64), "image/png")},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == "in_progress"
    assert saved["mask_available"] is True

    response = client.post(f"/api/annotations/{saved['id']}/submit", headers=annotator_headers)
    assert response.status_code == 200, response.text
    submitted = response.json()
    assert submitted["status"] == "submitted"
    assert submitted["version"] == 1

    # 标注员不能审核
    response = client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=annotator_headers,
        json={"decision": "approved"},
    )
    assert response.status_code == 403

    response = client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved", "comment": "通过"},
    )
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["reviewer"]["role"] == "reviewer"

    # 审核员不能直接编辑标注
    response = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask",
        headers=reviewer_headers,
        files={"file": ("mask.png", mask_bytes(64, 64), "image/png")},
    )
    assert response.status_code == 403

    # 管理员可以撤回
    response = client.post(f"/api/annotations/{saved['id']}/reopen", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    # 掩码切片接口可读
    response = client.get(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask-slice?index=0",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")


def test_seg3d_mask_assembly_and_validation(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset = prepare_dataset(client, admin_headers, "CT", "3d")
    task = create_task(client, admin_headers, "seg3d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]

    # 尺寸不匹配应拒绝
    response = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask-slice?index=0",
        headers=annotator_headers,
        files={"file": ("mask.png", mask_bytes(16, 16), "image/png")},
    )
    assert response.status_code == 400

    # 未定义类别应拒绝
    response = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask-slice?index=0",
        headers=annotator_headers,
        files={"file": ("mask.png", mask_bytes(32, 32, label=9), "image/png")},
    )
    assert response.status_code == 400

    annotation_id = None
    for index in (2, 3):
        response = client.put(
            f"/api/tasks/{task['id']}/annotations/{case['id']}/mask-slice?index={index}",
            headers=annotator_headers,
            files={"file": ("mask.png", mask_bytes(32, 32), "image/png")},
        )
        assert response.status_code == 200, response.text
        annotation_id = response.json()["id"]
    assert annotation_id

    response = client.post(f"/api/annotations/{annotation_id}/submit", headers=annotator_headers)
    assert response.status_code == 200, response.text
    submitted = response.json()
    assert submitted["status"] == "submitted"
    assert submitted["data"]["nonempty_slices"] == 2
    assert submitted["data"]["foreground_voxels"] > 0

    response = client.post(
        f"/api/annotations/{annotation_id}/review",
        headers=reviewer_headers,
        json={"decision": "approved"},
    )
    assert response.status_code == 200

    response = client.get(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask", headers=admin_headers
    )
    assert response.status_code == 200
    mask_path = Path("/tmp") / f"{unique('mask')}.nrrd"
    mask_path.write_bytes(response.content)
    image = sitk.ReadImage(str(mask_path))
    assert image.GetSize() == (32, 32, 8)
    array = sitk.GetArrayFromImage(image)
    assert array.shape == (8, 32, 32)
    assert array[2].any() and array[3].any()


def test_keyframe_and_det3d_annotations(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset = prepare_dataset(client, admin_headers, "CT", "3d")
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]

    keyframe_task = create_task(client, admin_headers, "keyframe3d")
    link_dataset(client, admin_headers, keyframe_task["id"], dataset["id"])
    response = client.put(
        f"/api/tasks/{keyframe_task['id']}/annotations/{case['id']}",
        headers=annotator_headers,
        json={"data": {"frames": [{"label_id": 1, "z_index": 3}]}},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["data"]["frames"][0]["z_index"] == 3
    response = client.post(f"/api/annotations/{saved['id']}/submit", headers=annotator_headers)
    assert response.status_code == 200
    response = client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved"},
    )
    assert response.status_code == 200

    det_task = create_task(client, admin_headers, "det3d")
    link_dataset(client, admin_headers, det_task["id"], dataset["id"])
    response = client.put(
        f"/api/tasks/{det_task['id']}/annotations/{case['id']}",
        headers=annotator_headers,
        json={
            "data": {
                "boxes": [
                    {
                        "label_id": 1,
                        "center_voxel": [16, 16, 4],
                        "size_voxel": [8, 8, 2],
                    }
                ]
            }
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    box = saved["data"]["boxes"][0]
    assert "center_world" in box and "size_world" in box
    assert len(box["center_world"]) == 3
    response = client.post(f"/api/annotations/{saved['id']}/submit", headers=annotator_headers)
    assert response.status_code == 200
    response = client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved"},
    )
    assert response.status_code == 200


def test_export_2d_nnunet_and_download(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
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
    client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved"},
    )

    response = client.post(
        "/api/exports",
        headers=admin_headers,
        json={
            "name": "seg2d 导出",
            "task_id": task["id"],
            "dataset_ids": [dataset["id"]],
            "format": "nnunet",
            "split_config": {"train": 0.7, "val": 0.15, "test": 0.15, "seed": 7},
            "include_statuses": ["approved"],
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "succeeded", job
    output = Path(job["output_dir"])
    assert (output / "dataset.json").exists()
    assert (output / "splits.json").exists()
    assert (output / "manifest.json").exists()
    assert list((output / "imagesTr").glob("*.png"))
    assert list((output / "labelsTr").glob("*.png"))
    assert job["summary"]["exported_cases"] == 1

    response = client.get(f"/api/exports/{job['id']}/download", headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    response = client.post(
        "/api/exports",
        headers=admin_headers,
        json={
            "name": "空导出",
            "task_id": task["id"],
            "dataset_ids": [dataset["id"]],
            "include_statuses": ["submitted"],
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert "没有符合状态要求" in response.json()["error"]


def test_export_3d_nnunet(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset = prepare_dataset(client, admin_headers, "CT", "3d")
    task = create_task(client, admin_headers, "seg3d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]
    saved = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask-slice?index=2",
        headers=annotator_headers,
        files={"file": ("mask.png", mask_bytes(32, 32), "image/png")},
    ).json()
    client.post(f"/api/annotations/{saved['id']}/submit", headers=annotator_headers)
    client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved"},
    )

    response = client.post(
        "/api/exports",
        headers=admin_headers,
        json={
            "name": "seg3d 导出",
            "task_id": task["id"],
            "dataset_ids": [dataset["id"]],
            "include_statuses": ["approved"],
        },
    )
    job = response.json()
    assert job["status"] == "succeeded", job
    output = Path(job["output_dir"])
    assert list((output / "imagesTr").glob("*_0000.nrrd"))
    assert list((output / "labelsTr").glob("*.nrrd"))
    dataset_json = json.loads((output / "dataset.json").read_text())
    assert dataset_json["file_ending"] == ".nrrd"
    assert dataset_json["numTraining"] == 1


def test_evaluation_seg2d(
    client: TestClient,
    admin_headers: dict[str, str],
    annotator_headers: dict[str, str],
    reviewer_headers: dict[str, str],
) -> None:
    dataset = prepare_dataset(client, admin_headers, "DR", "2d")
    task = create_task(client, admin_headers, "seg2d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]
    mask = mask_bytes(64, 64)
    saved = client.put(
        f"/api/tasks/{task['id']}/annotations/{case['id']}/mask",
        headers=annotator_headers,
        files={"file": ("mask.png", mask, "image/png")},
    ).json()
    client.post(f"/api/annotations/{saved['id']}/submit", headers=annotator_headers)
    client.post(
        f"/api/annotations/{saved['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved"},
    )

    prediction_zip = zip_predictions({f"{case['case_uid']}.png": mask})
    response = client.post(
        "/api/evaluations",
        headers=admin_headers,
        data={
            "name": "seg2d 评估",
            "task_id": task["id"],
            "dataset_ids": json.dumps([dataset["id"]]),
            "gt_statuses": json.dumps(["approved"]),
            "metrics_config": json.dumps({"include_background": False}),
        },
        files={"file": ("pred.zip", prediction_zip, "application/zip")},
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "succeeded", job
    assert job["summary"]["mean_dice"] == 1.0
    assert job["summary"]["classes"]["1"]["dice"]["mean"] == 1.0

    response = client.get(f"/api/evaluations/{job['id']}/report", headers=admin_headers)
    assert response.status_code == 200
    report = response.json()
    assert report["per_case"][0]["classes"]["1"]["dice"] == 1.0

    # 缺少预测文件时作业失败
    response = client.post(
        "/api/evaluations",
        headers=admin_headers,
        data={
            "name": "空评估",
            "task_id": task["id"],
            "dataset_ids": json.dumps([dataset["id"]]),
            "gt_statuses": json.dumps(["approved"]),
            "metrics_config": json.dumps({}),
        },
        files={"file": ("pred.zip", zip_predictions({}), "application/zip")},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"


def test_dashboard(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/dashboard", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["datasets"] >= 1
    assert "annotations" in data
    assert isinstance(data["task_progress"], list)


def test_slice_info_modality_and_task_stats(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    dataset = prepare_dataset(client, admin_headers, "CT", "3d")
    task = create_task(client, admin_headers, "seg3d")
    link_dataset(client, admin_headers, task["id"], dataset["id"])
    case = client.get(f"/api/datasets/{dataset['id']}/cases", headers=admin_headers).json()[
        "items"
    ][0]

    info = client.get(f"/api/cases/{case['id']}/slice-info", headers=admin_headers)
    assert info.status_code == 200, info.text
    payload = info.json()
    assert payload["modality"] == "CT"
    assert payload["dimension"] == "3d"
    assert payload["slices"] > 1
    assert payload["axes"] == ["axial", "coronal", "sagittal"]

    image = client.get(f"/api/cases/{case['id']}/slice?axis=coronal&index=0", headers=admin_headers)
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")

    stats = client.get(f"/api/tasks/{task['id']}/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["total_cases"] == 1
    assert stats.json()["pending"] == 1
