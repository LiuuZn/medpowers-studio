"""生成一套可交互的演示数据。

用法（在 backend 目录）：
    uv run python scripts/seed_demo.py

脚本通过平台 API 创建数据，幂等性按编码判断：已存在的数据集/任务/用户会复用。
默认管理员账号来自 MEDPOWERS_BOOTSTRAP_ADMIN_USERNAME / PASSWORD。
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

settings = get_settings()
DEMO_USERS = [
    {
        "username": "annotator1",
        "password": "pass1234",
        "display_name": "演示标注员",
        "role": "annotator",
    },
    {
        "username": "reviewer1",
        "password": "pass1234",
        "display_name": "演示审核员",
        "role": "reviewer",
    },
]


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    if response.status_code != 200:
        raise SystemExit(
            f"登录失败：{username} / {password}。"
            "请确认管理员密码或先删除 backend/medpowers_studio.db 重新初始化。"
        )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def ensure_protocol(client, headers, code, name, modalities):
    items = client.get("/api/scan-protocols?include_inactive=true", headers=headers).json()
    for item in items:
        if item["code"] == code:
            return item
    response = client.post(
        "/api/scan-protocols",
        headers=headers,
        json={"code": code, "name": name, "modality_scope": modalities},
    )
    response.raise_for_status()
    return response.json()


def ensure_dataset(client, headers, code, name, modality, protocol_id):
    items = client.get("/api/datasets", headers=headers, params={"search": code}).json()
    for item in items:
        if item["code"] == code:
            return item
    response = client.post(
        "/api/datasets",
        headers=headers,
        json={
            "code": code,
            "name": name,
            "modality": modality,
            "scan_protocol_id": protocol_id,
            "description": "演示数据集，由 scripts/seed_demo.py 生成",
        },
    )
    response.raise_for_status()
    return response.json()


def ensure_task(client, headers, code, name, task_type):
    items = client.get("/api/tasks", headers=headers, params={"search": code}).json()
    for item in items:
        if item["code"] == code:
            return item
    response = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "code": code,
            "name": name,
            "task_type": task_type,
            "description": "演示任务，由 scripts/seed_demo.py 生成",
            "annotation_guide": (
                "按影像中的高信号区域勾画；三维分割逐层勾画，"
                "检测框覆盖病灶完整范围。"
            ),
        },
    )
    response.raise_for_status()
    return response.json()


def ensure_linked(client, headers, task_id, dataset_id):
    links = client.get(f"/api/tasks/{task_id}/datasets", headers=headers).json()
    if any(item["dataset"]["id"] == dataset_id for item in links):
        return
    response = client.post(
        f"/api/tasks/{task_id}/datasets",
        headers=headers,
        json={"dataset_id": dataset_id},
    )
    response.raise_for_status()


def ensure_user(client, headers, payload):
    users = client.get("/api/users", headers=headers).json()
    if any(item["username"] == payload["username"] for item in users):
        return
    response = client.post("/api/users", headers=headers, json=payload)
    response.raise_for_status()


def make_volume(
    path: Path,
    z: int,
    y: int,
    x: int,
    offset: float = 0.0,
    *,
    patient_id: str | None = None,
    study_uid: str | None = None,
    series_uid: str | None = None,
    study_description: str = "演示检查",
    series_description: str = "演示序列",
    series_number: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((z, y, x), dtype=np.int16)
    zz, yy, xx = np.ogrid[:z, :y, :x]
    center = (z / 2 + offset, y / 2, x / 2)
    radius = min(z, y, x) / 4
    mask = (
        ((zz - center[0]) ** 2) / max(radius, 1) ** 2
        + ((yy - center[1]) ** 2) / max(radius, 1) ** 2
        + ((xx - center[2]) ** 2) / max(radius, 1) ** 2
    ) <= 1
    array[mask] = 900
    array += np.random.default_rng(int(offset * 100) + 7).integers(
        0, 40, size=array.shape, dtype=np.int16
    )
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((1.2, 1.2, 2.0))
    image.SetOrigin((-50.0, -60.0, 10.0))
    if patient_id:
        image.SetMetaData("PatientID", patient_id)
        image.SetMetaData("PatientSex", "M" if offset % 2 == 0 else "F")
        image.SetMetaData("PatientAge", "055Y")
    if study_uid:
        image.SetMetaData("StudyInstanceUID", study_uid)
        image.SetMetaData("StudyDescription", study_description)
        image.SetMetaData("StudyDate", "20260101")
        image.SetMetaData("AccessionNumber", f"ACC{int(offset):04d}")
    if series_uid:
        image.SetMetaData("SeriesInstanceUID", series_uid)
        image.SetMetaData("SeriesDescription", series_description)
        image.SetMetaData("SeriesNumber", str(series_number))
    sitk.WriteImage(image, str(path), True)


def make_2d(path: Path, size: int = 128, variant: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    yy, xx = np.ogrid[:size, :size]
    cx = size / 2 + (variant - 1) * 8
    cy = size / 2
    radius = size / 4
    circle = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
    array = np.full((size, size), 30, dtype=np.uint8)
    array[circle] = 190
    Image.fromarray(array).save(path)


def png_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array.astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def circle_mask(width: int, height: int) -> bytes:
    yy, xx = np.ogrid[:height, :width]
    circle = (xx - width / 2) ** 2 + (yy - height / 2) ** 2 <= (min(width, height) / 5) ** 2
    return png_bytes(circle.astype(np.uint8))


def seed_annotations(client, admin, annotator, reviewer, task, dataset):
    cases = client.get(
        f"/api/datasets/{dataset['id']}/cases", headers=admin, params={"page_size": 200}
    ).json()
    task_type = task["task_type"]
    for case in cases["items"]:
        current = client.get(
            f"/api/tasks/{task['id']}/annotations/{case['id']}", headers=admin
        ).json()
        if current["status"] in ("approved", "submitted"):
            continue
        if task_type == "seg2d":
            response = client.put(
                f"/api/tasks/{task['id']}/annotations/{case['id']}/mask",
                headers=annotator,
                files={"file": ("mask.png", circle_mask(128, 128), "image/png")},
            )
        elif task_type == "seg3d":
            response = None
            slices = 16
            for z in range(2, slices - 2):
                response = client.put(
                    f"/api/tasks/{task['id']}/annotations/{case['id']}/mask-slice?index={z}",
                    headers=annotator,
                    files={"file": ("slice.png", circle_mask(64, 64), "image/png")},
                )
                response.raise_for_status()
        elif task_type == "keyframe3d":
            response = client.put(
                f"/api/tasks/{task['id']}/annotations/{case['id']}",
                headers=annotator,
                json={"data": {"frames": [{"label_id": 1, "z_index": 8}]}},
            )
        else:
            response = client.put(
                f"/api/tasks/{task['id']}/annotations/{case['id']}",
                headers=annotator,
                json={
                    "data": {
                        "boxes": [
                            {
                                "label_id": 1,
                                "center_voxel": [32, 32, 8],
                                "size_voxel": [18, 18, 6],
                            }
                        ]
                    }
                },
            )
        if response is None:
            continue
        response.raise_for_status()
        annotation = response.json()
        if not annotation.get("id"):
            continue
        submitted = client.post(f"/api/annotations/{annotation['id']}/submit", headers=annotator)
        submitted.raise_for_status()
        reviewed = client.post(
            f"/api/annotations/{annotation['id']}/review",
            headers=reviewer,
            json={"decision": "approved", "comment": "演示数据自动审核通过"},
        )
        reviewed.raise_for_status()


def seed_export(client, headers, task, dataset):
    jobs = client.get("/api/exports", headers=headers, params={"task_id": task["id"]}).json()
    if any(job["name"].startswith("演示导出") for job in jobs):
        return
    response = client.post(
        "/api/exports",
        headers=headers,
        json={
            "name": f"演示导出 · {task['name']}",
            "task_id": task["id"],
            "dataset_ids": [dataset["id"]],
            "include_statuses": ["approved"],
            "split_config": {
                "train": 0.7,
                "val": 0.15,
                "test": 0.15,
                "seed": 42,
                "patient_level": True,
            },
        },
    )
    response.raise_for_status()
    job = response.json()
    print(f"  导出作业：{job['status']}，病例 {job['summary'].get('exported_cases', 0)}")


def seed_evaluation(client, headers, task, dataset):
    jobs = client.get("/api/evaluations", headers=headers, params={"task_id": task["id"]}).json()
    if any(job["name"].startswith("演示评估") for job in jobs):
        return
    cases = client.get(
        f"/api/datasets/{dataset['id']}/cases", headers=headers, params={"page_size": 200}
    ).json()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for case in cases["items"]:
            annotation = client.get(
                f"/api/tasks/{task['id']}/annotations/{case['id']}", headers=headers
            ).json()
            if annotation["status"] != "approved":
                continue
            mask = client.get(
                f"/api/tasks/{task['id']}/annotations/{case['id']}/mask", headers=headers
            )
            if mask.status_code != 200:
                continue
            archive.writestr(f"{case['case_uid']}.png", mask.content)
    if not buffer.getvalue():
        return
    response = client.post(
        "/api/evaluations",
        headers=headers,
        data={
            "name": f"演示评估 · {task['name']}",
            "task_id": task["id"],
            "dataset_ids": json.dumps([dataset["id"]]),
            "gt_statuses": json.dumps(["approved"]),
            "metrics_config": json.dumps({"include_background": False}),
        },
        files={"file": ("predictions.zip", buffer.getvalue(), "application/zip")},
    )
    response.raise_for_status()
    job = response.json()
    print(f"  评估作业：{job['status']}，平均 Dice {job['summary'].get('mean_dice')}")


def main() -> None:
    print(f"数据库：{settings.database_url}")
    print(f"存储根目录：{settings.storage_root}")
    source_root = settings.storage_root / "tmp" / "seed_sources"
    shutil.rmtree(source_root, ignore_errors=True)
    source_root.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as client:
        admin = login(
            client,
            settings.bootstrap_admin_username,
            settings.bootstrap_admin_password,
        )
        for user in DEMO_USERS:
            ensure_user(client, admin, user)
        annotator = login(client, "annotator1", "pass1234")
        reviewer = login(client, "reviewer1", "pass1234")

        ct_protocol = ensure_protocol(client, admin, "CT_ROUTINE", "CT 平扫", ["CT"])
        mr_protocol = ensure_protocol(client, admin, "MR_T1", "MR T1WI", ["MR"])
        dr_protocol = ensure_protocol(client, admin, "DR_AP", "DR 正位", ["DR"])

        ct_dataset = ensure_dataset(
            client, admin, "demo_ct_chest", "演示胸部 CT", "CT", ct_protocol["id"]
        )
        mr_dataset = ensure_dataset(
            client, admin, "demo_mr_brain", "演示头颅 MR", "MR", mr_protocol["id"]
        )
        dr_dataset = ensure_dataset(
            client, admin, "demo_dr_chest", "演示胸部 DR", "DR", dr_protocol["id"]
        )

        if ct_dataset["case_count"] == 0:
            source = source_root / "ct"
            ct_cases = [
                ("DEMO_CT_001", "1.2.826.0.1.3680043.10.100.1", ".1", 1),
                ("DEMO_CT_001", "1.2.826.0.1.3680043.10.100.1", ".2", 2),
                ("DEMO_CT_002", "1.2.826.0.1.3680043.10.100.2", ".1", 1),
            ]
            for index, (patient_id, study_uid, series_suffix, series_number) in enumerate(
                ct_cases
            ):
                make_volume(
                    source / f"ct_case_{index:02d}.nrrd",
                    16,
                    64,
                    64,
                    offset=index,
                    patient_id=patient_id,
                    study_uid=study_uid,
                    series_uid=f"{study_uid}{series_suffix}",
                    study_description="演示胸部 CT 检查",
                    series_description=f"胸部 CT 序列 {series_number}",
                    series_number=series_number,
                )
            response = client.post(
                f"/api/datasets/{ct_dataset['id']}/import-path",
                headers=admin,
                json={"path": str(source), "acknowledge_source_discarded": True},
            )
            response.raise_for_status()
            print(f"  CT 导入：{response.json()['imported']} 例")
        if mr_dataset["case_count"] == 0:
            source = source_root / "mr"
            for index in range(2):
                study_uid = f"1.2.826.0.1.3680043.10.200.{index + 1}"
                make_volume(
                    source / f"mr_case_{index:02d}.nrrd",
                    12,
                    64,
                    64,
                    offset=index + 2,
                    patient_id=f"DEMO_MR_{index + 1:03d}",
                    study_uid=study_uid,
                    series_uid=f"{study_uid}.1",
                    study_description="演示头颅 MR 检查",
                    series_description="T1WI 序列",
                    series_number=1,
                )
            response = client.post(
                f"/api/datasets/{mr_dataset['id']}/import-path",
                headers=admin,
                json={"path": str(source), "acknowledge_source_discarded": True},
            )
            response.raise_for_status()
            print(f"  MR 导入：{response.json()['imported']} 例")
        if dr_dataset["case_count"] == 0:
            source = source_root / "dr"
            for index in range(4):
                make_2d(source / f"dr_case_{index:02d}.png", variant=index % 3)
            response = client.post(
                f"/api/datasets/{dr_dataset['id']}/import-path",
                headers=admin,
                json={"path": str(source), "acknowledge_source_discarded": True},
            )
            response.raise_for_status()
            print(f"  DR 导入：{response.json()['imported']} 例")

        for dataset in (ct_dataset, mr_dataset, dr_dataset):
            current = client.get(f"/api/datasets/{dataset['id']}", headers=admin).json()
            if current["status"] != "ready":
                response = client.post(f"/api/datasets/{dataset['id']}/ready", headers=admin)
                response.raise_for_status()

        seg3d = ensure_task(client, admin, "demo_lung_seg3d", "演示肺结节三维分割", "seg3d")
        det3d = ensure_task(client, admin, "demo_lesion_det3d", "演示病灶三维检测", "det3d")
        keyframe = ensure_task(client, admin, "demo_keyframe3d", "演示关键帧选择", "keyframe3d")
        seg2d = ensure_task(client, admin, "demo_chest_seg2d", "演示胸部 DR 分割", "seg2d")

        ensure_linked(client, admin, seg3d["id"], ct_dataset["id"])
        ensure_linked(client, admin, det3d["id"], ct_dataset["id"])
        ensure_linked(client, admin, keyframe["id"], mr_dataset["id"])
        ensure_linked(client, admin, seg2d["id"], dr_dataset["id"])

        print("生成演示标注...")
        for task, dataset in (
            (seg3d, ct_dataset),
            (det3d, ct_dataset),
            (keyframe, mr_dataset),
            (seg2d, dr_dataset),
        ):
            seed_annotations(client, admin, annotator, reviewer, task, dataset)

        print("生成演示导出与评估...")
        seed_export(client, admin, seg3d, ct_dataset)
        seed_evaluation(client, admin, seg2d, dr_dataset)

    print("演示数据已就绪。启动后端与前端后，使用 admin / 初始密码登录查看。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
