# iwork 数据库架构与数据流

> 本文档描述 iwork 的本地数据库与远程生产数据库的关系、数据流向、同步机制与权限保护。
> 对应代码：`iwork/settings.py`（DATABASES）、`iwork/database_router.py`、`iwork/db_backends/guarded_mysql/`、`iwork/celery.py`（beat_schedule）。

## 一、三库架构总览

| 别名 | 位置 | 主要表 | 权限 | 可访问角色 |
|------|------|--------|------|-----------|
| `default` | 本地 MySQL `iwork_system`（Docker 共享 `mysql`） | Django 系统表（session、admin、迁移记录） | 读写 | 所有进程 |
| `iwork` | **远程**生产库 `192.168.7.22:3306/payroll` | `pytckreg3`（打卡记录/产量唯一源头）、`pywrkord`（初版款号 ExtField01）、`pywrkstp`（工序描述/标准工时）、`pydefstp` | **只读** | **仅 Celery 任务与管理命令**；Web 进程被硬拦截 |
| `iwork_local` | 本地 MySQL `iwork_local` | 历史快照三表（`historical_production_fact` / `historical_step_snapshot` / `historical_sync_state`）、`production_orders`（工单字典）、目标与责任表（`target_production`、`group_target_production`、`iwork_principal`、`daily_target_obligation` 等）、`alert_*` 通知表 | 读写 | 所有进程 |

### 核心结论

- **远程库是唯一生产数据源**，本地库是它的派生副本。
- Web 进程**永不直连远程库**：实时数据读 Redis 快照，历史数据读 `iwork_local` 快照表。
- 远程表全部 `managed = False`，本地无迁移；`pywrkstp` 使用 Django 5.2 `CompositePrimaryKey` 映射远程联合主键。

## 二、路由与权限保护

### 模型路由（`database_router.py`）

- `iwork` app 的 `local_models` 白名单模型（历史快照、工单字典、目标、责任、通知等）→ `iwork_local`
- `iwork` app 的其他模型（远程表）→ `iwork`，且 `db_for_write` 返回 `None`（只读语义）
- 非 `iwork` app（系统模型）→ `default`
- 迁移：仅白名单模型允许进入 `iwork_local`；远程模型禁止迁移

### 远程访问拦截（`db_backends/guarded_mysql/`）

- `iwork` 库使用自定义后端 `guarded_mysql`
- `IWORK_PROCESS_ROLE=web` 时，`get_new_connection` 与 `create_cursor` 双重检查，直接抛 `RemoteDatabaseAccessDenied`（"Web 进程禁止访问远程生产数据库"）
- Celery / 管理命令角色（`management`）不受限，用于采集与构建

## 三、数据流与同步链路

```
远程 payroll.pytckreg3（唯一产量源头）
  │
  ├─【实时链路·今日】Celery sync_dashboard_stats 每 60 秒采集（Redis 构建锁防并发）
  │   ├─ ReadModelFactSource 单次采集事实（含 HOUR(RegTime) 派生 event_hour）
  │   ├─ 补充元数据：pywrkord → initial_style_no（初版款号）
  │   │              production_orders → product_name / order_no（产品名称/生产单号）
  │   └─ 原子发布 Redis 版本化快照（read_model store，schema 版本校验）
  │       → Web 读 Redis（不碰远程库）→ 前端渲染
  │
  ├─【历史链路·过去日期】三种触发方式：
  │   1. 前端按需：API 404 → POST /api/history/snapshots/<date>/ensure/ → Celery 构建
  │   2. 每日定时：Celery beat 每天 03:00（业务时区）重建最近 3 天（覆盖迟到/修正数据）
  │   3. 管理命令：python manage.py snapshot_history --date / --start --end 批量回填
  │   └─ snapshot_history_date 构建管线：
  │       RemoteHistorySource.load（远程采集+工序/产品元数据）
  │       → _validate_payload（源记录数/总产量自洽校验）
  │       → 原子发布：删旧 → bulk_create → SUCCESS + version 递增（构建锁+后台续租线程）
  │       → Web 读 iwork_local 快照表 → 前端渲染
  │
  └─【工单字典·人工导入】sqlite/production_orders.db（人工传输的一次性导入源，不提交）
      └─ python manage.py import_production_orders → iwork_local.production_orders
         （前端"产品名称/生产单号"唯一来源，wrk_order[:6] 前缀匹配 style_no）
```

### 关键设计

- **历史快照是只读副本**：由构建管线整体替换（删旧→写入→SUCCESS），业务代码只读；`historical_sync_state` 记录版本与源统计，供可用日期列表与状态判断。
- **空快照是合法状态**：停产日/休息日无打卡记录 → 空快照 SUCCESS，页面显示 0 数据，属正常行为。
- **版本化**：每次重建 `snapshot_version` 递增；可用日期列表（`/api/history/dates/`）只列出 SUCCESS 快照日期。

## 四、Celery 调度清单（`celery.py` beat_schedule）

| 任务 | 调度 | 说明 |
|------|------|------|
| `sync_dashboard_stats` | 每 60 秒 | 采集远程数据并原子发布实时 Redis 快照 |
| `snapshot_recent_history` | 每天 03:00（业务时区） | 重建最近 3 天历史快照 |
| `reconcile_target_obligations_task` | 每 60 秒 | 目标责任对账（alerts 队列） |
| `reconcile_alerts_task` | 每 5 分钟 | 告警对账（alerts 队列） |

## 五、本地测试环境映射

本地开发/验证使用 `iwork/local_dev_settings.py`（不提交），三库全部映射到本地 SQLite 文件：

| 生产别名 | 本地测试 |
|---------|---------|
| `default` | `local_dev_db/default.sqlite3` |
| `iwork`（远程） | `local_dev_db/iwork.sqlite3`（手工建远程表结构 + 假数据**模拟远程库**） |
| `iwork_local` | `local_dev_db/iwork_local.sqlite3` |

- 实时链路：`build_snapshot` + `SnapshotStore().publish` 发布到本地 Docker Redis（`iwork-redis`，127.0.0.1:6379）
- SQLite 需注册 MySQL 兼容的 `HOUR()` 函数（`connection_created` 信号）
- 缓存：`default` 缓存使用 Redis（与生产一致）；Celery 内存 eager 模式

## 六、已知隐患与影响

| # | 隐患 | 位置 | 影响 | 状态 |
|---|------|------|------|------|
| 1 | `db_for_write` 对远程模型返回 `None` → Django 回退写入 `default` 库而非报错 | `database_router.py:60` | 若未来误写远程表（如 `Pytckreg3.objects.create()`）会静默写入本地系统库 | 当前无触发，待处理 |
| 2 | 本地测试环境：历史日期未 seed 时 ensure 发布空快照 | `history_store.py:_validate_payload` | 页面显示"已加载历史数据"但数据为空，`available_dates` 永久占位 | 待处理 |
| 3 | 前端 ensure 无限轮询无上限/无取消 | `templates/iwork/dashboard.html:697`、`production_detail.html:1472` | 构建长期卡住时页面永久轮询 | 待处理 |
| 4 | FAILED 状态快照会被 ensure 视为未构建 → 每 2 秒重新提交构建任务 | `api_views_local.py:_snapshot_state` | 远程库临时不可达时触发任务风暴 | 待处理 |

## 相关文档

- `README.md`（数据库架构小节）
- `docs/部署文档/PCI-docker-deployment.md`（部署与中间件）
- `docs/部署文档/PCI-迁移操作手册.md`（数据迁移操作）