# Docker 部署迁移指南

## 概述

本文档指导如何从 Windows 服务部署迁移到 Docker 部署。

## 前置条件

- Docker Desktop 已安装并运行
- Docker Compose 已安装
- 现有 MySQL 数据已备份（如需要）

## 迁移步骤

### 1. 准备环境变量

```bash
# 复制环境变量模板
copy iwork\.env.example iwork\.env

# 编辑 .env 文件，填入实际配置
# 特别注意：
# - MYSQL_ROOT_PASSWORD: MySQL root密码
# - ACCESS_DB_PASSWORD: Django系统库密码
# - LOCAL_DB_PASSWORD: 本地业务库密码
# - IWORK_DB_PASSWORD: 远程业务库密码
```

### 2. 构建并启动容器

```bash
# 构建镜像并启动所有服务
docker compose up -d --build

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f django
```

### 3. 验证服务

```bash
# 检查 Django 是否正常运行
curl http://localhost:8000/

# 检查 MySQL 连接
docker compose exec mysql mysql -u root -p -e "SHOW DATABASES;"

# 检查 Redis 连接
docker compose exec redis redis-cli ping
```

### 4. 表结构迁移

Django 会在启动时自动执行数据库迁移。如果需要手动迁移：

```bash
# 进入 Django 容器
docker compose exec django bash

# 执行迁移
python manage.py migrate --database=default
python manage.py migrate --database=iwork_local

# 退出容器
exit
```

### 5. 更新 Nginx 配置

更新现有 Nginx 配置，将请求代理到 Docker 容器：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /path/to/iwork/static/;
    }
}
```

### 6. 停止旧服务

如果之前使用 Windows 服务（NSSM），需要停止并删除：

```powershell
# 停止服务
.\stop_services.ps1

# 或手动停止
nssm stop iwork-django
nssm stop iwork-celery-worker
nssm stop iwork-celery-beat

# 删除服务
nssm remove iwork-django confirm
nssm remove iwork-celery-worker confirm
nssm remove iwork-celery-beat confirm
```

## 常用命令

```bash
# 启动服务
docker compose up -d

# 停止服务
docker compose down

# 重启服务
docker compose restart

# 查看日志
docker compose logs -f

# 进入容器
docker compose exec django bash

# 重新构建
docker compose up -d --build
```

## 数据持久化

- MySQL 数据: `mysql_data` 卷
- Redis 数据: `redis_data` 卷
- 应用日志: `./logs` 目录
- 静态文件: `./static` 目录

## 故障排查

### 服务无法启动

```bash
# 查看详细日志
docker compose logs django

# 检查环境变量
docker compose exec django env
```

### 数据库连接失败

```bash
# 检查 MySQL 状态
docker compose ps mysql

# 测试连接
docker compose exec mysql mysql -u root -p
```

### Redis 连接失败

```bash
# 检查 Redis 状态
docker compose ps redis

# 测试连接
docker compose exec redis redis-cli ping
```

## 回滚方案

如果需要回滚到 Windows 服务部署：

1. 停止 Docker 服务: `docker compose down`
2. 恢复原有 `.env` 配置
3. 重新注册 Windows 服务: `.\deploy.ps1 -ServiceOnly`
4. 启动服务: `.\start_dashboard.bat`
