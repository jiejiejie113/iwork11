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

iwork 采用**两层 `.env` 机制**：

| 层级 | 文件 | 用途 | 内容 |
|------|------|------|------|
| **Compose 层**（项目根目录） | `.env` | 为 `docker compose` 提供变量插值 | `IWORK_ENV_FILE=iwork/.env` |
| **Compose 层**（项目根目录） | `.env.local` | 本地开发时覆盖 compose 变量 | `IWORK_ENV_FILE=iwork/.env.local` |
| **容器层**（`iwork/` 目录） | `iwork/.env` | 生产环境 → 容器内环境变量 | `DEBUG=False`, 完整域名白名单 |
| **容器层**（`iwork/` 目录） | `iwork/.env.local` | 本地开发 → 容器内环境变量 | `DEBUG=True`, localhost 白名单 |

**切换流程**：

```bash
# 生产：compose 读取根 .env → IWORK_ENV_FILE=iwork/.env → 容器加载 iwork/.env
docker compose up -d

# 本地：compose 读取根 .env.local → IWORK_ENV_FILE=iwork/.env.local → 容器加载 iwork/.env.local
docker compose --env-file .env.local up -d
```

`docker-compose.yml` 中的关键行：
```yaml
env_file:
  - ${IWORK_ENV_FILE:-iwork/.env}
```

根 `.env` 和 `.env.local` 仅包含 `IWORK_ENV_FILE` 一个变量，职责单一：告诉 compose 去哪个路径找容器的 env 文件。

**容器环境变量对比**：

| 变量 | `iwork/.env`（生产） | `iwork/.env.local`（本地） |
|------|---------------------|--------------------------|
| `DJANGO_DEBUG` | `False` | `True` |
| `DJANGO_ALLOWED_HOSTS` | `dktportal.dongming.local,...` | `localhost,127.0.0.1,...` |
| `ACCESS_DB_HOST` | `mysql` | `mysql` |
| `REDIS_HOST` | `iwork-redis` | `iwork-redis` |

> 注：`ACCESS_DB_HOST=mysql` 和 `REDIS_HOST=iwork-redis` 使用的是 DTD_nginx compose 中的 **服务名**（非容器名 `DKT_mysql`/`DKT_iwork_redis`）。同一 `docker_dkt-net` 网络下，Docker 内置 DNS 可通过服务名或容器名互相解析，两种写法等价。这里统一用服务名，与 DTD_nginx 的 compose 定义保持一致。

## 影响

- iwork 不再能单条命令自给自足启动，必须先启动 DTD_nginx 的基础设施容器
- MySQL 和 Redis 端口不再暴露到宿主机（本地调试需额外配置）
- 本地开发时 iwork 加入 `docker_dkt-net`，与生产网络拓扑一致
- 数据库初始化脚本（`02-init-iwork.sql`）密码需与 iwork `.env` 保持一致
- 新增项目根目录 `.env` / `.env.local` 文件（仅含 `IWORK_ENV_FILE` 变量），`.gitignore` 需忽略根 `.env.local`
- 容器间通信主机名使用 DTD_nginx compose 的**服务名**（`mysql`、`iwork-redis`），而非容器名（`DKT_mysql`、`DKT_iwork_redis`），两种写法在 `docker_dkt-net` 中等价

## 关联

- ADR 003：Remote-User 认证架构（TrustedProxyMiddleware）
- `docs/部署文档/docker-deployment.md`
- `docs/superpowers/specs/2026-07-02-docker-orchestration-redesign.md`
