#!/usr/bin/env bash
# 实时查看 MedPowers Studio 日志。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$ROOT/logs/medpowers-studio.log"

if [[ ! -f "$LOG_FILE" ]]; then
  echo "日志文件不存在：$LOG_FILE"
  exit 1
fi

tail -n 200 -f "$LOG_FILE"
