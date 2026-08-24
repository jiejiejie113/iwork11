#!/bin/bash
# 使用 LF 行尾，供 Linux 容器直接执行。
set -e

echo "=== iwork Docker Startup Script ==="

# Wait for MySQL
echo "Waiting for MySQL..."
while ! python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('mysql', 3306)); s.close()" 2>/dev/null; do
    sleep 2
done
echo "MySQL is ready"

# Wait for Redis
echo "Waiting for Redis..."
while ! python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('iwork-redis', 6379)); s.close()" 2>/dev/null; do
    sleep 2
done
echo "Redis is ready"

if [ "${IWORK_CONTAINER_ROLE:-web}" = "alert-worker" ]; then
    echo "Starting isolated Alert Worker..."
    IWORK_PROCESS_ROLE=celery exec celery -A iwork worker -l info -P solo -Q alerts -n "alerts@%h"
fi

# 执行数据库迁移
if [ "${IWORK_RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "正在执行数据库迁移..."
    IWORK_PROCESS_ROLE=management python manage.py migrate --database=default --noinput
    IWORK_PROCESS_ROLE=management python manage.py migrate --database=iwork_local --noinput
elif [ "${IWORK_RUN_MIGRATIONS}" = "false" ]; then
    echo "根据部署策略跳过数据库迁移"
else
    echo "IWORK_RUN_MIGRATIONS配置值无效：${IWORK_RUN_MIGRATIONS}" >&2
    exit 64
fi

# Collect static files
echo "Collecting static files..."
IWORK_PROCESS_ROLE=management python manage.py collectstatic --noinput 2>/dev/null || true

# Start Celery Worker (background)
echo "Starting Celery Worker..."
IWORK_PROCESS_ROLE=celery celery -A iwork worker -l info -P solo -Q celery -n "realtime@%h" &
CELERY_WORKER_PID=$!

# Start Celery Beat (background)
echo "Starting Celery Beat..."
IWORK_PROCESS_ROLE=celery celery -A iwork beat -l info &
CELERY_BEAT_PID=$!

# Start Django (foreground, ASGI mode)
echo "Starting Django (Uvicorn ASGI)..."
IWORK_PROCESS_ROLE=web exec uvicorn iwork.asgi:application \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --timeout-keep-alive 120 \
    --access-log \
    --log-level info
