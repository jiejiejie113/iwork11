# iwork — 生产看板系统

基于 Django 5.2 的生产流水线实时看板系统，支持多维度数据聚合、SSE 实时推送、产品视图拖拽排序和历史数据回溯。

## 功能特性

- 🔌 **三数据库架构**: Django 系统库 + 远程业务库（只读）+ 本地业务库（读写）
- 🔒 **纵深防御认证**: TrustedProxyMiddleware 只在 Docker 内网受信，完全委托 Portal 层认证
- 📊 **实时看板**: Celery (60s) → 并行查询 → Redis → SSE 推送 → 前端实时渲染
- 📈 **产品视图**: 4 层树形表格（产品→工单→Flow→工序）+ 拖拽自定义层级排序
- 🎯 **目标管理**: 工单级目标产量 + 展开/收起 + 效率追踪
- 🔥 **热力图**: 工序侧边栏红绿渐变色条 + 瓶颈高亮
- 📅 **历史回溯**: 本地聚合快照，缺失日期按需自动回填
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
├── iwork/                              # Django 项目
│   ├── api_views.py                    # 实时看板 API
│   ├── api_views_local.py              # 历史/本地数据 API
│   ├── api_urls.py                     # API 路由（命名空间）
│   ├── history_urls.py                 # 历史模块独立路由
│   ├── urls.py                         # 项目主路由
│   ├── views.py                        # 页面视图（dashboard/kanban等）
│   ├── queries.py                      # 远程数据库查询
│   ├── local_queries.py                # 本地数据库查询
│   ├── historical_queries.py           # 历史快照查询
│   ├── history_store.py                # 历史快照存储
│   ├── statistics.py                   # 缓存编排 + 数据聚合
│   ├── sync.py                         # 远程→本地数据同步
│   ├── tasks.py                        # Celery 定时任务
│   ├── database_router.py              # 三库路由器
│   ├── middleware.py                   # TrustedProxy 认证
│   ├── models.py                       # 远程业务模型
│   ├── local_models.py                 # 本地业务模型
│   ├── request_params.py               # 请求参数处理（stepno_filter等）
│   ├── logger_config.py                # Loguru 日志配置
│   ├── settings.py                     # Django 配置
│   ├── celery.py                       # Celery 应用配置
│   ├── asgi.py                         # ASGI 入口（Uvicorn）
│   ├── test_settings.py                # SQLite/内存缓存测试配置
│   ├── templates/iwork/                # 前端模板（Django 内置）
│   │   ├── _header.html                # 公共头部
│   │   ├── dashboard.html              # 实时/历史看板
│   │   ├── production_detail.html      # 生产详情
│   │   └── kanban.html                 # 产量看板
│   └── management/commands/            # Django 管理命令
│       ├── import_production_orders.py # 导入工单
│       └── snapshot_history.py         # 历史快照
├── tests/                              # 测试（21个文件）
│   ├── conftest.py                     # 测试夹具
│   ├── test_core_api.py                # 核心 API 测试
│   ├── test_api_views.py               # API 视图测试
│   ├── test_api_views_local.py         # 历史 API 测试
│   ├── test_queries.py                 # 查询函数测试
│   ├── test_local_queries.py           # 本地查询测试
│   ├── test_models.py                  # 模型测试
│   ├── test_local_models.py            # 本地模型测试
│   ├── test_statistics.py              # 统计聚合测试
│   ├── test_sync.py                    # 同步测试
│   ├── test_tasks.py                   # Celery 任务测试
│   ├── test_database_router.py         # 数据库路由测试
│   ├── test_kanban_api.py              # 产量看板 API 测试
│   ├── test_kanban_queries.py          # 产量看板查询测试
│   ├── test_history_detail.py          # 历史详情测试
│   ├── test_production_detail_template.py  # 生产详情模板测试
│   ├── test_secrets_config.py          # 密钥配置测试
│   ├── test_unified_engine.py          # 统一引擎测试
│   ├── test_test_environment.py        # 测试环境验证
│   └── diagnose_process_compare.py     # 流程对比诊断
├── scripts/                            # 工具脚本
│   ├── export_pytckreg3.py             # 数据导出
│   ├── create_local_db.py              # 创建本地数据库
│   ├── benchmark_query_perf.py         # 查询性能基准
│   ├── datalib.py                      # 数据工具库
│   ├── watch_logs.ps1                  # 日志监视
│   └── gui/                            # GUI 导出工具
│       ├── main.py
│       └── pack.py
├── src/
│   └── reconcile_data/                 # 数据校对工具
│       ├── data_reconciliation.py
│       └── create_sample_files.py
├── docs/                               # 设计文档
│   ├── adr/                            # 架构决策记录（6篇）
│   ├── 开发文档/                       # 开发规范手册、数据结构、数据流、API文档等
│   ├── 部署文档/                       # Docker部署、Portal集成、迁移手册
│   ├── changelogs/                     # 变更日志（7篇）
│   ├── superpowers/                    # 设计规范 specs/ + 实施计划 plans/
│   └── PCI-architecture_flowchart.html     # Mermaid 架构流程图
├── env/                                # 可提交的非敏感环境 profile
│   ├── local.env
│   └── production.env
├── sqlite/                             # 人工传输的 SQLite 导入源（不提交）
├── mysql-init/                         # MySQL 初始化 SQL
├── logs/                               # 运行日志
├── static/                             # 静态文件收集目录
├── docker-compose.yml                  # Docker 编排
├── Dockerfile                          # Docker 镜像
├── manage.py                           # Django 管理入口
├── requirements.txt                    # Python 依赖
├── pyproject.toml                      # Ruff 配置
├── pytest.ini                          # Pytest 配置
├── deploy.ps1 / restart_services.ps1   # 部署脚本
├── stop_services.ps1                   # 停止服务
├── uninstall_services.ps1              # 清理旧 NSSM 服务
├── start_dashboard.bat                 # 开发启动（无认证）
└── stop_dashboard.bat                  # 停止开发服务
```

## 数据库架构

| 别名 | 用途 | 权限 |
|------|------|------|
| `default` | Django 系统库 (localhost) | 读写 |
| `iwork` | 业务生产库 (192.168.4.19) | 只读 |
| `iwork_local` | 本地业务副本 (localhost) | 读写 |

核心表：`payroll.pytckreg3`（生产流水线打卡记录）

`Pywrkstp` 使用 Django 5.2 `CompositePrimaryKey('WrkOrder', 'StepNo')` 映射远程联合主键，不假设数据库存在 `id` 列。

## 快速开始

### Docker 部署（推荐）

```bash
# 本地环境（中央密钥位于两个仓库的共同上级目录）
docker compose --env-file env/local.env --env-file ../dkt-secrets.env up -d --build iwork

# 服务器 D:\DM\iwork
docker compose --env-file env/production.env --env-file D:\DM\dkt-secrets.env up -d --build iwork
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

### 实时数据

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/realtime/` | GET | 实时统计数据 |
| `/api/dashboard/processes/` | GET | 流程列表 |
| `/api/dashboard/hourly/` | GET | 每小时产量趋势 |
| `/api/dashboard/flow/<flow_name>/` | GET | 指定流程统计 |
| `/api/dashboard/workorders/` | GET | 工单列表 |
| `/api/dashboard/workorders/<wrk_order>/` | GET | 工单详情 |

### 看板改版 v2（月度趋势 / 流程对比 / 热力图 / 工位排名）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/monthly-trend/` | GET | 月度产量趋势 |
| `/api/dashboard/process-compare/` | GET | 流程效率对比 |
| `/api/dashboard/heatmap/` | GET | 工序热力图数据 |
| `/api/dashboard/station-ranking/` | GET | 工位产量排名 |

### SSE 推送 & 目标产量

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/stream/` | GET | SSE 实时推送 |
| `/api/dashboard/set-targets/` | POST | 设置工单目标产量 |

### 历史数据

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/history/date/<date>/` | GET | 读取指定日期的历史数据 |
| `/api/history/dates/` | GET | 已有成功快照的日期列表 |
| `/api/history/snapshots/<date>/ensure/` | POST | 缺失时按需构建本地历史快照 |

### 生产详情

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/detail/stepno-overview/` | GET | 工序全景概览 |
| `/api/dashboard/detail/flows/` | GET | 生产线流程概览 |
| `/api/dashboard/detail/flow/<flow_name>/` | GET | 指定流程详细数据 |
| `/api/dashboard/detail/stepno/<stepno>/` | GET | 指定工序员工明细 |
| `/api/dashboard/detail/product-overview/` | GET | 产品视角总览 |

### 产量看板

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/kanban/stats/` | GET | 产量看板统计 |
| `/api/kanban/ranking/` | GET | 产量看板排行 |
| `/api/kanban/filter-options/` | GET | 筛选选项 |

## 测试

```bash
# 单文件快速测试
pytest tests/test_core_api.py -v

# 完整测试使用 iwork.test_settings，不依赖外部 MySQL/Redis
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

- [架构决策记录](docs/adr/)（6篇）
- [架构流程图](docs/PCI-architecture_flowchart.html)（Mermaid 可视化，浏览器打开）
- [开发规范手册](docs/开发文档/PCI-iwork规范手册.md)
- [数据流通与模块职责](docs/开发文档/PCI-数据流通与模块职责.md)
- [应用数据结构总览](docs/开发文档/PCI-iwork（车间工效看板）应用数据结构.md)
- [API 接口文档](docs/开发文档/PCI-API接口文档.md)
- [前后端字段同步规则](docs/开发文档/PCI-前后端字段同步规则.md)
- [SSE 迁移数据流设计](docs/开发文档/PCI-SSE迁移数据流设计.md)
- [Docker 部署指南](docs/部署文档/PCI-docker-deployment.md)
- [Portal 集成文档](docs/部署文档/PCI-portal-integration.md)
- [迁移操作手册](docs/部署文档/PCI-迁移操作手册.md)
- [变更日志](docs/changelogs/CHANGELOG.md)
