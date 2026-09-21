# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 基础环境

- 操作系统：Windows 11
- 终端：PowerShell；运行命令前执行 `chcp 65001` 设置 UTF-8 编码
- Python 版本：3.11.6
- 对话、解释、注释、错误信息和提示默认使用中文
- 命令行操作使用 Windows 命令，不使用 Linux 命令

## 必须使用的 Skills

- 处理 Excel、报表、`.xlsx`、`.xlsm`、openpyxl、xlwings、pandas Excel IO 时，使用 `excel-automation`
- 用户说"使用头脑风暴模式"或"头脑风暴"时，使用 `superpowers:brainstorming`
- 完成开发任务或合并前，使用 `superpowers:requesting-code-review` 验证工作
- 遇到 bug 或测试失败时，使用 `superpowers:systematic-debugging`
- 实施功能或修复 bug 时，使用 `superpowers:test-driven-development`
- 多步骤任务实施前，使用 `superpowers:writing-plans` 编写计划
- 声称工作完成/修复/通过前，使用 `superpowers:verification-before-completion`

> 注：原引用的 `python-project-standards`、`iwork-django-db-rules`、`karpathy-guidelines`、`obsidian-note-creator` 在当前环境中不可用，已替换为等效的可用 skills。

## 数据库架构

项目使用三数据库配置：

| 别名        | 用途             | 位置         | 权限 |
| ----------- | ---------------- | ------------ | ---- |
| `default` | Django 系统库     | localhost    | 读写 |
| `iwork`   | 业务生产库（远程） | 192.168.3.15 | 只读 |
| `iwork_local` | 本地业务副本   | localhost    | 读写 |

数据库路由器：`iwork/database_router.py`。路由规则：

- `app_label='iwork'` 模型 → `iwork` 数据库（只读）；本地历史快照、目标和产品映射模型 → `iwork_local`（读写）
- 其他 app 模型 → `default` 数据库（读写）
- 远程 `iwork` 数据库 **禁止写入**（`db_for_write` 返回 `None`）
- 禁止跨数据库建立 `ForeignKey` 关系
- `iwork` app 禁止对远程表执行迁移，`managed = False`

业务数据表：`payroll.pytckreg3`（生产流水线打卡记录），模型定义在 `iwork/models.py`（远程只读）和 `iwork/local_models.py`（本地可读写）。

核心字段：`TicketNo`（主键）、`WrkOrder`、`StepNo`、`Qty`、`Flow`、`StationID`、`RegDate`、`RegTime`。`RegDate` 仅含日期，`RegTime` 仅含时间（日期部分为 1899-12-30），完整时间戳需通过 `Pytckreg3.full_datetime` 属性组合。

## 核心架构

```text
queries.py          ← 远程数据库查询（iwork 只读）
local_queries.py    ← 本地历史总览查询（iwork_local）
historical_queries.py ← 本地历史生产详情查询
history_store.py    ← 远程只读聚合、校验和本地事务发布
statistics.py       ← Celery 批量统计构建与历史兼容入口；实时入口禁止回源
read_model/         ← 版本化实时快照构建、原子发布、统一查询和陈旧策略
snapshot_history 命令 / history_store.py ← 按日期生成本地聚合快照
tasks.py            ← Celery 唯一远程采集入口：每 60s 构建完整快照
api_views.py        ← 实时看板 API + 生产详情 API，只读 Redis/本地 MySQL
api_views_local.py  ← 本地历史读取 + 缺失快照异步入队 API
```

## 认证架构

本项目**不实现应用内认证**，完全依赖 Portal 层注入的认证信息：

```
用户 → Nginx (auth_request) → oauth2-proxy (OIDC 验证) → 注入 Remote-User header
       → iwork TrustedProxyMiddleware (IP 校验) → Django request.user
```

- **TrustedProxyMiddleware** (`iwork/middleware.py`)：仅接受来自 Docker 内网 IP（172.x、10.x、192.168.x、127.x）的请求，外部请求直接返回 403。这是纵深防御的最后一层——即使 Nginx 的 Remote-* header 清理被误改，此中间件仍能阻止外部伪造请求到达应用层。
- **不读取 Remote-User header**：iwork 采用"信任 Nginx 认证边界"策略，认证完全由 Nginx + oauth2-proxy + Keycloak 保证，应用层只做 IP 校验，不做用户身份解析。
- **安全边界**：iwork 应用端口不对外暴露，仅通过 Nginx 反向代理访问。

### 数据流

- **实时视图**：Celery Beat (60s) → `sync_dashboard_stats` → `get_batch_stats()`（6 线程并行）→ Redis → SSE push + API 读缓存
- **历史视图**：API 请求 → `statistics.get_local_date_stats()` → 本地聚合事实表
- **历史生产详情**：API 请求 → `historical_queries.py` → 本地事实表 + 元数据快照
- **数据同步**：管理命令/Celery → `snapshot_history_date()` → 远程按日聚合 → 本地事务发布

### 历史查询模块

`local_queries.py` 保持历史总览所需的统计函数；`historical_queries.py` 专门构建 Flow、
工序和产品生产详情。历史详情不得在普通请求中回查远程工序元数据。

### 关键设计决策

- **今日数据**：通过 Celery 预计算为 `iwork:read:v1:<date>:<version>:*` 完整快照，API 只通过 `current` 指针读取；缓存未命中、过旧或 Redis 故障时返回 503，禁止远程回源。
- **历史数据**：只读取本地按日发布的成功快照；缺失时由前端请求确保接口构建，
  确保接口只提交 Celery 任务并返回 202，不提供 `mode=remote` 绕过路径。
- **月趋势**：Redis 独立缓存（`batch_monthly:{year}{month}`），TTL 30 天。每日只查今日数据并追加到已有缓存，避免全月重查。
- **本地库用途**：用于历史数据查询（减少远程库压力）和离线分析。
- **进程角色**：Uvicorn=`web`、Celery=`celery`、管理命令=`management`；Web 角色由受保护数据库后端禁止连接远程 `iwork`。

## 业务配置管理

业务级配置参数统一在 `iwork/settings.py` 末尾的「业务配置」区块定义。

**规则**：
- 所有业务参数必须定义在 `settings.py` 中
- 各模块通过 `from django.conf import settings` 读取，在模块顶部建立引用：
  ```python
  ALLOWED_FLOWS = settings.ALLOWED_FLOWS
  QUERY_TIMEOUT = settings.QUERY_TIMEOUT
  ```
- 禁止在业务模块中硬编码配置值（如工序号、Flow 名称等），必须通过 `settings.XXX` 引用

**已有业务配置项**：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ALLOWED_FLOWS` | 45 个 Flow 字符串 | Flow 白名单 |
| `ALLOWED_FLOWS_STEPNO` | 70 | 白名单生效工序号 |
| `QUERY_TIMEOUT` | 45 | 数据库查询超时（秒） |
| `MONTHLY_CACHE_TTL` | 2592000 | 月度缓存 TTL（30天） |

## 开发规范手册

**每次修改必须更新** `docs/开发文档/PCI-iwork规范手册.md`。该手册是项目的活文档，包含：

- 架构概览与数据流
- 业务配置管理（ALLOWED_FLOWS / HIDDEN_FLOWS / VISIBLE_FLOWS）
- 隐藏分组机制
- 工单列表字段规范
- 时间与时区（UTC+6:30 缅甸）
- 图表配置（字体、颜色）
- SSE 异步架构
- 前后端字段同步对照表
- 修改检查清单

**修改规则**：
1. 修改配置 → 更新手册第 2/3 节
2. 修改 API 字段 → 更新手册第 4/8 节 + 前端模板
3. 修改 queries.py → 同步修改 local_queries.py（镜像）
4. 修改图表/时区 → 更新手册第 5/6 节
5. 每次提交前按手册第 9 节检查清单自查

## 环境变量

非敏感环境 profile 位于 `env/local.env` 与 `env/production.env`。真实密钥位于两个仓库共同上级目录的 `dkt-secrets.env`，不得提交；Compose 必须同时通过两个 `--env-file` 参数加载 profile 和中央密钥。

环境变量命名：
- `DJANGO_*`：Django 基础配置（SECRET_KEY、DEBUG、ALLOWED_HOSTS）
- `ACCESS_DB_*`：Django 系统库，对应 `default`
- `IWORK_DB_*`：远程业务生产库，对应 `iwork`
- `LOCAL_DB_*`：本地业务库，对应 `iwork_local`

## 开发命令

```powershell
# 安装依赖
pip install -r requirements.txt

# Django 迁移（仅 default 和 iwork_local 库）
python manage.py migrate

# Django 开发服务器（仅用于页面/API 快速调试；正式 SSE 运行时使用 Uvicorn）
python manage.py runserver

# 运行测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_statistics.py -v

# 运行带日志输出的测试
pytest tests/ -v -s
```

### 完整看板启动（需 Redis）

```powershell
# 1. 确保 Redis 运行
redis-cli ping

# 2. 启动 Celery Worker
celery -A iwork worker -l info -P eventlet

# 3. 启动 Celery Beat（定时调度）
celery -A iwork beat -l info

# 4. 启动 Uvicorn（ASGI，支持 SSE 推送）
uvicorn iwork.asgi:application --host 0.0.0.0 --port 8000
```

## 日志系统

所有进程（Django / Celery）通过 `iwork/logger_config.py` 统一日志配置。
- 入口调用：`setup_logging('DJANGO')` / `'CELERY'` / `'ASGI'`
- stdout：DEBUG 级别，格式 `时间 | 级别 | [组件名] | 消息`
- 文件：`logs/all_YYYY-MM-DD.log`（保留 7 天）+ `logs/error_YYYY-MM-DD.log`（保留 30 天）
- Django 标准 logging 通过 `_InterceptHandler` 全部重定向到 loguru

## Git 提交规范

提交格式：

```text
[YYYY-MM-DD][TYPE] 描述
```

常用类型：`[FEAT]`、`[FIX]`、`[DOCS]`、`[REFACTOR]`、`[TEST]`、`[PERF]`、`[STYLE]`、`[CHORE]`。
