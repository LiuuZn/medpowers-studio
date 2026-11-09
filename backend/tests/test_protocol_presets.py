from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.protocol_presets import (
    PRESET_SCAN_PROTOCOLS,
    suggest_preset_code,
)

from .helpers import create_dataset, create_protocol, unique


def _list_protocols(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get("/api/scan-protocols", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_preset_protocols_seeded_on_startup(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """启动补种后，全部预置流程都在字典中且字段与清单一致。"""

    items = {item["code"]: item for item in _list_protocols(client, admin_headers)}
    for preset in PRESET_SCAN_PROTOCOLS:
        item = items[preset.code]
        assert item["name"] == preset.name
        assert item["description"] == preset.description
        assert item["modality_scope"] == list(preset.modality_scope)
        assert item["sort_order"] == preset.sort_order
        assert item["is_active"] is True


def test_preset_protocol_usable_for_dataset(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """数据集可以直接绑定预置流程（如 head_ct 头部 CT 扫描）。"""

    items = {item["code"]: item for item in _list_protocols(client, admin_headers)}
    dataset = create_dataset(client, admin_headers, items["head_ct"]["id"], modality="CT")
    assert dataset["scan_protocol"]["code"] == "head_ct"
    assert dataset["scan_protocol"]["name"] == "头部 CT 扫描"

    # 预置流程的模态约束照常生效：DR 数据集不能绑 CT 预置流程
    response = client.post(
        "/api/datasets",
        headers=admin_headers,
        json={
            "code": unique("dataset"),
            "name": "bad",
            "modality": "DR",
            "scan_protocol_id": items["chest_ct"]["id"],
        },
    )
    assert response.status_code == 400, response.text


def test_custom_protocol_still_allowed(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """保留定制空间：管理员仍可新建自定义流程并绑定数据集。"""

    protocol = create_protocol(client, admin_headers, modality="MR")
    dataset = create_dataset(client, admin_headers, protocol["id"], modality="MR")
    assert dataset["scan_protocol"]["id"] == protocol["id"]


def test_suggest_preset_code_by_name_keywords() -> None:
    """存量数据改绑的模糊匹配：部位关键词命中 + 模态兼容。"""

    assert suggest_preset_code("IDC 开源 CT — cmb_crc（头部）", "CT") == "head_ct"
    assert suggest_preset_code("IDC 开源 CT — nlst（胸部）", "CT") == "chest_ct"
    assert suggest_preset_code("演示腹部 MR 数据集", "MR") == "abdomen_mr"
    assert suggest_preset_code("腰椎间盘突出 MR", "MR") == "lumbar_spine_mr"
    # 「颈椎」先于「颈部」规则命中
    assert suggest_preset_code("颈椎骨折 CT", "CT") == "cervical_spine_ct"
    assert suggest_preset_code("颈部淋巴结 CT", "CT") == "neck_ct"
    # 部位命中但模态不兼容 -> None（保持原流程）
    assert suggest_preset_code("IDC 开源 CT — 4d_lung（胸部）", "MR") is None
    # 无部位关键词 -> None
    assert suggest_preset_code("多部位数据集", "CT") is None
    # 表格数据集不在影像规则内
    assert suggest_preset_code("临床表格导入", "TABLE") is None
