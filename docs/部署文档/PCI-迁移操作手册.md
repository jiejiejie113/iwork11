# iwork 服务器迁移操作手册

> 平台：Windows Server | 最后更新：2026-07-14

## 1. 迁移原则

- 只部署 `Keycloak` 分支；`main` 是历史兼容分支。
- Portal 与 iwork 共用 `D:\DM\dkt-secrets.env`，只手工传输这一份密钥文件。
- 代码仓库不包含真实密钥和 `sqlite/production_orders.db`。
- 先备份数据，再部署基础设施、认证层和 iwork。
- 普通迁移和重建不删除 Docker 数据卷。

## 2. 迁移前备份

至少保存：

1. MySQL 的 `iwork_system`、`iwork_local` 及相关用户授权；
2. PostgreSQL 的 Portal/Keycloak 数据；
3. `D:\DM\dkt-secrets.env`；
4. 必要的 `sqlite/production_orders.db` 导入源；
5. 当前部署提交号和容器清单。

```powershell
git -C D:\DM\iwork rev-parse HEAD
git -C D:\DM\DTD_nginx rev-parse HEAD
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

数据库备份应使用组织现有备份流程和受控目录，本手册不在命令行中展开或记录密码。

## 3. 新服务器准备

```powershell
docker version
docker compose version
git --version
Test-NetConnection -ComputerName 192.168.4.19 -Port 3306
```

准备目录：

```text
D:\DM\DTD_nginx
D:\DM\iwork
D:\DM\dkt-secrets.env
```

首次部署时创建共享外部网络；已存在则跳过：

```powershell
if (-not (docker network ls --filter name=^docker_dkt-net$ --format "{{.Name}}")) {
    docker network create docker_dkt-net
}
```

把本机中央密钥安全传输到 `D:\DM\dkt-secrets.env`，限制普通用户读取。不要通过 Git、聊天记录或镜像传输。

```powershell
icacls D:\DM\dkt-secrets.env /inheritance:r /grant:r "$env:USERDOMAIN\$env:USERNAME:(F)" "*S-1-5-18:(F)" "*S-1-5-32-544:(F)"
```

## 4. 获取代码

```powershell
git -C D:\DM\DTD_nginx fetch origin
git -C D:\DM\DTD_nginx checkout feature/keycloak-migration
git -C D:\DM\DTD_nginx pull --ff-only

git -C D:\DM\iwork fetch origin
git -C D:\DM\iwork checkout Keycloak
git -C D:\DM\iwork pull --ff-only origin Keycloak
```

Portal 的部署分支若已调整，以服务器发布约定为准；不要在服务器工作区现场合并开发分支。

## 5. 校验配置

```powershell
cd D:\DM\DTD_nginx
.\scripts\Test-Secrets.ps1 -Target all -SecretsFile D:\DM\dkt-secrets.env

docker compose --env-file .\docker\env\production.env `
  --env-file D:\DM\dkt-secrets.env `
  -f .\docker\docker-compose.yml config --quiet

docker compose --env-file .\docker\env\production.env `
  --env-file D:\DM\dkt-secrets.env `
  -f .\docker\docker-compose.keycloak.yml config --quiet

cd D:\DM\iwork
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env config --quiet
```

任何一个命令失败都应停止部署，先补齐或修正配置。

## 6. 启动顺序

### 6.1 基础设施

```powershell
cd D:\DM\DTD_nginx
docker compose --env-file .\docker\env\production.env `
  --env-file D:\DM\dkt-secrets.env `
  -f .\docker\docker-compose.yml -p docker `
  up -d postgres redis mysql iwork-redis
```

等待 PostgreSQL、MySQL 和 Redis 变为 healthy。

### 6.2 认证层

```powershell
.\scripts\Sync-Keycloak-Secrets.ps1 -SecretsFile D:\DM\dkt-secrets.env

docker compose --env-file .\docker\env\production.env `
  --env-file D:\DM\dkt-secrets.env `
  -f .\docker\docker-compose.keycloak.yml -p dkt-keycloak `
  up -d --build keycloak oauth2-proxy portal nginx
```

不要删除 Keycloak 数据卷来“刷新” Realm。结构变更需要单独迁移和备份。

### 6.3 iwork

```powershell
cd D:\DM\iwork
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env `
  up -d --build iwork
```

## 7. 可选数据导入

只有 `iwork_local.production_orders` 尚未初始化时，才手工上传 `sqlite/production_orders.db` 并执行：

```powershell
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env exec iwork `
  python manage.py import_production_orders
```

该 SQLite 文件已被 Git 忽略。导入完成后，运行时数据源是 MySQL。

## 8. 验证

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
docker exec DKT_kc_nginx nginx -t
docker exec DKT_iwork python manage.py check

curl.exe -f -I https://dktportal.dongming.local/
curl.exe -f -I https://dktportal.dongming.local/iwork/
curl.exe -f https://auth.dktportal.dongming.local/realms/dkt/.well-known/openid-configuration
```

还需使用实际账号完成一次登录，确认：

- 浏览器跳转到生产 Keycloak 域名；
- Portal 和 iwork 都能读取同一登录会话；
- iwork 实时页建立 SSE 连接；
- Celery worker/beat 无数据库或 Redis 错误。

## 9. 回滚

应用回滚使用上一个已验证提交重新构建，不修改数据库卷：

```powershell
git -C D:\DM\iwork checkout <已验证提交>
cd D:\DM\iwork
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env up -d --build iwork
```

涉及数据库结构或密钥的回滚必须使用对应备份和变更记录。不要执行 `docker compose down -v`。
