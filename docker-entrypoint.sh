#!/bin/sh
# MedPowers Studio 容器入口：修正数据卷权限、执行数据库迁移、启动应用。
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/storage 2>/dev/null || true
    # 只修正数据卷顶层，避免 5TB 级目录递归 chown。
    chown app:app /data/storage 2>/dev/null || true
    exec gosu app "$0" "$@"
fi

cd /app/backend

attempt=0
until ./.venv/bin/alembic upgrade head; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "数据库迁移失败，已重试 ${attempt} 次" >&2
        exit 1
    fi
    echo "等待数据库就绪（${attempt}/30）..." >&2
    sleep 2
done

exec "$@"
