#!/usr/bin/env bash
# 查看 MedPowers Studio 运行状态。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/run/medpowers-studio.pid"
HOST_FILE="$ROOT/run/medpowers-studio.host"
LOG_FILE="$ROOT/logs/medpowers-studio.log"
PORT="${MP_PORT:-8000}"
FILE_HOST="$(cat "$HOST_FILE" 2>/dev/null || true)"
HOST="${MP_HOST:-${FILE_HOST:-127.0.0.1}}"
if [[ "$HOST" == "0.0.0.0" || -z "$HOST" ]]; then
  HOST="127.0.0.1"
fi

if [[ ! -f "$PID_FILE" ]]; then
  echo "状态: 未运行（未找到 PID 文件）"
  exit 1
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
  echo "状态: 未运行（PID 文件存在但进程已退出）"
  exit 1
fi

if curl -fsS "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
  echo "状态: 运行中"
else
  echo "状态: 进程存在（PID $PID），但健康检查未通过"
fi
echo "  PID : $PID"
echo "  地址: http://${HOST}:${PORT}"
echo "  日志: $LOG_FILE"
