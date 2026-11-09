"""预置扫描流程清单。

系统初始化（应用启动）时按 code 幂等补种进 scan_protocols 字典：
只创建缺失项，不覆盖管理员对已有流程的修改（改名/停用等）。
数据集接入时应优先绑定这里的预置流程；均不适用时管理员再自定义新建，
命名建议沿用「部位 + 模态 + 扫描」，编码用小写英文/数字/下划线。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetScanProtocol:
    code: str
    name: str
    description: str
    modality_scope: tuple[str, ...]  # 为空表示适用全部模态（预置流程均显式指定）
    sort_order: int  # 按部位分组，十位递增；字典按其排序展示
    region: str  # 部位分组键，供存量数据改绑的模糊匹配使用


PRESET_SCAN_PROTOCOLS: tuple[PresetScanProtocol, ...] = (
    # ---- 头颈与神经（10+）----
    PresetScanProtocol("head_ct", "头部 CT 扫描", "颅脑病变筛查：外伤、卒中、肿瘤等", ("CT",), 10, "head"),
    PresetScanProtocol("head_mr", "头部 MR 扫描", "颅脑实质、占位与血管性病变评估", ("MR",), 11, "head"),
    PresetScanProtocol("pituitary_mr", "垂体 MR 扫描", "鞍区动态增强，垂体微腺瘤等", ("MR",), 12, "pituitary"),
    PresetScanProtocol("orbit_ct", "眼眶 CT 扫描", "眼眶骨折、异物、眶内肿瘤", ("CT",), 13, "orbit"),
    PresetScanProtocol("temporal_bone_ct", "颞骨 CT 扫描", "中耳乳突炎、听骨链及颞骨骨折", ("CT",), 14, "temporal_bone"),
    PresetScanProtocol("paranasal_sinus_ct", "鼻窦 CT 扫描", "鼻窦炎症、肿瘤及解剖变异", ("CT",), 15, "paranasal_sinus"),
    PresetScanProtocol("nasopharynx_mr", "鼻咽部 MR 扫描", "鼻咽癌诊断与分期", ("MR",), 16, "nasopharynx"),
    PresetScanProtocol("neck_ct", "颈部 CT 扫描", "颈部肿物、淋巴结与喉部病变", ("CT",), 17, "neck"),
    PresetScanProtocol("neck_mr", "颈部 MR 扫描", "颈部软组织、咽旁间隙病变", ("MR",), 18, "neck"),
    PresetScanProtocol("thyroid_ct", "甲状腺 CT 扫描", "甲状腺结节与胸骨后甲状腺肿", ("CT",), 19, "thyroid"),
    # ---- 胸部（20+）----
    PresetScanProtocol("chest_ct", "胸部 CT 扫描", "肺、纵隔、胸膜与胸壁病变常规评估", ("CT",), 20, "chest"),
    PresetScanProtocol("chest_low_dose_ct", "低剂量胸部 CT 扫描", "肺癌筛查（LDCT）", ("CT",), 21, "chest"),
    PresetScanProtocol("chest_hrct", "胸部高分辨 CT 扫描", "间质性肺病、支气管扩张等肺实质细节", ("CT",), 22, "chest"),
    PresetScanProtocol("chest_dr", "胸部 DR 扫描", "胸片常规：肺纹理、心影、肋骨初筛", ("DR",), 23, "chest"),
    PresetScanProtocol("breast_mr", "乳腺 MR 扫描", "乳腺增强检查，致密型乳腺评估", ("MR",), 24, "breast"),
    # ---- 腹部（30+）----
    PresetScanProtocol("abdomen_ct", "腹部 CT 扫描", "肝胆胰脾肾及胃肠道常规评估", ("CT",), 30, "abdomen"),
    PresetScanProtocol("abdomen_mr", "腹部 MR 扫描", "腹盆腔脏器常规 MR 评估", ("MR",), 31, "abdomen"),
    PresetScanProtocol("liver_mr", "肝脏 MR 扫描", "肝脏局灶病变定性（增强）", ("MR",), 32, "liver"),
    PresetScanProtocol("mrcp_mr", "胰胆管 MR 扫描（MRCP）", "胆胰管水成像：结石、狭窄、扩张", ("MR",), 33, "mrcp"),
    PresetScanProtocol("ctu_ct", "泌尿系 CT 扫描（CTU）", "泌尿系全程：结石、肿瘤、畸形", ("CT",), 34, "ctu"),
    PresetScanProtocol("adrenal_ct", "肾上腺 CT 扫描", "肾上腺结节与增生", ("CT",), 35, "adrenal"),
    # ---- 盆腔（40+）----
    PresetScanProtocol("pelvis_ct", "盆腔 CT 扫描", "膀胱、直肠及盆壁病变评估", ("CT",), 40, "pelvis"),
    PresetScanProtocol("pelvis_mr", "盆腔 MR 扫描", "盆腔软组织常规评估", ("MR",), 41, "pelvis"),
    PresetScanProtocol("prostate_mr", "前列腺 MR 扫描", "前列腺癌检出与分期（PI-RADS）", ("MR",), 42, "prostate"),
    PresetScanProtocol("uterus_mr", "子宫附件 MR 扫描", "子宫肌瘤、腺肌症与附件肿物", ("MR",), 43, "uterus"),
    PresetScanProtocol("rectum_mr", "直肠 MR 扫描", "直肠癌术前分期", ("MR",), 44, "rectum"),
    # ---- 脊柱（50+）----
    PresetScanProtocol("cervical_spine_ct", "颈椎 CT 扫描", "颈椎骨折、椎体骨质病变", ("CT",), 50, "cervical_spine"),
    PresetScanProtocol("cervical_spine_mr", "颈椎 MR 扫描", "颈椎间盘、脊髓与神经根评估", ("MR",), 51, "cervical_spine"),
    PresetScanProtocol("thoracic_spine_ct", "胸椎 CT 扫描", "胸椎骨折与骨质病变", ("CT",), 52, "thoracic_spine"),
    PresetScanProtocol("thoracic_spine_mr", "胸椎 MR 扫描", "胸椎间盘、脊髓与椎旁评估", ("MR",), 53, "thoracic_spine"),
    PresetScanProtocol("lumbar_spine_ct", "腰椎 CT 扫描", "腰椎骨折、椎体骨质病变", ("CT",), 54, "lumbar_spine"),
    PresetScanProtocol("lumbar_spine_mr", "腰椎 MR 扫描", "腰椎间盘突出、椎管狭窄评估", ("MR",), 55, "lumbar_spine"),
    PresetScanProtocol("sacroiliac_mr", "骶髂关节 MR 扫描", "骶髂关节炎（脊柱关节炎）早期评估", ("MR",), 56, "sacroiliac"),
    # ---- 四肢关节（60+）----
    PresetScanProtocol("limb_dr", "四肢 DR 扫描", "长骨与关节外伤、退变初筛", ("DR",), 60, "limb"),
    PresetScanProtocol("joint_ct", "关节 CT 扫描", "骨折累及关节面、三维重建", ("CT",), 61, "joint"),
    PresetScanProtocol("shoulder_mr", "肩关节 MR 扫描", "肩袖损伤、盂唇病变", ("MR",), 62, "shoulder"),
    PresetScanProtocol("knee_mr", "膝关节 MR 扫描", "半月板、韧带及软骨损伤", ("MR",), 63, "knee"),
    PresetScanProtocol("hip_mr", "髋关节 MR 扫描", "股骨头坏死、盂唇损伤", ("MR",), 64, "hip"),
    PresetScanProtocol("ankle_mr", "踝关节 MR 扫描", "韧带、肌腱与软骨损伤", ("MR",), 65, "ankle"),
    # ---- 血管（70+）----
    PresetScanProtocol("head_neck_cta", "头颈部 CTA 扫描", "颅内及颈部血管：狭窄、动脉瘤", ("CT",), 70, "head_neck_vessel"),
    PresetScanProtocol("coronary_cta", "冠状动脉 CTA 扫描", "冠状动脉狭窄评估（CCTA）", ("CT",), 71, "coronary"),
    PresetScanProtocol("pulmonary_cta", "肺动脉 CTA 扫描", "肺动脉栓塞（CTPA）", ("CT",), 72, "pulmonary_vessel"),
    PresetScanProtocol("aorta_cta", "主动脉 CTA 扫描", "主动脉夹层、动脉瘤", ("CT",), 73, "aorta"),
    PresetScanProtocol("lower_limb_cta", "下肢 CTA 扫描", "下肢动脉狭窄/闭塞", ("CT",), 74, "lower_limb_vessel"),
    PresetScanProtocol("head_mra", "头部 MRA 扫描", "脑血管成像（无创，不用对比剂可选）", ("MR",), 75, "head_neck_vessel"),
    # ---- DR 其他（80+）----
    PresetScanProtocol("abdomen_dr", "腹部 DR 扫描", "立位腹平片：肠梗阻、消化道穿孔", ("DR",), 80, "abdomen"),
    PresetScanProtocol("spine_dr", "脊柱 DR 扫描", "全脊柱正侧位：侧弯、退变测量", ("DR",), 81, "spine"),
    # ---- 内置（999，保持原有字段不变）----
    PresetScanProtocol(
        "table_default",
        "表格数据导入",
        "内置流程：CSV/XLSX/Parquet 等临床表格数据的导入与规范化",
        ("TABLE",),
        999,
        "table",
    ),
)


# 存量数据集名称 → 部位分组的模糊匹配规则；靠前的规则优先（如「颈椎」先于「颈部」）。
_REGION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("head", ("头部", "头颅", "颅脑", "脑")),
    ("pituitary", ("垂体", "鞍区")),
    ("nasopharynx", ("鼻咽",)),
    ("cervical_spine", ("颈椎",)),
    ("thoracic_spine", ("胸椎",)),
    ("lumbar_spine", ("腰椎", "腰")),
    ("sacroiliac", ("骶髂",)),
    ("spine", ("脊柱", "椎体")),
    ("neck", ("颈部",)),
    ("thyroid", ("甲状腺",)),
    ("chest", ("胸部", "肺", "纵隔", "胸腔")),
    ("breast", ("乳腺",)),
    ("liver", ("肝脏", "肝")),
    ("mrcp", ("胰胆", "胆道", "MRCP", "mrcp")),
    ("abdomen", ("腹部", "腹", "胆囊", "胆", "胰腺", "脾", "肾脏", "肾", "泌尿")),
    ("adrenal", ("肾上腺",)),
    ("prostate", ("前列腺",)),
    ("uterus", ("子宫", "附件")),
    ("rectum", ("直肠",)),
    ("pelvis", ("盆腔", "膀胱")),
    ("shoulder", ("肩",)),
    ("knee", ("膝",)),
    ("hip", ("髋",)),
    ("ankle", ("踝",)),
    ("limb", ("四肢", "股骨", "胫骨", "肱骨", "尺桡骨")),
    ("joint", ("关节",)),
    ("coronary", ("冠脉", "冠状动脉", "CCTA", "ccta")),
    ("head_neck_vessel", ("头颈血管", "脑血管", "MRA", "mra")),
    ("pulmonary_vessel", ("肺动脉", "CTPA", "ctpa")),
    ("aorta", ("主动脉",)),
    ("lower_limb_vessel", ("下肢血管", "下肢动脉")),
)


def _presets_by_region() -> dict[str, tuple[PresetScanProtocol, ...]]:
    grouped: dict[str, list[PresetScanProtocol]] = {}
    for preset in PRESET_SCAN_PROTOCOLS:
        grouped.setdefault(preset.region, []).append(preset)
    return {region: tuple(items) for region, items in grouped.items()}


def suggest_preset_code(name: str, modality: str) -> str | None:
    """按数据集名称中的部位关键词 + 模态，建议一个预置流程 code；无匹配返回 None。

    规则按 _REGION_KEYWORDS 顺序取第一个命中的部位（保证「颈椎」先于「颈部」等），
    再取该部位下第一个模态兼容的预置流程（即该部位最通用的那一项）。
    """

    lowered = (name or "").lower()
    by_region = _presets_by_region()
    for region, keywords in _REGION_KEYWORDS:
        if not any(keyword.lower() in lowered for keyword in keywords):
            continue
        for preset in by_region.get(region, ()):
            if not preset.modality_scope or modality in preset.modality_scope:
                return preset.code
        return None
    return None
