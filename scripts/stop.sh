#!/usr/bin/env bash
# 停止由 scripts/start.sh 启动的 MedPowers Studio。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/run/medpowers-studio.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "MedPowers Studio 未在运行（未找到 PID 文件）。"
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
  echo "进程不存在，清理 PID 文件。"
  rm -f "$PID_FILE"
  exit 0
fi

echo "正在停止 MedPowers Studio（PID $PID）..."
kill "$PID" 2>/dev/null || true
for _ in $(seq 1 15); do
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

if kill -0 "$PID" 2>/dev/null; then
  echo "进程未在 15 秒内退出，发送 SIGKILL。"
  kill -9 "$PID" 2>/dev/null || true
fi

rm -f "$PID_FILE"
echo "已停止。"
