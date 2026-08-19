#!/bin/bash
# 使用 LF 行尾，供 Linux 容器直接执行。
set -e

# bind mount（logs/static）里可能有历史 root 属主的文件，非 root 进程无法追加。
# 必须以 root 修正权限后再降权；chown 失败时放宽权限兜底，保证日志可写。
chown -R iwork:iwork /app/logs 2>/dev/null || chmod -R a+rw /app/logs 2>/dev/null || true
chown -R iwork:iwork /app/static 2>/dev/null || chmod -R a+rw /app/static 2>/dev/null || true

# 整个应用栈（uvicorn/celery/beat/migrations）以非 root 用户运行，
# 消除 Celery superuser 警告并满足最小权限。
exec setpriv --reuid=10001 --regid=10001 --init-groups bash /app/start.sh
