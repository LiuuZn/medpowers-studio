from __future__ import annotations

# API 访问令牌的权限范围（scope）。
# 插件/训练仓库拿到的 token 只应获得完成任务所需的最小权限。
SCOPE_READ = "studio:read"
SCOPE_DATA = "studio:data"
SCOPE_WRITE = "studio:write"
# 训练仓库/插件的最小权限：实验与指标镜像、评测结果、复核申请。
SCOPE_EXPERIMENT = "studio:experiment"
SCOPE_EVALUATE = "studio:evaluate"
SCOPE_REVIEW_REQUEST = "studio:review-request"
# 数据集接入：只增不删（新建/改属性/导入/标记就绪/新建扫描流程）。
SCOPE_DATASET_MANAGE = "studio:dataset-manage"

SCOPE_DEFINITIONS: dict[str, dict[str, str]] = {
    SCOPE_READ: {
        "name": "读取元数据",
        "description": "查看数据集、患者/检查/序列、任务、导出与评估等元数据。",
    },
    SCOPE_DATA: {
        "name": "下载影像与数据",
        "description": "下载导出包、切片 PNG 与标注掩码等二进制数据。",
    },
    SCOPE_WRITE: {
        "name": "通用写入（仅网页/管理端）",
        "description": "创建或修改数据集、任务、标注、导出与评估等；训练仓库 token 不应获得。",
    },
    SCOPE_EXPERIMENT: {
        "name": "实验与指标镜像",
        "description": "创建/更新实验镜像，批量推送训练指标与实验状态。",
    },
    SCOPE_EVALUATE: {
        "name": "评测结果",
        "description": "推送外部评测结果；后续 Studio 原生评测提交也使用该权限。",
    },
    SCOPE_REVIEW_REQUEST: {
        "name": "申请标注复核",
        "description": "把已通过标注转为待复核，提醒人工检查；不能修改标注内容。",
    },
    SCOPE_DATASET_MANAGE: {
        "name": "数据集管理（无删除）",
        "description": "新建数据集、修改数据集属性、导入病例并标记就绪，以及新建扫描流程；"
        "不能删除或归档数据集、不能修改或删除扫描流程。",
    },
}

ALL_SCOPES = tuple(SCOPE_DEFINITIONS)
DEFAULT_TOKEN_SCOPES = (SCOPE_READ,)
# 训练仓库默认建议：只读 + 下载 + 实验 + 评测；复核申请需显式追加。
TRAINING_TOKEN_SCOPES = (SCOPE_READ, SCOPE_DATA, SCOPE_EXPERIMENT, SCOPE_EVALUATE)
MAX_TOKEN_SCOPES = ALL_SCOPES


def normalize_scopes(raw: list[str] | tuple[str, ...] | None) -> list[str]:
    """校验并去重 scope；未知 scope 直接拒绝。"""

    if raw is None:
        return list(DEFAULT_TOKEN_SCOPES)
    scopes = sorted({str(item).strip() for item in raw if str(item).strip()})
    unknown = [item for item in scopes if item not in SCOPE_DEFINITIONS]
    if unknown:
        raise ValueError(f"未知权限：{', '.join(unknown)}")
    if not scopes:
        raise ValueError("至少需要选择一个权限")
    return scopes
