# AGENTS.md — MedPowers Studio

> **⚠ 并行工作区实例规范（本节优先于下文的一切命令与端口）**
> 本仓库是 `../`（medpowers-studio-workspaces）下的并行实例之一（mps1/mps2/mps3 三仓库相互独立）。**本仓库具体是哪个实例、独占哪个端口段，以本实例 `.env`（`MP_PORT`/`MP_CONTAINER_NAME` 等）与 `../AGENTS.md` 的登记表为准**，禁止臆测：
> - 实例独占一个百位端口段：部署 `x00`、热更新后端 `x01`、前端 Vite `x02`，`x10` 起留给附属容器（须在 `../AGENTS.md` 登记）；**严禁使用默认 8000**（宿主机已被其他服务占用），严禁占用其他实例端口段。
> - 启动/停止/重建一律用工作区根目录封装（自动注入端口并校验会话锁）：`../scripts/start.sh <实例>`、`../scripts/stop.sh <实例>`、`../scripts/docker.sh <实例> ...`、`../scripts/status.sh`。若直接跑本仓库 `scripts/start.sh`，必须显式 `MP_PORT=<本实例部署端口>`。
> - 会话开始先认领：`../scripts/claim.sh <实例> --owner <会话/任务标识>`；结束释放：`../scripts/release.sh <实例> --owner <同一标识>`。未持锁不得操作任何实例；mps1 为生产实例，操作须加 `--prod`。
> - 不要写其他 `mps*`/`mpp*` 目录。完整规范见 `../AGENTS.md`。

## 项目定位

医疗影像数据「管、标、训、评」一体化平台的初步框架。训练本身不在平台内执行；平台负责数据集管理、任务编排、标注/审核、训练数据导出、模型预测评估。

- 后端：FastAPI + SQLAlchemy 2 + PostgreSQL 16（测试/本地可用 SQLite）+ SimpleITK/pydicom/pyarrow
- 前端：React 18 + TypeScript + Vite + Ant Design 5
- 存储：PostgreSQL 存元数据；影像/表格/掩码走内容寻址 Blob（`blobs/sha256/...`），默认挂载 `./data/storage`
- 认证：JWT + bcrypt，三角色 `admin` / `annotator` / `reviewer`
- 界面与注释使用中文；代码标识符/URL/JSON 字段使用英文 snake_case

## 版本与发版纪律（与 medpowers 插件同版演进）

- **mps 与 mpp（medpowers-plugin）版本号保持一致**：发版时两仓同时改为同一个 `vX.Y.Z`（mps 先跟随 mpp 的版本锚）。
- mps 的版本事实源是**两处**，必须同步改：`backend/pyproject.toml` 的 `version` 与 `frontend/package.json` 的 `version`（`package-lock.json` 两处随之）；改完顺手同步 README 顶部版本徽章，并打 `vX.Y.Z` tag。
- mpp 的版本唯一事实源是其 `.claude-plugin/plugin.json`（发版纪律见该仓库 README）。
- 日常滚动 main 不动 `version`。GitLab 为开发主仓；GitHub 为公开镜像（`github.com/LiuuZn/medpowers-studio`、`github.com/LiuuZn/medpowers-plugin`），打 tag 后用工作区 skill `/github-sync` 同步，**同步只带 `main + 全部 tags`**（不携带开发分支与中间提交）。

## 分支与提交纪律（强制，2026-11-09 起）

- **原始提交只进私有 GitLab**（origin）；GitHub 是发布镜像，不接收原始提交。
- **原始提交必须落在开发分支**，禁止在 `main` 上直接提交；分支命名 `<type>/<topic>`（如 `feat/seg-canvas`）。
- **开发分支经 MR 以 Squash + fast-forward 合入 `main`**：GitLab 已将 `main` 设为保护分支（任何人不可直接推送、仅 MR 合入、强制 squash），`main` 上每个功能/修复一条线性干净提交。
- **GitHub 只保留发布面**：发布同步只带 `main + 全部 tags`（工作区 skill `/github-sync` 默认即如此），开发分支与中间提交不出现在 GitHub。
- **tag 只打在 `main` 的发布提交上**，打完 tag 才推 GitHub。
- **强制层**：GitLab 保护分支（服务端）+ `scripts/git-hooks/pre-commit`（本地 main 直提拦截，经 `git config core.hooksPath scripts/git-hooks` 启用，工作区 `claim.sh` 认领实例时自动安装）；紧急豁免 `MPS_ALLOW_MAIN_COMMIT=1 git commit ...`，提交说明必须注明原因。

## 常用命令

> 长期运行**不要**依赖 AI 终端的后台任务；生产使用 `docker compose up -d`，本地调试可用 `scripts/start.sh`。

```bash
# 生产/长期运行（PostgreSQL + 应用容器，数据在 ./data）
cp .env.example .env        # 修改 JWT secret、DB 密码、管理员密码
docker compose up -d --build
docker compose logs -f
docker compose down

# 本地开发（SQLite + 热更新）
cd backend && uv sync --extra dev && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# 后端 lint / 测试
cd backend && uv run ruff check app tests scripts
cd backend && uv run pytest

# 演示数据（幂等，按编码复用）
cd backend && uv run python scripts/seed_demo.py

# 存量数据迁移（先 dry-run；默认只统计）
cd backend && uv run python scripts/migrate_to_v2.py --dry-run
cd backend && uv run python scripts/migrate_to_v2.py --apply --resume
cd backend && uv run python scripts/verify_storage.py

# SQLite -> PostgreSQL（空库或 --replace）
cd backend && uv run python scripts/migrate_sqlite_to_postgres.py --sqlite medpowers_studio.db --replace

# 批量提交并审核通过数据集内已有标注（按名称片段匹配；先 --dry-run）
cd backend && uv run python scripts/approve_dataset_annotations.py --dataset "脊柱关键层面 CT" --dry-run

# 历史病例补齐 DICOM Patient / Study / Series 层级（幂等）
cd backend && uv run python scripts/backfill_hierarchy.py
```

默认管理员：`admin / admin123`（生产必须改）。演示账号：`annotator1 / pass1234`、`reviewer1 / pass1234`。

重置演示数据：停止服务，删除 `data/`（容器模式）或 `backend/medpowers_studio.db` + `backend/storage/`（本地模式），重新 seed。

## 目录与职责

```text
backend/app/
├── api/            # 路由层，只做参数校验/权限/组装响应
├── domain/         # 模态、数据种类、任务类型、标签校验、常量（扩展点）
├── metrics/        # 纯函数指标：分割/检测/关键帧
├── services/       # 导入、资产存储、Patient/Study 层级、切片渲染、标注、导出、评估
│   ├── asset_store.py   # 内容寻址 Blob 存取
│   ├── formats/         # 各格式适配器：volume/image/table
│   └── import_jobs.py   # 大目录后台导入
├── models.py       # SQLAlchemy ORM
├── schemas.py      # Pydantic 请求/响应
├── db.py           # engine/session/init
└── main.py         # app 工厂、生命周期、静态前端托管
backend/migrations/ # Alembic
frontend/src/
├── api/            # axios 客户端与 TS 类型
├── auth/           # AuthContext
├── components/     # StatusTag、LabelSchemaEditor、SegCanvas、BoxCanvas、TablePreview
├── layouts/        # MainLayout
└── pages/          # 概览、数据集（含标注/表格预览）、任务、实验与指标、导出、评估、扫描流程、用户
```

## 硬性业务规则（改动时勿破坏）

1. **严格维度匹配**：2D 任务只能关联 2D DR；3D 任务只能关联 3D CT/MR。关联接口在服务端强制校验，前端过滤只是体验优化。
2. **每个数据集必须且只能绑定一个扫描流程**；流程停用不删除，保留历史引用。**数据集接入优先绑定预置标准流程**（清单在 `backend/app/domain/protocol_presets.py`，启动时按 code 幂等补种；如 head_ct=头部 CT 扫描、abdomen_mr=腹部 MR 扫描），均不适用时管理员再自定义新建；存量数据集批量改绑用 `backend/scripts/apply_preset_protocols.py`（默认 dry-run）。
3. **数据集必须先 `ready` 才能被任务关联**；有序列才能标记 ready。
4. **已有标注的任务不能修改标签体系**；已关联任务的数据集不能归档/删除。
5. **已提交/已通过标注不可直接编辑**；管理员撤回后才能改。
6. **导出默认只包含 approved 标注**；评估默认只用 approved 作为金标准。
7. 3D 张量轴序 `(Z,Y,X)`；3D 影像压缩 NRRD；2D PNG；分割掩码 uint8，值=类别 id，0 背景。
8. 3D 检测前端编辑体素坐标，后端换算 RAS mm 世界坐标；不要只存世界坐标而丢失体素编辑信息。
9. **数据层级为 `Dataset → Patient → Study → Case(Series)`**：一个 Case 就是一个序列。导入 NRRD/DICOM 时从头部初始化 Patient/Study/Series；缺少 UID 时按 `PatientID → StudyInstanceUID → 序列级匿名患者` 回退，不能在患者级划分中把无标识序列合并成同一患者。
10. **标注入口在数据集内**：不恢复独立“标注”菜单/页面。数据集详情通过任务选择器展示每条序列的标注状态，并跳转到标注工作台。
11. **插件访问使用 scoped API 令牌**：`mps_` 令牌只保存 SHA-256 摘要；scope 为 `studio:read`（元数据）/ `studio:data`（二进制）/ `studio:experiment`（实验+指标）/ `studio:evaluate`（评测结果）/ `studio:review-request`（复核申请）/ `studio:dataset-manage`（数据集接入：只增不删）/ `studio:write`（通用写，仅管理端/极可信自动化）。**API 令牌不继承用户角色**：用户管理、删除/归档数据集、修改扫描流程、任务创建、导出/评估创建、标注保存/提交/审核/撤回只允许网页 JWT；唯一例外是管理员账号的令牌携带 `studio:dataset-manage` 时，可新建/修改数据集属性、导入病例、标记就绪、新建扫描流程，但不能删除或归档。新增路由时确认 scope 映射与 token 禁写清单，接入契约见 `docs/api-access.md`。
12. **训练仓库只读标注 + 复核申请**：`approved → review_requested` 只改状态，不改 `data`/`mask_path`/`version`/revision；`review_requested` 不计入 approved，不进入导出/评测金标准池；复核通过回 approved，驳回回 in_progress；申请必须留 reason/token/repo_key 审计。`AnnotationReviewRequest` 是唯一复核历史表。
13. **实验镜像是只读可视化**：`Experiment/MetricPoint/ExternalEvaluation` 以 `(repo_key, exp_id)` 关联 git 中的 EXP 记录；git 是权威，Studio 不提供实验正文编辑；指标按 `(experiment,name,split,class,step)` 幂等 upsert，外部评测 `source=external` 不得冒充 Studio 原生评测。Studio 不托管 checkpoint/模型权重。
14. **数据必须自包含**：Case 影像/表格只保存在 `storage_root/blobs/sha256/...`；数据库只存相对 storage key，禁止新增宿主机绝对路径。导入不再支持 reference 模式。
15. **只保留规范格式**：3D → 压缩 NRRD，2D → PNG，表格 → Parquet；原始 DICOM/NIfTI/图片/表格不进入平台长期存储，导入必须显式确认“用户已备份”。
14. **表格数据集**：`modality=TABLE`、`data_kind=table`、`dimension=tabular`；使用内置 `table_default` 扫描流程。表格 MVP 只支持导入/浏览，不参与标注/导出/评估。

## 扩展点

### 新增模态

编辑 `backend/app/domain/modalities.py`，登记 `code/name/dimension/description/data_kind`。维度与数据种类由注册表推导，数据集创建接口无需改。

### 新增数据种类 / 格式

1. `backend/app/domain/data_kinds.py` 登记 `DataKindSpec`（dimension、canonical_format、viewer）；
2. `backend/app/services/formats/` 增加适配器（detect/probe/normalize/read）；
3. `import_service.py` 增加发现与 materialize 分支；
4. 前端增加查看器/预览组件；
5. 导出/评估如需要，补 `export_service.py` / `evaluation_service.py`。

### 新增任务类型

1. `backend/app/domain/task_types.py` 增加 `TaskTypeSpec` 与默认标签体系；
2. 确定 `annotation_kind`：`mask` / `keyframe` / `boxes`；
3. 若是全新交互类型，需要新增：
   - 标注数据校验函数；
   - 前端工作台面板；
   - 导出器 `export_service.py`；
   - 评估器 `evaluation_service.py` + `metrics/`。
4. 同步更新 README/design 的矩阵与格式说明。

### 新增导出格式

在 `export_service.py` 中按 `job.format` 分派；保持 `manifest.json` 记录标注版本与文件映射。

### 新增指标

`backend/app/metrics/` 放纯函数；`evaluation_service.py` 负责逐例/聚合与报告结构。

## 已知首版边界

- 3D 分割仅轴位逐层勾画；冠状位/矢状位只能查看。
- 表格数据只支持导入/浏览/Parquet 下载，不支持标注、导出训练集、评估。
- 导入/导出/评估默认同步执行；大目录导入可走 `import-jobs` 后台任务，但仍是单进程线程池，不是分布式队列。
- 数据集无版本/快照；导出/评估用标注 revision 追溯。
- 无项目级权限、病例级任务分配、盲标/仲裁。
- 训练运行、模型仓库、推理服务不在平台内。
- 导入元数据只保留哈希 PatientID 与检查/序列字段，不落姓名/生日；原始 DICOM 文件与像素烧录信息未做去标识化。
- 3D 检测世界框按 AABB 处理，斜向方向矩阵的精确有向框未实现。
- 内容寻址 Blob 默认只增不减；孤立 Blob 用 `scripts/gc_blobs.py` 手动清理。

## 验证要求

- 改后端：至少跑 `uv run ruff check app tests scripts` 与 `uv run pytest`。
- 改前端：至少跑 `npm run build`（含 `tsc --noEmit`）。
- 改标注画布/切片接口：手动或 Playwright 验证 2D 画笔、3D 逐层保存、关键帧、检测框、审核状态。
- 改存储/导入：验证导入后 DB 中无绝对路径、Blob 存在且 sha256 一致、重复导入只产生一个 Blob。
- 改容器：`docker compose build` + `docker compose up -d`，确认 `/api/health/ready` 返回 200，重启后数据仍在。
- 不要提交生成物：`backend/medpowers_studio.db`、`backend/storage/`、`data/`、`imports/`、`frontend/dist/`、`node_modules/` 已在 `.gitignore`。

## 待确认问题

见 `docs/design.md` 第 9 节。接入真实数据前优先确认：序列粒度与多序列选择、数据接入方式、导出格式、评估预测输入方式、3D 标注交互需求。（扫描流程清单已由预置字典解决，见 `backend/app/domain/protocol_presets.py`。）
