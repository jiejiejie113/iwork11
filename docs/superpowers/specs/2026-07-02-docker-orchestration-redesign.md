# Docker 容器编排重构设计

> 状态：草稿 | 日期：2026-07-02 | 作者：Claude + lipengfei

---

## 一、当前状态

### 1.1 文件分布

```
iwork/
├── docker-compose.yml          ← iwork 独立部署
└── iwork/.env                  ← 写死 Docker 容器名，无本地/生产区分

DTD_nginx/docker/
├── docker-compose.yml          ← 基础设施 + 应用（含 DKT_iwork 重复定义）
├── docker-compose.keycloak.yml ← Keycloak 认证栈
├── .env                        ← 生产环境变量
└── .env.local                  ← 本地开发环境变量（仅 keycloak compose 用）
```

### 1.2 当前容器清单

| 容器名                  | 来源 compose                                                     | 网络                    | 端口暴露      | 问题                                |
| ----------------------- | ---------------------------------------------------------------- | ----------------------- | ------------- | ----------------------------------- |
| `DKT_postgres`        | DTD_nginx/docker-compose.yml                                     | dkt-net                 | 5432          | —                                  |
| `DKT_redis`           | DTD_nginx/docker-compose.yml                                     | dkt-net                 | 6379          | —                                  |
| `DKT_mysql`           | DTD_nginx/docker-compose.yml                                     | dkt-net                 | —            | —                                  |
| `DKT_fabric`          | DTD_nginx/docker-compose.yml                                     | dkt-net                 | —            | —                                  |
| `DKT_pattern`         | DTD_nginx/docker-compose.yml                                     | dkt-net                 | —            | —                                  |
| `DKT_iwork_redis`     | DTD_nginx/docker-compose.yml                                     | dkt-net                 | —            | —                                  |
| **`DKT_iwork`** | DTD_nginx/docker-compose.yml**+** iwork/docker-compose.yml | dkt-net + iwork_default | 8000          | ⚠️**两个 compose 重复定义** |
| `iwork-mysql`         | iwork/docker-compose.yml                                         | iwork_default           | 3307→3306    | ⚠️ 与 DKT_mysql 功能重复          |
| `iwork-redis`         | iwork/docker-compose.yml                                         | iwork_default           | 6379          | ⚠️ 与 DKT_iwork_redis 功能重复    |
| `DKT_kc_keycloak`     | keycloak.yml                                                     | dkt-net                 | —            | —                                  |
| `DKT_kc_oauth2proxy`  | keycloak.yml                                                     | dkt-net                 | —            | —                                  |
| `DKT_kc_portal`       | keycloak.yml                                                     | dkt-net                 | —            | —                                  |
| `DKT_kc_nginx`        | keycloak.yml                                                     | dkt-net                 | 443, 80, 8080 | —                                  |

### 1.3 当前存在的问题

#### 问题 1：DKT_iwork 重复定义

两个 compose 文件都定义了 `DKT_iwork` 服务，构建上下文和配置不同：

| 配置项     | iwork/docker-compose.yml | DTD_nginx/docker-compose.yml   |
| ---------- | ------------------------ | ------------------------------ |
| context    | `.`（iwork 根目录）    | `../../iwork`                |
| env_file   | `.env`（项目根目录）   | `../../iwork/iwork/.env`     |
| MYSQL_HOST | mysql（自己的 mysql）    | mysql（DKT_mysql）             |
| REDIS_HOST | redis（自己的 redis）    | iwork-redis（DKT_iwork_redis） |
| volumes    | `./logs`, `./static` | `iwork_data`, `iwork_logs` |

哪个先启动就用哪个定义，另一个文件的修改会被忽略，极易造成配置漂移。

#### 问题 2：MySQL/Redis 重复实例

iwork 独立 compose 自己起了 `iwork-mysql`（3307）和 `iwork-redis`（6379），但基础设施层已经有 `DKT_mysql` 和 `DKT_iwork_redis`。本地开发时白白多跑两个容器。

#### 问题 3：iwork 无 .env.local

iwork 只有一个 `.env`，里面的 `DJANGO_DEBUG=True`、白名单都是本地值，实际上充当了 `.env.local` 的角色。没有真正的生产配置模板。

#### 问题 4：.env 路径不一致

- iwork compose 读项目根目录的 `.env`
- Django settings 读 `iwork/.env`
- DTD_nginx 的 iwork 服务读 `../../iwork/iwork/.env`

三个地方找 .env，让人困惑。

---

## 二、修改后方案

### 2.1 设计原则

1. **单一职责**：每个容器只有一个 compose 文件定义它
2. **分层架构**：基础设施层 + 应用层 + 认证层，各层独立 compose
3. **本地/生产一键切换**：通过 `.env` vs `.env.local` 区分
4. **命名对齐**：全部 `DKT_<模块>_<服务>` 格式

### 2.2 文件结构

```
iwork/
├── docker-compose.yml          ← [修改] 仅 iwork 应用 + 专用 Redis（不再含 mysql）
├── Dockerfile                  ← [不变]
├── iwork/
│   ├── .env.example            ← [修改] 纯生产模板（DEBUG=False，完整域名）
│   ├── .env                    ← [新增到 gitignore] 本地实际配置
│   └── .env.local              ← [新增] 本地开发覆盖（DEBUG=True，localhost）
└── .dockerignore               ← [不变]

DTD_nginx/docker/
├── docker-compose.yml          ← [修改] 基础设施层（postgres/redis/mysql），移除 DKT_iwork
├── docker-compose.keycloak.yml ← [不变] Keycloak 认证栈
├── .env                        ← [不变] 生产环境变量
└── .env.local                  ← [不变] 本地开发环境变量（keycloak compose 用）
```

### 2.3 修改后容器清单

| 容器名                 | 所属 compose                       | 网络                                    | 端口          |
| ---------------------- | ---------------------------------- | --------------------------------------- | ------------- |
| **基础设施层**   |                                    |                                         |               |
| `DKT_postgres`       | DTD_nginx/docker-compose.yml       | dkt-net                                 | 5432          |
| `DKT_redis`          | DTD_nginx/docker-compose.yml       | dkt-net                                 | 6379          |
| `DKT_mysql`          | DTD_nginx/docker-compose.yml       | dkt-net                                 | —            |
| `DKT_iwork_redis`    | DTD_nginx/docker-compose.yml       | dkt-net                                 | —            |
| **应用层**       |                                    |                                         |               |
| `DKT_iwork`          | **iwork/docker-compose.yml** | dkt-net（生产） / iwork_default（本地） | 8000          |
| `DKT_fabric`         | DTD_nginx/docker-compose.yml       | dkt-net                                 | —            |
| `DKT_pattern`        | DTD_nginx/docker-compose.yml       | dkt-net                                 | —            |
| **认证层**       |                                    |                                         |               |
| `DKT_kc_keycloak`    | docker-compose.keycloak.yml        | dkt-net                                 | —            |
| `DKT_kc_oauth2proxy` | docker-compose.keycloak.yml        | dkt-net                                 | —            |
| `DKT_kc_portal`      | docker-compose.keycloak.yml        | dkt-net                                 | —            |
| `DKT_kc_nginx`       | docker-compose.keycloak.yml        | dkt-net                                 | 443, 80, 8080 |

### 2.4 删除的容器

| 容器名               | 原因                                        |
| -------------------- | ------------------------------------------- |
| ~~`iwork-mysql`~~ | 本地开发直接用`DKT_mysql`，不单独起       |
| ~~`iwork-redis`~~ | 本地开发直接用`DKT_iwork_redis`，不单独起 |

### 2.5 .env 拆分对比

**iwork/iwork/.env（生产模板）**：

```env
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=dktportal.dongming.local,auth.dktportal.dongming.local
REDIS_HOST=DKT_iwork_redis
ACCESS_DB_HOST=DKT_mysql
...
```

**iwork/iwork/.env.local（本地覆盖）**：

```env
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,iwork,iwork:8000
# REDIS_HOST/ACCESS_DB_HOST 等继承 .env 的 Docker 容器名（本地也是 Docker 跑）
```

> 本地开发时 Django 也在 Docker 里跑，所以 host 名不需要改。差异仅在于 DEBUG、白名单、密钥等。

### 2.6 启动方式

```bash
# === 生产环境 ===
# 1. 基础设施
cd DTD_nginx/docker
docker compose up -d

# 2. 认证层
docker compose -f docker-compose.keycloak.yml -p dkt-keycloak up -d

# 3. iwork（加入 dkt-net）
cd iwork
docker compose --env-file iwork/.env up -d

# === 本地开发 ===
# 1. 基础设施（如果还没起）
cd DTD_nginx/docker
docker compose --env-file .env.local up -d

# 2. 认证层
docker compose -f docker-compose.keycloak.yml -p dkt-keycloak --env-file .env.local up -d

# 3. iwork（本地网络，端口暴露给宿主机）
cd iwork
docker compose --env-file iwork/.env.local up -d
```

### 2.7 网络架构图

```
生产模式（docker_dkt-net）
═══════════════════════════════════════════════════════
                    Internet
                       │
                  ┌────┴────┐
                  │  Nginx  │ :443 (TLS)
                  │DKT_kc_  │
                  └────┬────┘
                       │ auth_request
                  ┌────┴──────────┐
                  │ oauth2-proxy  │
                  │ DKT_kc_       │
                  └────┬──────────┘
                       │ OIDC
            ┌──────────┼──────────┐
            │          │          │
       ┌────┴────┐ ┌───┴────┐ ┌──┴──────────┐
       │Keycloak │ │Portal  │ │   iwork     │
       │DKT_kc_  │ │DKT_kc_ │ │  DKT_iwork  │
       └────┬────┘ └────────┘ └────┬─────────┘
            │                      │
       ┌────┴────┐          ┌──────┴──────┐
       │Postgres │          │iwork Redis  │
       │DKT_     │          │DKT_iwork_   │
       └─────────┘          └─────────────┘
    ═══════════════════════════════════════════

本地模式（iwork_default，可选隔离）
═══════════════════════════════════════════════════════
  ┌──────────────┐    ┌────────────────┐
  │ DKT_iwork    │    │ DKT_iwork_redis │
  │   :8000      │───▶│   (基础设施)    │
  └──────┬───────┘    └────────────────┘
         │
  ┌──────┴───────┐
  │  DKT_mysql   │
  │  (基础设施)   │
  └──────────────┘
  ═══════════════════════════════════════════════════
```

### 2.8 修改清单

| 文件                                    | 操作           | 内容                                                        |
| --------------------------------------- | -------------- | ----------------------------------------------------------- |
| `iwork/docker-compose.yml`            | 修改           | 移除 mysql/redis 服务，仅保留 iwork；使用外部网络或默认网络 |
| `iwork/iwork/.env`                    | 修改           | 改为生产模板：DEBUG=False，完整域名白名单                   |
| `iwork/iwork/.env.example`            | 修改           | 同步 .env 的模板内容，去掉本地默认值                        |
| `iwork/iwork/.env.local`              | **新增** | 本地覆盖：DEBUG=True，localhost 白名单                      |
| `DTD_nginx/docker/docker-compose.yml` | 修改           | 删除 iwork 服务定义（第 138-159 行）                        |
| `iwork/.gitignore`                    | 修改           | 追加`iwork/.env.local`（敏感信息不入库）                  |
| ~~`iwork-mysql` 容器~~               | 删除           | 不再需要                                                    |
| ~~`iwork-redis` 容器~~               | 删除           | 不再需要                                                    |

---

## 三、不变的部分

| 文件                                             | 说明                               |
| ------------------------------------------------ | ---------------------------------- |
| `iwork/Dockerfile`                             | 构建定义不变                       |
| `DTD_nginx/docker/docker-compose.keycloak.yml` | Keycloak 认证栈不变                |
| `DTD_nginx/docker/.env`                        | 基础设施生产配置不变               |
| `DTD_nginx/docker/.env.local`                  | Keycloak 本地配置不变              |
| `iwork/iwork/settings.py`                      | Django 配置不变（已通过 env 读取） |
| 所有容器名称（DKT_* 系列）                       | 保持不变，仅删除不再需要的         |
