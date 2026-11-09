#!/usr/bin/env bash
# 启动 MedPowers Studio（生产/长期运行模式）。
# 前端构建产物由 FastAPI 托管，只需一个后端进程；nohup 脱离当前终端。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
RUN_DIR="$ROOT/run"
LOG_DIR="$ROOT/logs"
PID_FILE="$RUN_DIR/medpowers-studio.pid"
HOST_FILE="$RUN_DIR/medpowers-studio.host"
LOG_FILE="$LOG_DIR/medpowers-studio.log"
HOST="${MP_HOST:-}"
if [[ -z "$HOST" && -f "$HOST_FILE" ]]; then
  # 复用上次绑定的地址，避免多网卡主机意外回到 0.0.0.0。
  HOST="$(cat "$HOST_FILE" 2>/dev/null || true)"
fi
HOST="${HOST:-0.0.0.0}"
PORT="${MP_PORT:-8000}"
FORCE_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --build) FORCE_BUILD=1 ;;
    -h|--help)
      echo "用法: $0 [--build]"
      echo "  --build   强制重新构建前端"
      echo "环境变量: MP_HOST（默认沿用上次绑定地址，首次为 0.0.0.0；多网卡主机建议绑定内网 IP）、MP_PORT（默认 8000）"
      exit 0
      ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "MedPowers Studio 已在运行（PID $EXISTING_PID，端口 $PORT）。"
    echo "如需重启：$0 stop 或先执行 scripts/stop.sh"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "错误：未找到 uv。请先安装 uv（https://docs.astral.sh/uv/）。" >&2
  exit 1
fi

echo "[1/3] 同步后端依赖..."
(cd "$BACKEND" && uv sync --frozen --extra dev)

if [[ "$FORCE_BUILD" -eq 1 || ! -f "$FRONTEND/dist/index.html" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "错误：需要构建前端，但未找到 npm。" >&2
    exit 1
  fi
  echo "[2/3] 构建前端..."
  (
    cd "$FRONTEND"
    if [[ ! -d node_modules ]]; then
      npm ci --no-audit --no-fund
    fi
    npm run build
  )
else
  echo "[2/3] 前端构建产物已存在，跳过构建（可用 --build 强制重建）。"
fi

echo "[3/3] 启动后端并托管前端..."
cd "$BACKEND"
export PYTHONUNBUFFERED=1
nohup "$BACKEND/.venv/bin/python" -m uvicorn app.main:app \
  --host "$HOST" --port "$PORT" \
  >> "$LOG_FILE" 2>&1 < /dev/null &
PID=$!
echo "$PID" > "$PID_FILE"
echo "$HOST" > "$HOST_FILE"
disown "$PID" 2>/dev/null || true

# 等待健康检查
HEALTH_HOST="$HOST"
if [[ "$HEALTH_HOST" == "0.0.0.0" ]]; then
  HEALTH_HOST="127.0.0.1"
fi
READY=0
for _ in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  if curl -fsS "http://${HEALTH_HOST}:${PORT}/api/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  echo "启动失败或健康检查超时。最近日志：" >&2
  tail -n 40 "$LOG_FILE" >&2 || true
  kill "$PID" 2>/dev/null || true
  rm -f "$PID_FILE"
  exit 1
fi

echo
echo "MedPowers Studio 已启动"
echo "  地址: http://${HEALTH_HOST}:${PORT}"
echo "  文档: http://${HEALTH_HOST}:${PORT}/docs"
echo "  PID : $PID"
echo "  日志: $LOG_FILE"
echo "  停止: $ROOT/scripts/stop.sh"
echo "  状态: $ROOT/scripts/status.sh"
