# iwork Docker 部署指南

> 最后更新：2026-07-14

## 架构

iwork 只拥有 `DKT_iwork` 应用容器。MySQL、Redis、认证层和 Nginx 由相邻的 `DTD_nginx` 仓库管理，全部加入外部网络 `docker_dkt-net`。

| 层 | Compose 文件 | 主要容器 |
|----|--------------|----------|
| 基础设施 | `DTD_nginx/docker/docker-compose.yml` | `DKT_mysql`、`DKT_iwork_redis` |
| 认证入口 | `DTD_nginx/docker/docker-compose.keycloak.yml` | Keycloak、oauth2-proxy、Portal、Nginx |
| 应用 | `iwork/docker-compose.yml` | `DKT_iwork` |

## 配置

非敏感 profile 位于 `env/local.env` 和 `env/production.env`。真实密钥只保存在两个仓库共同上级目录的 `dkt-secrets.env`：

- 本地：`C:\Users\lipengfei\ZCodeProject\dkt-secrets.env`
- 服务器：`D:\DM\dkt-secrets.env`

不要把密钥复制回仓库内的 profile，也不要把整个密钥文件注入容器。Compose 只显式传入 iwork 所需的三个值。

## 本地启动

推荐使用 Portal 仓库的一键脚本：

```powershell
cd C:\Users\lipengfei\ZCodeProject\DTD_nginx
.\scripts\Rebuild-Local.ps1 -Target iwork
```

手工方式：

```powershell
cd C:\Users\lipengfei\ZCodeProject\iwork
docker compose --env-file .\env\local.env `
  --env-file ..\dkt-secrets.env up -d --build iwork
docker logs DKT_iwork --tail 100
docker exec DKT_kc_nginx nginx -t
docker exec DKT_kc_nginx nginx -s reload
```

## 生产启动

在 `D:\DM\iwork` 执行：

```powershell
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env up -d --build iwork
```

应用启动脚本自动执行 default 和 iwork_local 数据库迁移、收集静态文件，并启动 Celery worker、Celery beat 和 Uvicorn。

## 验证

```powershell
docker ps --filter "name=DKT_iwork"
docker logs DKT_iwork --tail 100
curl.exe -s -o NUL -w "%{http_code}" http://localhost:8080/iwork/
docker exec DKT_iwork python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/'); assert r.status == 200"
docker exec DKT_iwork python manage.py check
docker exec DKT_iwork python manage.py migrate --check --database=default
docker exec DKT_iwork python manage.py migrate --check --database=iwork_local
```

期望容器内部检查返回 `200`，认证入口未登录时返回 `302`。端口 8000 不发布到宿主机，只允许 Nginx 通过 `docker_dkt-net` 访问。

## 生产工单导入

`sqlite/production_orders.db` 只是一份人工传输的导入源，已被 Git 忽略，不是运行时数据库。需要初始化 `iwork_local.production_orders` 时，将文件放到服务器 `D:\DM\iwork\sqlite\production_orders.db`，然后执行：

```powershell
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env exec iwork `
  python manage.py import_production_orders
```

导入完成后业务读取 MySQL，不再依赖 SQLite 文件。

## 日常操作

```powershell
docker logs DKT_iwork --tail 100
docker restart DKT_iwork
docker exec DKT_iwork python manage.py check
```

普通发布不要执行 `docker compose down -v`。共享数据卷由基础设施层管理，删除卷会造成不可逆数据丢失。

## 故障排查

| 现象 | 检查 |
|------|------|
| 启动后持续等待 MySQL | `DKT_mysql` 是否运行、`docker_dkt-net` 是否存在 |
| 启动后持续等待 Redis | `DKT_iwork_redis` 是否运行 |
| Django 报缺少环境变量 | 是否同时传入 profile 和中央密钥文件 |
| 经 Nginx 返回 502 | 容器状态、Nginx 日志，并在 `nginx -t` 后 reload |
| SSE 无消息 | Redis、Celery 日志及 Nginx `proxy_buffering off` |
