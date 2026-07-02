# ADR 004 — Docker 容器分层编排

> 日期：2026-07-02 | 状态：已实施

---

## 背景

iwork 项目的 Docker 编排存在三个问题：

1. **`DKT_iwork` 重复定义**：iwork 自己的 `docker-compose.yml` 和 DTD_nginx 基础设施的 `docker-compose.yml` 都定义了 `DKT_iwork` 服务，配置可能漂移
2. **MySQL/Redis 重复实例**：iwork 独立起 `iwork-mysql`(3307) 和 `iwork-redis`(6379)，但基础设施层已有 `DKT_mysql` 和 `DKT_iwork_redis`
3. **无本地/生产模式切换**：iwork 只有一个 `.env`，写死 Docker 容器名，无法在本地开发和生产部署之间切换

## 决策

采用**三层分层架构**，所有容器统一到 `docker_dkt-net` 网络：

```
基础设施层 (DTD_nginx/docker/docker-compose.yml)
  ├── DKT_postgres      PostgreSQL（Portal/Keycloak/Fabric 共用）
  ├── DKT_redis         共享 Redis 缓存
  ├── DKT_mysql         MySQL（iwork + pattern 共用）
  ├── DKT_iwork_redis   iwork 专用 Redis
  ├── DKT_fabric        面料分析（外部依赖）
  └── DKT_pattern       版单统计（外部依赖）

认证层 (DTD_nginx/docker/docker-compose.keycloak.yml)
  ├── DKT_kc_keycloak   Keycloak IAM
  ├── DKT_kc_oauth2proxy OIDC 认证代理
  ├── DKT_kc_portal     Django 导航首页
  └── DKT_kc_nginx      Nginx 反向代理 + TLS

应用层 (iwork/docker-compose.yml)
  └── DKT_iwork         iwork 应用（仅此一个服务）
```

## 具体变更

### 删除的资源

| 资源 | 原因 |
|------|------|
| `iwork-mysql` 容器 | 改用 `DKT_mysql` |
| `iwork-redis` 容器 | 改用 `DKT_iwork_redis` |
| DTD_nginx 中的 `DKT_iwork` 服务定义 | 避免与 iwork 自己的 compose 冲突 |
| `iwork_mysql_data` / `iwork_redis_data` 数据卷 | 数据已迁移到 DKT_mysql |

### 配置拆分

iwork 的 `.env` 拆为两个：

| 文件 | 用途 | DEBUG | ALLOWED_HOSTS |
|------|------|-------|---------------|
| `iwork/.env` | 生产部署 | False | dktportal.dongming.local,... |
| `iwork/.env.local` | 本地开发 | True | localhost,127.0.0.1,... |

通过 compose 变量 `IWORK_ENV_FILE` 切换：

```bash
# 生产
docker compose up -d

# 本地
docker compose --env-file .env.local up -d
```

## 影响

- iwork 不再能单条命令自给自足启动，必须先启动 DTD_nginx 的基础设施容器
- MySQL 和 Redis 端口不再暴露到宿主机（本地调试需额外配置）
- 本地开发时 iwork 加入 `docker_dkt-net`，与生产网络拓扑一致
- 数据库初始化脚本（`02-init-iwork.sql`）密码需与 iwork `.env` 保持一致

## 关联

- ADR 003：Remote-User 认证架构（TrustedProxyMiddleware）
- `docs/部署文档/docker-deployment.md`
- `docs/superpowers/specs/2026-07-02-docker-orchestration-redesign.md`
