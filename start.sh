#!/bin/bash
set -e

echo "=== iwork Docker 启动脚本 ==="

# 等待 MySQL 就绪
echo "等待 MySQL 就绪..."
while ! python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('mysql', 3306)); s.close()" 2>/dev/null; do
    sleep 2
done
echo "MySQL 已就绪"

# 等待 Redis 就绪
echo "等待 Redis 就绪..."
while ! python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('iwork-redis', 6379)); s.close()" 2>/dev/null; do
    sleep 2
done
echo "Redis 已就绪"

# 执行数据库迁移
echo "执行数据库迁移..."
python manage.py migrate --database=default --noinput
python manage.py migrate --database=iwork_local --noinput 2>/dev/null || true

# 收集静态文件
echo "收集静态文件..."
python manage.py collectstatic --noinput 2>/dev/null || true

# 启动 Celery Worker（后台）
echo "启动 Celery Worker..."
celery -A iwork worker -l info -P solo &
CELERY_WORKER_PID=$!

# 启动 Celery Beat（后台）
echo "启动 Celery Beat..."
celery -A iwork beat -l info &
CELERY_BEAT_PID=$!

# 启动 Django（前台，ASGI 模式）
echo "启动 Django (Uvicorn ASGI)..."
exec uvicorn iwork.asgi:application \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --timeout-keep-alive 120 \
    --access-log \
    --log-level info
