# MedPowers Studio 设计说明

> 版本：v0.1（初步框架）  
> 日期：2026-11-05

## 1. 需求理解

平台覆盖医疗影像数据的四个环节：

```text
扫描流程配置 → 数据集管理 → 任务编排 → 标注/审核 → 训练数据导出 → 训练后评估
```

- **管**：数据集、病例影像、扫描流程字典、元数据与存储路径。
- **标**：按任务组织标注，支持提交、审核、驳回、撤回与版本快照。
- **训**：不运行训练，导出训练就绪数据（首版 nnU-Net 风格 + 任务 JSON）。
- **评**：上传模型预测，与金标准标注比对，输出逐例/汇总指标。

平台首版是管理台 + 标注工作台，不包含训练调度、GPU 管理、模型仓库和推理服务。

## 2. 角色

| 角色 | 权限 |
|---|---|
| 管理员 `admin` | 全部权限：扫描流程、数据集、任务、用户、导出、评估、标注、审核、撤回 |
| 标注员 `annotator` | 查看数据集/任务，保存/提交标注，不能审核，不能管理基础数据 |
| 审核员 `reviewer` | 查看数据集/任务/标注，审核通过/驳回；不能编辑标注 |

首版没有项目级隔离和病例级任务分配：标注员可以处理任务下所有病例。后续如需盲标/仲裁，应在 `Annotation` 上增加分配表与审核轮次。

## 3. 领域模型

### 3.1 ScanProtocol 扫描流程

| 字段 | 说明 |
|---|---|
| `code` | 唯一编码，创建后不可改 |
| `name` | 展示名称 |
| `modality_scope` | 适用模态列表；空表示全部模态 |
| `sort_order` / `is_active` | 排序、启停 |
| `description` | 说明 |

规则：

- 数据集必须且只能选择一个扫描流程。
- 新建数据集时只能选择启用且模态匹配的流程。
- 停用流程不会破坏历史数据集引用；删除前会检查是否被使用。
- 修改流程适用范围时，会检查已使用该流程的数据集模态，避免出现非法历史引用。

预置清单：系统内置约 45 项常见标准检查流程（`backend/app/domain/protocol_presets.py` 的
`PRESET_SCAN_PROTOCOLS`），按「部位 + 模态 + 扫描」命名（头部 CT 扫描、腹部 MR 扫描、
腰椎 MR 扫描、冠状动脉 CTA 扫描等），按部位分组（头颈神经/胸部/腹部/盆腔/脊柱/四肢关节/
血管/DR）设置 `sort_order`；应用启动时按 `code` 幂等补种——只创建缺失项，不覆盖管理员的
修改。数据集接入应优先绑定预置流程，均不适用时管理员再自定义新增；存量数据集可用
`backend/scripts/apply_preset_protocols.py` 按名称部位关键词批量改绑（默认 dry-run）。

### 3.2 Dataset 数据集

数据集是**组织容器**，不是 DICOM 层级本身；一个数据集可以覆盖多个患者、多个检查。

| 字段 | 说明 |
|---|---|
| `code` / `name` | 唯一编码、名称 |
| `modality` | `DR` / `CT` / `MR` / `TABLE`，注册表可扩展 |
| `dimension` | 由模态推导：DR→2d，CT/MR→3d，TABLE→tabular |
| `data_kind` | `volume3d` / `image2d` / `table` |
| `scan_protocol_id` | 必填，单选；表格数据集使用内置 `table_default` |
| `status` | `draft` / `ready` / `archived` |
| `case_count` | 序列/表格记录数（导入时维护） |
| `patient_count` / `study_count` | 由层级关系实时聚合，不单独存储 |
| `storage_path` | 相对 storage key（`datasets/<id>`），不再存绝对路径 |

状态：

- `draft`：刚创建，可导入序列。
- `ready`：至少有一个序列，可被任务关联。
- `archived`：不可导入/关联；已关联任务时禁止归档。

### 3.3 Patient / Study / Case（Series）层级

```text
Dataset（组织容器）
└── Patient（患者，patient_key 加盐哈希）
    └── Study（检查，StudyInstanceUID）
        └── Case / Series（序列，SeriesInstanceUID）
```

| 实体 | 关键字段 | 说明 |
|---|---|---|
| `Patient` | `patient_key`、`sex`、`age` | `patient_key` 全局唯一；不存患者姓名/出生日期 |
| `Study` | `study_uid`、`description`、`study_date`、`accession_number` | 患者内按 `study_uid` 唯一 |
| `Case` | `study_id`、`series_uid`、`series_number`、`series_description`、`patient_key` | 一个 Case = 一个序列；保留 `patient_key` 供患者级划分 |

`Case` 的业务字段：

| 字段 | 说明 |
|---|---|
| `case_uid` | 数据集内唯一；优先用 DICOM SeriesInstanceUID，否则文件名 |
| `data_kind` | `volume3d` / `image2d` / `table` |
| `image_path` | 相对 storage key，指向 `blobs/sha256/...` |
| `image_format` | 规范格式：`nrrd` / `png` / `parquet` |
| `size_bytes` / `sha256` | 规范文件大小与内容哈希 |
| `geometry` | 3D：ITK size/spacing/origin/direction + array_shape；2D：宽高；表格：行数/列定义 |
| `source_kind` | `dicom_series` / `volume_file` / `image_file` / `dicom_image` / `table_file` |
| `source_path` / `metadata_json` | 来源与脱敏后的元数据 |

### 3.3.1 v2 资产存储（自包含）

- 所有 Case 主文件写入 `storage_root/blobs/sha256/<前2位>/<次2位>/<sha256>`，内容寻址、自动去重。
- `Blob` 表登记哈希/大小/media type/storage key；`CaseAsset` 关联 Case 与 Blob（`canonical`、`source_manifest`）。
- 导入时只保留规范化格式：3D→压缩 NRRD，2D→PNG，表格→Parquet；原始文件不进入平台长期存储，导入必须显式确认用户已备份。
- `source_manifest` 记录原文件名/大小/源格式，不能还原原始文件。
- 数据库不再保存宿主机绝对路径；迁移脚本负责把 v1 的 `/ssd/...` 路径复制进 Blob 并改写为相对 key。
- 5TB 级容量使用本地内容寻址存储 + PostgreSQL 元数据；`AssetStore` 接口预留 S3/MinIO 适配。

**NRRD / DICOM 导入时的层级初始化规则**：

1. **Patient**：优先 `PatientID` 的加盐 SHA-256；没有 `PatientID` 但有 `StudyInstanceUID` 时由检查 UID 派生；两者都没有（如合成 NRRD、PNG）时为每个序列生成独立匿名患者，确保患者级训练划分不会把整个数据集放进同一 split。
2. **Study**：优先 `StudyInstanceUID`；缺失时生成 `local:<patient_key>`，保证同一患者的序列至少能归入一个本地检查。
3. **Series**：优先 `SeriesInstanceUID`；缺失时生成 `local:<数据集内唯一 case_uid>`。
4. 原始 `PatientID`、`PatientName`、`PatientBirthDate` 不写入病例元数据；只保留哈希后的 `patient_key` 与非姓名字段。

数据集详情页支持**患者 / 检查 / 序列**三档视图，默认停留在序列层面（标注与序列强关联）。患者层面按三级树逐级展开；检查层面平铺所有 study，并展开到序列；序列层面直接平铺所有序列。一个数据集可以关联多个任务，因此页面顶部提供**任务选择器**，当前任务决定每条序列显示的标注状态；点击序列直接进入该任务的标注工作台。独立“标注”菜单已移除。

### 3.4 Task 任务

| 字段 | 说明 |
|---|---|
| `code` / `name` | 唯一编码、名称 |
| `task_type` | `seg3d` / `seg2d` / `keyframe3d` / `det3d`，注册表可扩展 |
| `dimension` | 由任务类型推导 |
| `label_schema` | 标签体系 JSON |
| `annotation_guide` | 标注指南 |
| `status` | `draft` / `active` / `archived` |

任务与数据集是**多对多**关系。关联时校验：

- 数据集存在且 `status == ready`；
- 数据集 `dimension` 与任务 `dimension` 严格相等；
- 不能重复关联；
- 已有标注的数据集不能解除关联。

### 3.5 Annotation 标注

按“任务 × 序列（Case）”唯一。

| 字段 | 说明 |
|---|---|
| `status` | `pending` / `in_progress` / `submitted` / `approved` / `rejected` / `review_requested` |
| `data` | 关键帧/检测 JSON；分割任务的统计元信息 |
| `mask_path` | 分割任务提交版本掩码 |
| `version` | 提交版本号 |
| `annotator_id` / `reviewer_id` | 标注人/审核人 |
| `review_comment` | 审核意见 |

状态机：

```text
pending → in_progress → submitted → approved
                              └────→ rejected → in_progress

approved --训练仓库/插件申请复核（需 studio:review-request）--> review_requested
review_requested --复核通过--> approved
review_requested --复核驳回--> in_progress（标注员修改后重新提交）

submitted/approved/rejected/review_requested --管理员撤回--> in_progress
```

- 草稿保存只更新 current 工作区；提交时生成 `AnnotationRevision` 快照。
- 已提交/已通过标注不能直接编辑；管理员可撤回后继续修改。
- `review_requested` 只改状态，不改 `data`/`mask_path`/`version`/revision；不计入 approved，不进入导出/评测金标准池；每次申请写入 `AnnotationReviewRequest`（token/repo_key/reason/evidence/eval_id）。
- 3D 分割逐层保存 PNG 到 working 目录，提交时按影像几何组装为压缩 NRRD。

### 3.6 ExportJob 导出作业

| 字段 | 说明 |
|---|---|
| `task_id` | 任务 |
| `dataset_ids` | 选中的关联数据集 |
| `format` | 首版 `nnunet` |
| `split_config` | 比例/种子/患者级开关，或显式 train/val/test 列表 |
| `include_statuses` | 纳入导出的标注状态 |
| `status` | queued/running/succeeded/failed |
| `output_dir` / `manifest_path` / `summary` | 产物与统计 |

导出目录示例（3D 分割）：

```text
exports/<job_id>/
├── imagesTr/
│   └── <case>_0000.nrrd
├── labelsTr/
│   └── <case>.nrrd
├── dataset.json
├── splits.json
├── splits_final.json
└── manifest.json
```

关键帧/检测使用 `images/` + `labels/<case>.json`。

### 3.7 EvaluationJob 评估作业

| 字段 | 说明 |
|---|---|
| `task_id` | 任务 |
| `dataset_ids` | 参与评估的数据集 |
| `gt_statuses` | 作为金标准的标注状态（默认 approved） |
| `prediction_path` | 解压后的预测目录 |
| `metrics_config` | IoU 阈值、关键帧容差、是否含背景等 |
| `report_path` / `summary` | 报告与汇总 |

预测结果 ZIP 约定：

- 分割：`<case_uid>.nrrd` 或 `<case_uid>.png`（也兼容 `_0000` 后缀和嵌套目录）。
- 关键帧：`predictions.json`，`{case_uid: [{label_id, z_index}, ...]}` 或 `{cases: {...}}`。
- 检测：`predictions.json`，`{case_uid: [{label_id, center_world, size_world}, ...]}`。

### 3.8 Experiment / Metric 镜像（训练仓库对接）

`medpowers` 插件把训练仓库的实验镜像推送到 Studio，用于可视化与查询；**git 中的 `EXP-<NNN>` 记录是实验事实的权威**，Studio 不提供正文编辑，也不托管 checkpoint。

| 实体 | 关键字段 | 规则 |
|---|---|---|
| `Experiment` | `repo_key` + `exp_id` 唯一、`task_id`（任务=模型）、`status`、`machine`、`git_commit`、`config`、`record_path`/`record_sha256`、时间 | 状态与 exp-mgmt 对齐：`planned/running/done/interrupted/cancelled`；幂等 upsert |
| `MetricPoint` | `name`、`value`、`step`、`epoch`、`split`、`class`、`tags`、`source` | 任意数值指标；幂等键 `(experiment,name,split,class,step)`；批量上限 5000 |
| `ExternalEvaluation` | `eval_id`、`source=external`、`gt_statuses`、`dataset_version`、`summary`、`per_case`、`report_sha256` | 外部推送结果与 Studio 原生评测用 `source` 区分；不得冒充金标准评测 |

- token 通过 `studio:experiment` / `studio:evaluate` 写；`repo_key` 以 token 绑定值为准，请求体传其他仓库 403。
- 推送失败不影响训练：插件侧写本地队列，恢复后重放；Studio 侧幂等。

## 4. 模态与任务匹配矩阵

| 模态 | 维度 | seg3d | seg2d | keyframe3d | det3d |
|---|---|:---:|:---:|:---:|:---:|
| 2D DR | 2D | ✗ | ✓ | ✗ | ✗ |
| 3D CT | 3D | ✓ | ✗ | ✓ | ✓ |
| 3D MR | 3D | ✓ | ✗ | ✓ | ✓ |

这是首版按需求确定的**严格匹配**规则：3D 数据不自动切片用于 2D 任务。若后续需要“3D 数据切片做 2D 分割”，应新增独立的任务类型或显式的切片导出配置，而不是放宽关联校验。

## 5. 标签体系

分割：

```json
{
  "classes": [
    {"id": 0, "name": "背景", "color": "#000000"},
    {"id": 1, "name": "目标", "color": "#ff4d4f"}
  ]
}
```

- id 从 0 连续编号，0 固定背景；
- 掩码像素值 = 类别 id。

关键帧/检测：

```json
{
  "labels": [
    {"id": 1, "name": "病灶", "color": "#fa8c16"}
  ]
}
```

- id 从 1 开始，名称唯一。

任务已有标注后禁止修改标签体系，避免历史标注语义漂移。

## 6. 标注数据格式

### 6.1 3D 分割

- 工作区：`annotations/<task_id>/<case_id>/working/z0001.png` 等，单层 PNG，像素值 = 类别 id。
- 提交：`current/mask.nrrd`，uint8，几何与影像一致，z-y-x 轴序。
- 当前首版只支持轴位勾画；冠状位/矢状位可查看。

### 6.2 2D 分割

- `current/mask.png`，尺寸与影像一致，像素值 = 类别 id。

### 6.3 关键帧

```json
{
  "frames": [
    {"label_id": 1, "z_index": 8}
  ]
}
```

### 6.4 3D 检测

```json
{
  "boxes": [
    {
      "label_id": 1,
      "center_voxel": [32.0, 32.0, 8.0],
      "size_voxel": [18.0, 18.0, 6.0],
      "center_world": [-11.2, -21.6, 26.0],
      "size_world": [21.6, 21.6, 12.0]
    }
  ]
}
```

- 前端以体素坐标编辑，后端用影像 origin/spacing/direction 换算世界坐标。
- 方向矩阵非单位时，世界坐标为体素框 8 个角点的 AABB；斜向扫描的精确有向框留待后续。

## 7. 评估指标

### 7.1 分割

按类别二值化后计算：

- Dice
- IoU
- Precision / Recall
- HD95（mm，按影像 spacing）

空 GT + 空预测：Dice/IoU 记为 1，HD95 记为 0；仅一侧为空：HD95 记为缺失，不参与该类均值。

### 7.2 检测

按类别、按 IoU 阈值做贪心一对一匹配：

- TP/FP/FN
- Precision/Recall/F1
- 匹配框平均 IoU

### 7.3 关键帧

按类别、按层容差做贪心一对一匹配：

- TP/FP/FN
- Precision/Recall/F1
- 匹配帧平均绝对层误差

## 8. 关键设计决策

| 决策 | 理由 |
|---|---|
| 严格维度匹配 | 与需求一致，避免 3D→2D 隐式切片带来的语义歧义 |
| 扫描流程单选 | 一个数据集对应一个采集流程，便于统计和筛选；停用而非删除 |
| 任务类型注册表 | 新任务类型只加注册项与前端面板，不迁移核心表 |
| 标签体系 JSON | 不同任务标签差异大；JSON 便于扩展，同时后端做规范化校验 |
| 标注版本快照 | 导出/评估可复现，审核后仍可追溯 |
| 3D 掩码逐层 PNG → 提交组装 NRRD | 浏览器端无需生成大体积 NRRD，后端统一几何与压缩 |
| Dataset → Patient → Study → Series 层级 | 与 DICOM 语义一致；数据集可跨患者/检查组织；患者级划分有稳定依据 |
| 标注入口在数据集内 | 数据集与标注强耦合；避免独立的“标注”功能与任务/数据集脱节 |
| 同步导入/导出/评估 | 首版简单可靠；大目录导入已提供后台任务，仍为单进程线程池 |
| PostgreSQL + 本地内容寻址 Blob | 5TB 级影像/表格不适合放数据库 BLOB；本地卷少一层运维，`AssetStore` 预留对象存储 |
| 只保留规范化格式 | 统一训练/导出/评估的读取路径；原始文件由用户自行备份，`source_manifest` 保留追溯信息 |

## 9. 待确认问题

以下问题在首版按合理默认实现，需要真实数据/业务确认：

1. ~~**扫描流程清单**：请提供实际选项（编码、名称、适用模态、说明）。~~ **已解决（2026-11-08）**：系统已预置约 45 项常见标准检查流程（见 3.1「预置清单」），管理员仍可自定义新增；「适用模态为空=全部」能力保留给自定义流程。
2. **数据接入方式**：真实数据是 DICOM 目录、NIfTI/NRRD、PACS 拉取，还是对象存储？当前已统一为“复制并规范化进平台 Blob”，原始文件不保留；是否需要改为原始+规范双份？
3. **序列粒度**：当前已按“一个 Case = 一个序列”建模，并从 NRRD/DICOM 头初始化 Patient/Study。若业务需要以“检查”为标注对象（多序列融合），需要新增 Study 级标注或多序列选择逻辑。
4. **标注协作**：是否需要多标注员、盲标、仲裁、按病例分配、标注工时统计？
5. **导出格式**：是否要求严格兼容某个 nnU-Net 版本（`dataset.json`/`splits_final.json` 字段）？关键帧/检测的 JSON 是否要适配现有训练代码？
6. **评估输入**：预测结果是否总是 ZIP 上传，还是需要平台直接调用推理服务/PACS？是否需要 ROC、PR 曲线、mAP 等更完整指标？
7. **数据集版本**：导入新病例后，已导出的训练集是否需要版本化/冻结？是否需要数据集快照？
8. **权限范围**：是否需要项目/团队隔离、数据集级授权、操作审计日志？
9. **规模与部署**：预计病例数、单例体积、并发标注人数；是否部署在 GPU 服务器/内网服务器/容器平台？当前按约 5TB 影像 + PostgreSQL + 本地 Blob 卷设计；更大规模或多副本需切对象存储与独立任务队列。
10. **3D 标注体验**：是否需要三视图联动、层间插值、AI 预分割、撤销/重做、快捷键？当前首版是轴位逐层画笔。
11. **DICOM 去标识化**：除 PatientID 外，是否需要按院方规范清除姓名、生日、机构等标签？
12. **训练与模型管理**：后续是否要把训练任务、模型版本、推理服务也纳入平台（当前明确不在首版）？

## 10. 建议的下一阶段

1. 用真实数据验证导入器与标注工作台，确定序列粒度、多序列选择、窗宽窗位默认值。
2. 完善 3D 标注：三视图、插值、撤销/重做、快捷键、预分割。
3. 引入后台任务队列，支持大规模导入/导出/评估与进度展示。
4. 增加数据集版本与导出快照，保证训练数据可复现。
5. 增加任务分配、盲标、仲裁与审核轮次。
6. 按实际训练代码对齐导出格式与评估指标。
