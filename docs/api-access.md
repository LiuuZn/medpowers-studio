# 插件与训练仓库接入（API 鉴权契约）

本文档面向 **medpowers 插件 / skill 的实现方**，说明训练代码仓库如何以最小权限访问 MedPowers Studio。插件侧的命令、存储和 skill 文案由 `medpowers` 仓库实现；服务端只提供本文定义的 HTTP 契约。

> 部署形态：内网 HTTP 直连。默认地址 `http://<studio-host>:8000`。若需要跨不可信网络访问，必须在前面加 HTTPS 反向代理；Bearer Token 在 HTTP 上是明文传输。

## 1. 两种凭证

| 凭证 | 用途 | 有效期 | 管理方式 |
|---|---|---|---|
| JWT | 浏览器网页会话 | 默认 12 小时 | 用户名 + 密码登录获得 |
| API 访问令牌（`mps_...`） | 插件、训练仓库、脚本 | 30/90/180/365 天 | 网页「访问令牌」页创建，或设备码授权自动领取 |

两者都通过同一个请求头传递：

```http
Authorization: Bearer <access_token>
```

服务端先尝试按 JWT 解析，失败后再按 `mps_` 前缀查 API 令牌。**不要把密码保存到训练仓库或插件配置里**，插件只应保存 API 令牌。

## 2. 权限范围（scope）

| Scope | 允许的操作 | 典型用途 |
|---|---|---|
| `studio:read` | 所有只读元数据接口：数据集、患者/检查/序列、任务、导出记录、评估报告、实验/指标/复核队列、概览、元信息 | 查询有哪些数据集/任务/导出 |
| `studio:data` | 下载二进制数据：导出 ZIP、切片 PNG、标注掩码 | 拉取训练数据 |
| `studio:experiment` | 创建/更新实验镜像、批量推送指标点 | 训练进程上报 EXP 状态与曲线 |
| `studio:evaluate` | 推送外部评测结果；后续 Studio 原生评测提交也使用该权限 | 训练仓库回传 Dice/HD95 等 |
| `studio:review-request` | 把 `approved` 标注转为 `review_requested`，提醒人工复核 | badcase 发现标注可疑时 |
| `studio:dataset-manage` | 新建数据集、修改数据集属性、导入病例、标记就绪、新建扫描流程；**不能删除或归档** | 智能体/训练仓库接入开源数据集 |
| `studio:write` | 通用写接口（仅网页/管理端或极可信自动化） | 兼容旧脚本；训练仓库不应申请 |

注意：

- **scope 相互独立**，`studio:data` 不自动包含 `studio:read`。训练仓库默认建议 `studio:read studio:data studio:experiment studio:evaluate`；只有需要提醒人工复核时才加 `studio:review-request`。需要上传数据集时追加 `studio:dataset-manage`。
- **API 令牌不继承用户角色**：`/api/users`、任务创建、导出/评估创建、标注保存/提交/审核/撤回等管理端接口只允许网页 JWT；令牌调用一律 403。
  - 唯一例外是**数据集接入**：管理员账号的令牌携带 `studio:dataset-manage` 时，可以新建数据集、修改属性、导入病例、标记就绪、新建扫描流程。
  - 删除/归档数据集、修改/删除扫描流程仍然只允许网页管理员 JWT；令牌即使带该 scope 也会 403。
- 标注复核是 token 唯一允许的标注状态写入口：只改状态、不改内容/revision；`review_requested` 立即移出 approved 金标准池。
- 下列接口 **只允许网页 JWT**，任何 API 令牌都会被拒绝（403）：
  - `/api/users/*` 用户与密码管理
  - `/api/auth/tokens/*` 令牌管理
  - `/api/auth/device/lookup|approve|deny` 设备码审批
- `studio:write` 权限较大，只应发给可信自动化；训练仓库不要申请。

## 3. 推荐接入：设备码授权（RFC 8628）

用户在训练仓库里安装插件后，插件不应要求输入平台密码。推荐流程：

```text
插件                          Studio 后端                    用户浏览器
 |  POST /api/auth/device/code   |                              |
 |----------------------------->|                              |
 |  {device_code, user_code,    |                              |
 |   verification_uri_complete} |                              |
 |<-----------------------------|                              |
 |  打印 verification_uri_complete 和 user_code                 |
 |                                                             |
 |                              |<---- 打开链接、登录、确认 ---|
 |                              |      POST /device/lookup     |
 |                              |      POST /device/approve    |
 |                                                             |
 |  POST /api/auth/device/token |                              |
 |----------------------------->|                              |
 |  {access_token, scope, ...}  |                              |
 |<-----------------------------|                              |
 |  保存 token，后续带 Authorization 头                          |
```

### 3.1 申请设备码

```http
POST /api/auth/device/code
Content-Type: application/json

{
  "client_name": "medpowers-plugin@training-repo",
  "repo_key": "spine_locator",
  "scopes": ["studio:read", "studio:data", "studio:experiment", "studio:evaluate"]
}
```

响应：

```json
{
  "device_code": "3wJ...（高熵字符串，插件保存，不要展示给用户）",
  "user_code": "ABCD-EFGH",
  "verification_uri": "http://192.168.113.201:8000/device",
  "verification_uri_complete": "http://192.168.113.201:8000/device?user_code=ABCD-EFGH",
  "expires_in": 600,
  "interval": 5
}
```

- 设备码默认 10 分钟有效。
- 插件向用户展示 `verification_uri_complete`（或 `verification_uri` + `user_code`）。
- `client_name` 会显示在审批页面，建议包含机器名/仓库名，便于用户识别。
- `repo_key` 是训练仓库标识（同一仓库多机共用）；token 为 `(repo_key, exp_id)` 归属实验镜像，缺失时训练仓库写接口会拒绝。

### 3.2 轮询领取令牌

```http
POST /api/auth/device/token
Content-Type: application/json

{"device_code": "3wJ..."}
```

成功：

```json
{
  "access_token": "mps_...",
  "token_type": "Bearer",
  "scope": "studio:read studio:data studio:experiment studio:evaluate",
  "repo_key": "spine_locator",
  "expires_at": "2027-02-04T08:00:00Z",
  "user": {"id": "...", "username": "alice", "display_name": "Alice", "role": "annotator"}
}
```

失败统一为 HTTP 400：

```json
{"error": "authorization_pending", "error_description": "用户尚未完成授权"}
```

| `error` | 含义 | 插件行为 |
|---|---|---|
| `authorization_pending` | 用户尚未批准 | 按 `interval` 继续轮询 |
| `slow_down` | 轮询过快 | 增加轮询间隔（服务端也会提高该请求的 interval） |
| `access_denied` | 用户拒绝 | 停止轮询，提示用户 |
| `expired_token` | 设备码过期/已使用 | 停止轮询，重新申请 |
| `invalid_grant` | `device_code` 无效 | 停止轮询，重新申请 |

**一个 `device_code` 只能兑换一次。** 成功兑换后再次轮询会返回 `expired_token`。

### 3.3 用户在浏览器侧

- 打开 `verification_uri_complete`。
- 未登录时先登录；登录后自动回到设备授权页。
- 页面显示客户端名称、申请 scope、有效期，用户点击「批准」或「拒绝」。
- 批准后插件下次轮询即可拿到令牌。

## 4. 手动创建长期令牌

适合无法走浏览器的自动化场景：

1. 登录 Studio → 左侧「访问令牌」→「新建令牌」。
2. 填写 `repo_key`（训练仓库标识），选择 scope 与有效期。
3. 令牌只显示一次，立即复制到插件/Secret 管理。
4. 插件侧建议通过 `MEDPOWERS_STUDIO_TOKEN` 环境变量或 `runtime/studio.token`（0600）读取。

```http
POST /api/auth/tokens
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "name": "训练仓库-分割实验",
  "repo_key": "spine_locator",
  "scopes": ["studio:read", "studio:data", "studio:experiment", "studio:evaluate"],
  "expires_in_days": 90
}
```

响应中的 `token` 字段就是明文令牌，`info` 是不含明文的元数据。列表、撤销与删除：

- `GET /api/auth/tokens`
- `POST /api/auth/tokens/{token_id}/revoke`：撤销令牌（保留审计记录）
- `DELETE /api/auth/tokens/{token_id}`：永久删除令牌记录；若令牌仍有效会立即失效

## 5. 使用令牌读取平台信息

约定环境变量（由 medpowers 插件读取，具体实现以插件仓库为准）：

```bash
export MEDPOWERS_STUDIO_URL=http://192.168.113.201:8000
export MEDPOWERS_STUDIO_TOKEN=mps_xxx
```

```bash
# 插件启动自检：身份、凭证类型、scope 与可用能力
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/auth/context"

# 当前身份与角色
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/auth/me"

# 数据集
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/datasets"

# 任务
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/tasks"

# 导出记录与下载（下载需要 studio:data）
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/exports"
curl -fL -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  -o export.zip "$MEDPOWERS_STUDIO_URL/api/exports/<job_id>/download"

# 评估报告
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/evaluations/<job_id>/report"
```

### 5.1 训练仓库对接接口（实验/指标/评测/复核）

| 方法 | 路径 | Scope | 说明 |
|---|---|---|---|
| GET | `/api/studio/meta` | read | schema 版本、任务类型、指标 schema、能力 |
| GET | `/api/studio/tasks` | read | 任务（= 模型）就绪摘要 |
| GET | `/api/studio/tasks/{code}/readiness` | read | approved/复核计数、逐类病例、QC、标注契约、数据集 |
| GET | `/api/studio/changes?since=` | read | 增量同步（annotation/experiment） |
| POST | `/api/studio/experiments` | experiment | upsert 实验镜像（planned/running） |
| PATCH | `/api/studio/experiments/{exp_id}` | experiment | 状态/结束时间/记录摘要 |
| POST | `/api/studio/experiments/{exp_id}/metrics:batch` | experiment | 批量指标（幂等键 exp+name+split+class+step） |
| GET | `/api/studio/experiments/{exp_id}/metrics` | read | 指标查询 |
| POST | `/api/studio/experiments/{exp_id}/evaluations` | evaluate | 外部评测结果（source=external） |
| GET | `/api/studio/experiments/{exp_id}/evaluations` | read | 评测结果列表 |
| GET | `/api/studio/tasks/{code}/experiments` | read | 任务下实验镜像 |
| POST | `/api/annotations/{annotation_id}/request-review` | review-request | approved → review_requested（不改内容） |
| GET | `/api/studio/review-requests?status=open` | read | 复核队列 |

示例（训练仓库推送指标）：

```bash
curl -fsS -X POST -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  -H "Content-Type: application/json" \
  "$MEDPOWERS_STUDIO_URL/api/studio/experiments/EXP-001/metrics:batch" \
  -d '{"points":[{"name":"train/loss","value":0.42,"step":10,"split":"train"}]}'
```

注意：`POST /experiments` 的 `repo_key` 以 token 绑定值为准，请求体传其他仓库会 403；`exp_id` 格式 `EXP-<NNN>`，`task_code` 必须存在。外部评测与 Studio 原生评测用 `source` 区分，不得把外部指标冒充 Studio 金标准评测。

### 5.2 数据集接入（`studio:dataset-manage`，只增不删）

适用于"一个开源数据集 → 新建一个 Studio 数据集 → 分批上传病例"的智能体/自动化流程。令牌所属账号必须是 `admin`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/scan-protocols` | 新建扫描流程（数据集必填前置） |
| POST | `/api/datasets` | 新建数据集（默认 `draft`） |
| PATCH | `/api/datasets/{id}` | 修改 `name` / `description` / `scan_protocol_id` |
| POST | `/api/datasets/{id}/import-upload` | 上传 ZIP（推荐；客户端与服务器不共享文件系统时使用） |
| POST | `/api/datasets/{id}/import-path` | 服务端路径导入 |
| POST | `/api/datasets/{id}/import-jobs` | 提交大目录后台导入（每令牌最多 3 个 queued/running 任务） |
| POST | `/api/datasets/{id}/ready` | 有病例后标记 `ready` |

**明确禁止（403）**：`DELETE /api/datasets/{id}`、`POST /api/datasets/{id}/archive`、`PATCH/DELETE /api/scan-protocols/{id}`。这些操作只能由网页管理员在 Studio 界面执行。

**导入幂等**：同一数据集内按非空 `SeriesInstanceUID` 去重；重复上传同一序列会跳过并计入 `ImportReport.skipped`，不再生成 `_2` 副本。一个 ZIP 应包含完整序列。

示例：

```bash
# 1) 授权时申请 studio:read studio:data studio:dataset-manage
curl -fsS -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/auth/context"

# 2) 建流程、建数据集、上传、就绪
curl -fsS -X POST -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  -H "Content-Type: application/json" \
  "$MEDPOWERS_STUDIO_URL/api/scan-protocols" \
  -d '{"code":"qc_dr_chest","name":"DR 胸片质控","modality_scope":["DR"]}'

curl -fsS -X POST -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  -H "Content-Type: application/json" \
  "$MEDPOWERS_STUDIO_URL/api/datasets" \
  -d '{"code":"open_dr_001","name":"开源 DR 数据集","modality":"DR","scan_protocol_id":"<protocol_id>"}'

curl -fsS -X POST -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  -F "file=@cases.zip" -F "acknowledge_source_discarded=true" \
  "$MEDPOWERS_STUDIO_URL/api/datasets/<dataset_id>/import-upload"

curl -fsS -X POST -H "Authorization: Bearer $MEDPOWERS_STUDIO_TOKEN" \
  "$MEDPOWERS_STUDIO_URL/api/datasets/<dataset_id>/ready"
```

其他只读接口：

| 接口 | 说明 |
|---|---|
| `GET /api/datasets/{id}` | 数据集详情 |
| `GET /api/datasets/{id}/tasks` | 数据集关联任务与标注进度 |
| `GET /api/datasets/{id}/hierarchy` | 患者 → 检查 → 序列树；`level=patient|study|series` 控制平铺层级，默认 `patient` |
| `GET /api/tasks/{id}` / `GET /api/tasks/{id}/stats` | 任务详情与统计 |
| `GET /api/exports/{id}` / `manifest` | 导出详情与 manifest |
| `GET /api/evaluations` | 评估列表 |
| `GET /api/dashboard` | 概览计数 |
| `GET /api/meta/modalities` / `task-types` | 模态与任务类型注册表 |

数据下载类接口：

| 接口 | Scope |
|---|---|
| `GET /api/exports/{job_id}/download` | `studio:data` |
| `GET /api/cases/{case_id}/slice` | `studio:data` |
| `GET /api/tasks/{task_id}/annotations/{case_id}/mask` / `mask-slice` | `studio:data` |

`GET /api/auth/context` 返回示例：

```json
{
  "service": "MedPowers Studio",
  "version": "0.1.0",
  "api_prefix": "/api",
  "auth_method": "token",
  "scopes": ["studio:data", "studio:experiment", "studio:read"],
  "capabilities": {
    "read": true, "data": true, "write": false,
    "experiment": true, "evaluate": false, "review_request": false
  },
  "repo_key": "spine_locator",
  "user": {"id": "...", "username": "alice", "display_name": "Alice", "role": "annotator"}
}
```

插件应在每次启动时调用一次，根据 `capabilities` 决定是否允许下载数据或写入，而不是假设令牌拥有全部权限。

## 6. 错误与限流

- `401`：未携带令牌、JWT 过期、API 令牌无效/过期/已撤销、用户已停用。
- `403`：scope 不足、角色不足、或调用了仅限网页会话的接口。响应头会带：
  ```http
  WWW-Authenticate: Bearer error="insufficient_scope", scope="studio:data"
  ```
- `429`：登录、设备码申请、令牌创建等接口触发限流，响应头 `Retry-After` 给出等待秒数。
- 限流默认按客户端 IP 计数，默认每分钟 20 次；登录额外按 IP + 用户名限制 10 次/分钟。
- 单进程内存限流；多 worker 或反向代理部署时，如需严格全局限流应在网关层实现。

## 7. 插件侧安全要求

1. **令牌等同密码**：不要写入 Git、日志、实验产物、命令行历史（避免 `ps` 泄漏）；token 泄漏 = 用户凭证泄漏，立即撤销并轮换。
2. 建议保存位置：训练仓库 `<工作区>/runtime/studio.token`（0600，并加入 `.gitignore`），或从 `MEDPOWERS_STUDIO_TOKEN` 读取；`runtime/studio.json` 只存 base_url/repo_key/scopes 等非敏感配置。
3. 每个仓库使用独立 `repo_key`；同一仓库换机/轮换可有多枚 token，名称写清用途，便于单独撤销。
4. 默认申请 `studio:read studio:data studio:experiment studio:evaluate`；只有需要提醒人工复核时才加 `studio:review-request`；**不要给训练仓库 `studio:write`**。
5. 令牌失效时提示用户重新执行设备码授权，不要回退到保存用户名密码。
6. 插件不得自动批准设备码；批准必须由真人在浏览器完成。
7. 不要把 Studio 的 JWT 当作长期凭证保存到仓库；JWT 只用于网页会话。
8. 内网明文 HTTP 会泄露 token；只允许受控网段访问，有 TLS 时配置 CA/校验。

## 8. 服务端配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MEDPOWERS_ENVIRONMENT` | `development` | 设为 `production` 时拒绝默认 JWT secret |
| `MEDPOWERS_JWT_SECRET` | 开发默认值 | 生产必须 ≥32 字节随机值 |
| `MEDPOWERS_PUBLIC_BASE_URL` | 空 | 设备授权链接的对外地址，如 `http://192.168.113.201:8000`；为空时按请求 Host 推导 |
| `MEDPOWERS_ALLOWED_HOSTS` | `[]` | 可选 Host 白名单，JSON 数组 |
| `MEDPOWERS_ENABLE_HSTS` | `false` | 仅在 HTTPS 反向代理后开启 |
| `MEDPOWERS_API_TOKEN_DEFAULT_EXPIRE_DAYS` | `90` | 设备码授权发放令牌的默认有效期 |
| `MEDPOWERS_API_TOKEN_MAX_EXPIRE_DAYS` | `365` | 手动创建令牌的最大有效期 |
| `MEDPOWERS_DEVICE_CODE_EXPIRE_SECONDS` | `600` | 设备码有效期 |
| `MEDPOWERS_DEVICE_POLL_INTERVAL_SECONDS` | `5` | 设备码初始轮询间隔 |
| `MEDPOWERS_AUTH_RATE_LIMIT_PER_MINUTE` | `20` | 认证类接口限流阈值 |

部署安全清单：

- 修改默认管理员密码与 `MEDPOWERS_JWT_SECRET`。
- 只在内网/VPN 暴露 8000 端口；用防火墙限制来源网段。
- 跨不可信网络时使用 HTTPS 反向代理，并设置 `MEDPOWERS_PUBLIC_BASE_URL` 为外部地址。
- 定期在「访问令牌」页撤销不再使用的令牌；停用用户或重置密码会自动撤销其全部令牌。

## 9. 排障

| 现象 | 排查 |
|---|---|
| 401 未登录或登录已过期 | 令牌是否带 `mps_` 前缀、是否过期/撤销、用户是否停用 |
| 403 缺少 `studio:data` | 令牌 scope 不含下载权限；重新创建或换令牌 |
| 403 该操作需要网页登录会话 | 用了 API 令牌调用用户管理/令牌管理/设备审批 |
| 设备码轮询一直 `authorization_pending` | 用户尚未在浏览器批准；检查 `verification_uri_complete` 是否可达 |
| 设备码链接指向 `127.0.0.1` | 未设置 `MEDPOWERS_PUBLIC_BASE_URL`，且请求 Host 是回环地址 |
| 429 请求过于频繁 | 按 `Retry-After` 等待；不要高频重建设备码 |
