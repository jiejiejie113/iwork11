# iwork — 生产看板系统

基于 Django 5.2 的生产流水线实时看板系统，支持多维度数据聚合、SSE 实时推送、产品视图拖拽排序和历史数据回溯。

## 功能特性

- 🔌 **三数据库架构**: Django 系统库 + 远程业务库（只读）+ 本地业务库（读写）
- 🔒 **纵深防御认证**: TrustedProxyMiddleware 只在 Docker 内网受信，完全委托 Portal 层认证
- 📊 **实时看板**: Celery (60s) → 并行查询 → Redis → SSE 推送 → 前端实时渲染
- 📈 **产品视图**: 4 层树形表格（产品→工单→Flow→工序）+ 拖拽自定义层级排序
- 🎯 **目标管理**: 工单级目标产量 + 展开/收起 + 效率追踪
- 🔥 **热力图**: 工序侧边栏红绿渐变色条 + 瓶颈高亮
- 📅 **历史回溯**: 本地/远程双模式，按日查询完整统计
- 🖥️ **GUI 导出工具**: 基于 CustomTkinter 的桌面导出应用

## 技术栈

- Python 3.11 / Django 5.2
- Uvicorn (ASGI + SSE 推送)
- Celery + Celery Beat (定时任务)
- Redis (缓存层 / 消息队列)
- MySQL 8.0+ (三库架构)
- Ruff (静态检查)

## 项目结构

```
iwork/
├── iwork/                         # Django 项目
│   ├── api_views.py               # 实时看板 API
│   ├── api_views_local.py         # 历史/本地数据 API
│   ├── queries.py                 # 远程数据库查询
│   ├── local_queries.py           # 本地数据库查询（镜像签名）
│   ├── statistics.py              # 缓存编排 + 数据聚合
│   ├── sync.py                    # 远程→本地数据同步
│   ├── tasks.py                   # Celery 定时任务
│   ├── database_router.py         # 三库路由器
│   ├── middleware.py               # TrustedProxy 认证
│   ├── management/commands/       # Django 管理命令
│   └── .env / .env.local          # 环境变量
├── templates/iwork/               # 前端模板
│   ├── dashboard.html             # 实时/历史看板
│   ├── production_detail.html     # 生产详情
│   └── kanban.html                # 产量看板
├── tests/                         # 测试
│   ├── test_core_api.py           # 核心 API 测试（20项）
│   ├── test_api_views.py          # API 视图测试
│   ├── test_queries.py            # 查询函数测试
│   └── ...
├── scripts/                       # 工具脚本
│   ├── export_pytckreg3.py        # 数据导出
│   └── gui/                       # GUI 导出工具
├── docs/                          # 设计文档
└── deploy.ps1                     # Windows 部署脚本
```

## 数据库架构

| 别名 | 用途 | 权限 |
|------|------|------|
| `default` | Django 系统库 (localhost) | 读写 |
| `iwork` | 业务生产库 (192.168.4.19) | 只读 |
| `iwork_local` | 本地业务副本 (localhost) | 读写 |

核心表：`payroll.pytckreg3`（生产流水线打卡记录）

## 快速开始

### Docker 部署（推荐）

```bash
# 生产环境
docker compose up -d --build

# 本地开发环境
docker compose --env-file .env.local up -d --build
```

> iwork 通过 `docker_dkt-net` 网络连接 DTD_nginx 提供的 MySQL（`mysql`）和 Redis（`iwork-redis`）。

### 直接运行（需 Docker 中间件）

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## 认证架构

```
用户 → Nginx (auth_request) → oauth2-proxy (OIDC) → Portal
       → iwork TrustedProxyMiddleware (仅受信 Docker IP)
```

iwork 不实现应用内认证，安全边界由 Nginx + oauth2-proxy + Keycloak 保证。

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/realtime/` | GET | 实时统计数据 |
| `/api/dashboard/stream/` | GET | SSE 实时推送 |
| `/api/history/date/<date>/` | GET | 按日历史数据（local/remote） |
| `/api/history/dates/` | GET | 可用日期列表 |
| `/api/history/sync/<date>/` | POST | 远程数据同步 |
| `/api/dashboard/detail/flows/` | GET | 生产线概览 |
| `/api/dashboard/detail/stepno/<stepno>/` | GET | 工序员工明细 |
| `/api/kanban/stats/` | GET | 产量看板统计 |
| `/api/kanban/ranking/` | GET | 产量看板排行 |

## 测试

```bash
# 核心 API 测试（无需数据库/Redis）
pytest tests/test_core_api.py -v

# 完整测试（需要数据库/Redis/Docker 环境）
pytest tests/ -v
```

## 数据导出

```bash
# 默认导出今日数据
python scripts/export_pytckreg3.py

# 指定日期和输出
python scripts/export_pytckreg3.py --date 2026-04-21 --output data.csv
```

## 提交规范

```
[YYYY-MM-DD][TYPE] 描述

TYPE: FEAT / FIX / DOCS / REFACTOR / TEST / PERF / STYLE / CHORE
```

## 文档

- [开发规范手册](docs/开发文档/iwork规范手册.md)
- [API 接口文档](docs/开发文档/API接口文档.md)
- [前后端字段同步规则](docs/开发文档/前后端字段同步规则.md)
- [Docker 部署指南](docs/部署文档/docker-deployment.md)
- [架构决策记录](docs/adr/)
