# 部署与启动

本项目生产部署使用 **Docker Compose（PostgreSQL 16 + Studio 应用）**。长期运行不要依赖 IDE/AI 终端的后台任务。

## 1. Docker Compose（推荐生产/长期运行）

```bash
cp .env.example .env         # 修改 MP_DB_PASSWORD、JWT secret、初始管理员密码
mkdir -p data imports
docker compose up -d --build
docker compose ps
docker compose logs -f studio
```

- `db`：PostgreSQL 16，数据在 `${MP_DATA_DIR:-./data}/postgres`。
- `studio`：FastAPI + 前端构建产物，影像/表格/掩码在 `${MP_DATA_DIR:-./data}/storage`。
- 大数据目录放到 `${MP_IMPORT_DIR:-./imports}`，容器内只读挂载为 `/imports`，通过“从服务器路径导入”或后台导入任务使用。
- 健康检查：`curl http://127.0.0.1:8000/api/health/ready`（检查 DB + storage 可写）。
- 容器启动时自动执行 `alembic upgrade head`；入口脚本会等待数据库就绪。
- 停止（保留数据）：`docker compose down`。
- 彻底删除（**会删除数据**）：`docker compose down && rm -rf ./data`。

### 5TB 级容量准备

- 将 `MP_DATA_DIR` 指向专用数据盘（建议 ≥5TB，可独立扩容），不要放在系统盘。
- 导入前会检查剩余空间，默认保留 `MEDPOWERS_STORAGE_MIN_FREE_GB=50`。
- Blob 采用 `sha256` 两级分片目录，避免单目录海量文件；相同内容自动去重。
- 大目录优先使用“后台导入”，不要用 HTTP 上传数 TB 数据。
- 存储用量：`GET /api/admin/storage/usage`（管理员）。
- 孤立 Blob 清理：`docker compose exec studio python scripts/gc_blobs.py`（默认 dry-run，确认后加 `--apply`）。

### 备份与恢复

需要同时备份：

- PostgreSQL：`docker compose exec -T db pg_dump -U "${MP_DB_USER:-medpowers}" "${MP_DB_NAME:-medpowers}" > backup.sql`
- 存储目录：`./data/storage`（推荐文件系统快照；5TB 级不要每天全量 rsync）

建议在低峰期先 `docker compose stop studio`，再执行 `pg_dump` + 快照，保证数据库与 Blob 同一时间点。恢复时先恢复 PostgreSQL，再挂回同一份 storage。

### 升级

```bash
git pull
docker compose up -d --build
docker compose logs -f studio
```

镜像启动时会自动跑 Alembic；升级前请先备份。

> 生产环境务必修改 `.env` 中的 `MP_DB_PASSWORD`、`MEDPOWERS_JWT_SECRET`、`MEDPOWERS_BOOTSTRAP_ADMIN_PASSWORD`。

## 2. 本地守护脚本（单机调试）

```bash
./scripts/start.sh          # 默认 SQLite；同步依赖 + 首次构建前端 + nohup 启动
./scripts/status.sh
./scripts/logs.sh
./scripts/stop.sh
```

- 默认 `0.0.0.0:8000`；通过 `MP_HOST`、`MP_PORT` 修改。
- 首次启动自动执行 `uv sync --frozen --extra dev`；前端 `dist` 不存在时执行 `npm ci && npm run build`。
- 强制重建前端：`./scripts/start.sh --build`。
- PID：`run/medpowers-studio.pid`；日志：`logs/medpowers-studio.log`。
- 配置：`cp backend/.env.example backend/.env`，按需修改数据库、存储根目录、JWT secret 等。
- 健康检查：`curl http://127.0.0.1:8000/api/health`。

本地模式默认使用 `backend/medpowers_studio.db` + `backend/storage/`，仅适合调试。

## 3. 从 v1（外部引用 / SQLite）迁移

v1 的 `Case.image_path` 可能是 `/ssd/...` 绝对路径，且 annotation 路径也在旧 storage 下。迁移步骤：

```bash
# 1) 停止旧服务（避免写入）
./scripts/stop.sh

# 2) 备份旧 SQLite 与 storage
cp backend/medpowers_studio.db backend/medpowers_studio.db.v1
cp -a backend/storage backend/storage.v1

# 3) 启动新的 PostgreSQL 容器（仅 db）
docker compose up -d db

# 4) 把 SQLite 复制到 PostgreSQL（空库或 --replace）
cd backend
export MEDPOWERS_DATABASE_URL=postgresql+psycopg://medpowers:<密码>@127.0.0.1:5432/medpowers
uv run python scripts/migrate_sqlite_to_postgres.py --sqlite medpowers_studio.db --replace

# 5) 把外部影像复制进内容寻址 Blob，并重写路径
#    注意：目标 storage 必须是 Compose 使用的 ../data/storage（或你的 MP_DATA_DIR）
export MEDPOWERS_STORAGE_ROOT=../data/storage
uv run python scripts/migrate_to_v2.py --dry-run
uv run python scripts/migrate_to_v2.py --apply --resume

# 6) 校验
uv run python scripts/verify_storage.py

# 7) 启动 Studio 容器
cd .. && docker compose up -d studio
```

- 迁移默认 **复制** 外部影像（不删除 `/ssd/data/spine/images`），确认无误后再自行清理旧数据。
- `migrate_to_v2.py` 默认 `--old-storage-root backend/storage`；如旧 storage 在其他位置请显式指定。
- 迁移完成后保留旧 SQLite、旧 storage、外部影像至少 30 天，便于回滚。
- 若旧库中存在 annotation 的绝对路径，脚本会把文件复制到新 storage 并改为相对 key。

## 4. 插件访问、鉴权与内网暴露

`medpowers` 插件与训练代码仓库通过 **API 访问令牌**读取平台数据，不保存网页密码。服务端提供：

- 网页「访问令牌」页手动创建 `mps_` 令牌；
- RFC 8628 设备码授权：插件申请设备码，用户在浏览器批准后插件自动领取令牌；
- Scope 限制：`studio:read`（元数据）、`studio:data`（下载影像/导出包）、`studio:dataset-manage`（数据集接入，只增不删）、`studio:write`（写入）；
- 令牌只保存 SHA-256 摘要，停用用户或重置密码自动撤销全部令牌。

接入契约、curl 示例与插件侧安全要求见 [`docs/api-access.md`](api-access.md)。

### 内网 HTTP 直连

默认监听 `0.0.0.0:8000`（Compose 映射 `${MP_BIND_HOST:-0.0.0.0}:${MP_PORT:-8000}:8000`），适合可信内网/VPN。

**多网卡主机**（同时有内网和公网地址）应只绑定内网地址：

```bash
# Docker Compose：在 .env 中设置
MP_BIND_HOST=192.168.113.201

# 本地脚本
MP_HOST=192.168.113.201 ./scripts/start.sh
```

```bash
# 只允许业务网段访问 8000（示例，按实际网段调整）
sudo ufw allow from 192.168.113.0/24 to any port 8000 proto tcp
```

建议配置：

```dotenv
MEDPOWERS_ENVIRONMENT=production
MEDPOWERS_JWT_SECRET=<至少 32 字节随机值>
MEDPOWERS_PUBLIC_BASE_URL=http://192.168.113.201:8000
MEDPOWERS_ALLOWED_HOSTS=["192.168.113.201","localhost","127.0.0.1"]
```

- `MEDPOWERS_PUBLIC_BASE_URL` 决定设备码授权链接；不设置时按请求 Host 推导，反向代理场景可能得到错误地址。
- `MEDPOWERS_ALLOWED_HOSTS` 为空表示不校验 Host；配置域名/IP 白名单可降低 Host 头伪造风险。
- `MEDPOWERS_ENVIRONMENT=production` 会拒绝默认 JWT secret，启动即失败。

### 跨不可信网络（可选 TLS）

如果训练仓库不在同一可信内网，请在 Studio 前加 HTTPS 反向代理，并将 `MEDPOWERS_PUBLIC_BASE_URL` 设为外部地址、`MEDPOWERS_ENABLE_HSTS=true`。反向代理需：

- 终止 TLS，转发到 `127.0.0.1:8000`；
- 保留 `Authorization` 头；
- 传递 `Host` / `X-Forwarded-Proto`；
- 限制请求体大小与超时（大文件建议走 `/imports` 路径导入，不要走 HTTP 上传）。

## 5. systemd（可选，服务器开机自启）

示例单元文件见 [`deploy/medpowers-studio.service.example`](../deploy/medpowers-studio.service.example)。

```bash
sudo cp deploy/medpowers-studio.service.example /etc/systemd/system/medpowers-studio.service
sudo systemctl daemon-reload
sudo systemctl enable --now medpowers-studio
sudo systemctl status medpowers-studio
```

单元文件使用 `Type=forking` + `PIDFile=run/medpowers-studio.pid`，由 `scripts/start.sh` 负责拉起和健康检查。

## 6. 开发模式（仅开发）

```bash
# 终端 A
cd backend && uv run uvicorn app.main:app --reload --port 8000

# 终端 B
cd frontend && npm run dev
```

前端访问 <http://127.0.0.1:5173>，Vite 代理 `/api` 到 8000。该模式依赖终端，不用于正式运行。

## 常见问题

- **端口被占用**：设置 `MP_PORT=8080` 或修改根目录 `.env`。
- **前端 404 或旧页面**：执行 `./scripts/start.sh --build` 或 `docker compose up -d --build`。
- **数据库连接失败**：确认 `db` 健康、`MP_DB_PASSWORD` 与 `MEDPOWERS_DATABASE_URL` 一致；入口脚本会重试 30 次。
- **导入提示空间不足**：扩容 `MP_DATA_DIR`，或临时降低 `MEDPOWERS_STORAGE_MIN_FREE_GB`（不推荐生产）。
- **忘记管理员密码**：删除数据库会重建初始化管理员（同时丢失全部数据）；或在数据库中已有其他管理员时由管理员重置。
- **SQLite 锁**：本地模式不要同时运行多个后端实例；生产使用 PostgreSQL + 单 Studio 容器。
- **容器文件属主**：容器内应用以 uid 10001 运行；`./data` 首次会被入口脚本修正顶层权限。迁移旧数据后如需手工维护，可用 `docker compose exec` 或 `sudo`。
