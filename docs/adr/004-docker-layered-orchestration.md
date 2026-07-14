# ADR 004: Docker 分层编排与中央密钥

> 日期：2026-07-02 | 更新：2026-07-14 | 状态：已实施

## 背景

iwork 曾重复定义 MySQL、Redis 和应用容器，并用多层 `.env` 保存连接密码。重复资源和重复密钥使本地与服务器配置容易漂移。

## 决策

所有容器加入外部网络 `docker_dkt-net`，按所有权分为三层：

```text
基础设施层 DTD_nginx/docker/docker-compose.yml
  DKT_postgres, DKT_redis, DKT_mysql, DKT_iwork_redis

认证层 DTD_nginx/docker/docker-compose.keycloak.yml
  DKT_kc_keycloak, DKT_kc_oauth2proxy, DKT_kc_portal, DKT_kc_nginx

应用层 iwork/docker-compose.yml
  DKT_iwork
```

iwork 仓库不再创建 MySQL 或 Redis。`DKT_iwork` 通过网络别名 `mysql` 和 `iwork-redis` 连接基础设施。

## 配置边界

仓库内可提交的 profile 只含非敏感值：

| 文件 | 用途 |
|------|------|
| `env/local.env` | 本地调试、localhost 白名单 |
| `env/production.env` | 服务器域名、生产调试开关 |

两个仓库共用一份不提交的中央密钥：

| 环境 | 文件 |
|------|------|
| 本机 | `C:\Users\lipengfei\ZCodeProject\dkt-secrets.env` |
| 服务器 | `D:\DM\dkt-secrets.env` |

Compose 通过 `DKT_ENVIRONMENT` 选择 profile，并显式注入 `IWORK_DJANGO_SECRET_KEY`、`IWORK_APP_DB_PASSWORD` 和 `IWORK_DB_PASSWORD`。

```powershell
# 本地
docker compose --env-file .\env\local.env `
  --env-file ..\dkt-secrets.env up -d --build iwork

# 服务器 D:\DM\iwork
docker compose --env-file .\env\production.env `
  --env-file D:\DM\dkt-secrets.env up -d --build iwork
```

## 影响

- 启动 iwork 前必须确保 `DKT_mysql`、`DKT_iwork_redis` 和外部网络已存在；
- 密钥只手工传输一次，profile 可以随代码发布；
- 初始化 MySQL 用户时，基础设施层和 iwork 使用同一个 `IWORK_APP_DB_PASSWORD`；
- 普通重建不删除共享数据库、Redis 或 Keycloak 数据卷；
- `env/` 目录是配置目录，不是 Python 虚拟环境，必须由 `.gitignore` 显式放行两个 profile。

## 关联

- DTD_nginx ADR 0013：中央密钥文件
- `docs/部署文档/docker-deployment.md`
- `docs/部署文档/迁移操作手册.md`
