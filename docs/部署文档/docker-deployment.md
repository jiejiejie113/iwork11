# Docker 部署迁移指南

## 概述

本文档指导如何从 Windows 服务部署迁移到 Docker 部署。

> **当前生产部署**: iwork 通过分层架构部署：基础设施（MySQL/Redis/PostgreSQL）由 `DTD_nginx/docker/docker-compose.yml` 管理，iwork 应用由本仓库的 `docker-compose.yml` 管理，认证层（Keycloak + oauth2-proxy + Nginx）由 `docker-compose.keycloak.yml` 管理。所有容器通过 `docker_dkt-net` 网络通信。容器名 `DKT_iwork`。

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
# - ACCESS_DB_PASSWORD: Django系统库密码
# - LOCAL_DB_PASSWORD: 本地业务库密码
# - IWORK_DB_PASSWORD: 远程业务库密码
```

### 2. 构建并启动容器

```bash
# 1. 先启动基础设施（在 DTD_nginx/docker 目录下）
cd ../DTD_nginx/docker
docker compose up -d mysql redis iwork-redis postgres

# 2. 回到 iwork 目录，启动应用
cd ../../iwork

# 生产环境
docker compose up -d --build

# 本地开发环境
docker compose --env-file .env.local up -d --build

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f iwork
```

### 3. 验证服务

```bash
# 检查 iwork 是否正常运行
curl http://localhost:8000/

# 检查 MySQL 连接（基础设施容器）
docker exec DKT_mysql mysql -u root -p -e "SHOW DATABASES;"

# 检查 Redis 连接
docker exec DKT_iwork_redis redis-cli ping
```

### 4. 表结构迁移

Django 会在启动时自动执行数据库迁移。如果需要手动迁移：

```bash
# 进入 iwork 容器
docker compose exec iwork bash

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

生产环境已迁移至 Docker（容器名 `DKT_iwork`），不再使用 NSSM Windows 服务。

如果旧服务器上仍有 NSSM 服务残留，可用以下命令清理：

```powershell
# 停止 NSSM 服务（如存在）
Get-Service -Name "iwork-*" -ErrorAction SilentlyContinue | Stop-Service

# 删除 NSSM 服务注册
nssm remove iwork-django confirm 2>$null
nssm remove iwork-celery-worker confirm 2>$null
nssm remove iwork-celery-beat confirm 2>$null
```

> 注意：当前采用分层架构部署。基础设施（MySQL/Redis/PostgreSQL）由 `DTD_nginx/docker/docker-compose.yml` 管理，iwork 应用由本仓库的 `docker-compose.yml` 管理，认证层（Keycloak + oauth2-proxy + Nginx）由 `docker-compose.keycloak.yml` 管理。

## 常用命令

```bash
# 启动服务
docker compose up -d

# 停止服务
docker compose down

# 重启服务
docker compose restart

# 查看日志
docker compose logs -f iwork

# 进入容器
docker compose exec iwork bash

# 重新构建
docker compose up -d --build
```

## 数据持久化

- MySQL 数据: `DTD_nginx` 的 `docker_mysql_data` 卷
- Redis 数据: `DTD_nginx` 的 `docker_redis_data` 和 `docker_iwork_redis_data` 卷
- 应用日志: `./logs` 目录
- 静态文件: `./static` 目录

## 故障排查

### 服务无法启动

```bash
# 查看详细日志
docker compose logs iwork

# 检查环境变量
docker compose exec iwork env
```

### 数据库连接失败

```bash
# 检查 MySQL 状态（基础设施容器）
docker ps --filter name=DKT_mysql

# 测试连接
docker exec DKT_mysql mysql -u root -p
```

### Redis 连接失败

```bash
# 检查 Redis 状态
docker ps --filter name=DKT_iwork_redis

# 测试连接
docker exec DKT_iwork_redis redis-cli ping
```

## 回滚方案

如果需要回滚到 Windows 服务部署：

1. 停止 Docker 服务: `docker compose down`
2. 恢复原有 `.env` 配置
3. 重新注册 Windows 服务: `.\deploy.ps1 -ServiceOnly`
4. 启动服务: `.\start_dashboard.bat`
