# 车间工效看板（iwork）— 开发规范手册

> 本手册是项目的活文档，每次修改必须同步更新对应章节。
> 最后更新：2026-08-03

---

## 1. 架构概览

```
Uvicorn ASGI (4 workers)
    ├── 实时数据：Celery Beat (60s) → 单次基础事实查询 → 内存派生 → 版本化 Redis 快照
    ├── Web/SSE：read_model.queries → 当前完整快照（禁止远程回源）
    ├── 历史数据：API → local_queries.py → 本地历史事实表
    ├── 历史快照：ensure API → Celery → history_store.py → 本地事务快照
    └── 远程生产库：仅 Celery/管理角色允许连接
```

| 文件 | 职责 |
|------|------|
| `queries.py` | 仅供 Celery/管理角色使用的远程数据库查询（iwork 只读） |
| `local_queries.py` | 从本地历史事实表构建历史总览 |
| `historical_queries.py` | 从历史事实和元数据快照构建生产详情 |
| `history_store.py` | 远程只读聚合、校验和本地事务发布 |
| `read_model/builder.py` | 受控远程采集并组装完整实时快照 |
| `read_model/fact_source.py` | 从同一批当前业务日事实派生实时、月趋势、详情与 Kanban 视图 |
| `read_model/store.py` | 版本键、原子 current 切换、上一版本和陈旧策略 |
| `read_model/queries.py` | Web/SSE 统一筛选、分页与跨接口读模型 |
| `statistics.py` | 批量统计构建器和历史兼容入口；实时入口不允许回源 |
| `api_views.py` | 实时看板、生产详情、Kanban 与异步 SSE；不得导入 `iwork.queries` |
| `api_views_local.py` | 本地历史读取；缺失快照只提交 Celery 任务并返回 202 |
| `tasks.py` | Celery 受控采集、原子发布和历史快照任务 |
| `db_backends/guarded_mysql` | Web 进程远程 MySQL 连接/游标硬拦截 |

### 实时快照发布不变量

当前业务日只允许 `get_read_model_fact_rows()` 对远程 `pytckreg3` 执行一次基础事实
聚合查询。实时、当前日月趋势、生产详情、产品视图和 Kanban 必须由
`ReadModelFactSource` 在内存中从这批不可变事实派生，禁止为任一今日视图再次查询
`pytckreg3`。月度历史远程查询最多截止当前业务日的前一天；产品信息读取本地
`ProductionOrder`，工序描述和标准工时的只读元数据查询不参与产量一致性。

`read_model.schemas` 必须在写入 Redis 前校验以下同语义汇总，任一不一致都禁止切换
`current`：

- 每个实时视图的 `total_qty` 等于 `process_flow_stats` 的产量合计；
- 每个实时视图的 `total_qty` 等于 `monthly_total_trend` 中当前业务日期的产量；
- 具体工序视图的 `total_qty` 等于 `monthly_process_stats` 中当前业务日期的产量；
- `all` 视图不与 `monthly_process_stats` 直接比较，因为该字段存在既有工序过滤语义。

一致性异常使用 `SnapshotConsistencyError` 表示，属于可恢复错误：Celery 按既有重试
策略重新采集，上一份完整快照继续可读。结构版本、字段类型等逻辑错误仍立即失败，
不进入一致性重试。测试中的“今日”接口必须固定或模拟 `get_business_date()`，禁止依赖
执行测试当天的自然日期。

### 运行与测试环境

- Docker 使用 `env/local.env` 或 `env/production.env` 保存非敏感配置；
- 真实密钥从两个仓库共同上级目录的 `dkt-secrets.env` 显式注入；
- `DKT_iwork` 的 8000 端口只在 `docker_dkt-net` 内暴露，外部请求必须经过 Nginx 和 oauth2-proxy；
- pytest 固定加载 `iwork.test_settings`，使用内存 SQLite、LocMem 缓存和内存 Celery，不依赖开发数据库或 Redis；
- `Pywrkstp` 使用 `(WrkOrder, StepNo)` 复合主键，禁止查询隐式 `id`。
- 进程必须声明 `IWORK_PROCESS_ROLE`：Uvicorn=`web`、Celery=`celery`、管理命令=`management`；
- `web` 角色访问数据库别名 `iwork` 会抛出 `RemoteDatabaseAccessDenied`。
- Celery 线程池中的每个查询必须在线程内部关闭自身数据库连接，不能只关闭任务主线程连接。

---

## 2. 业务配置管理

所有业务参数统一在 `iwork/settings.py` 末尾「业务配置」区块定义。

| 配置项 | 说明 | 引用方式 |
|--------|------|----------|
| `ALLOWED_FLOWS` | Flow 白名单（全量） | `settings.ALLOWED_FLOWS` |
| `HIDDEN_FLOWS` | 隐藏分组列表（不查询、不显示） | `settings.HIDDEN_FLOWS` |
| `VISIBLE_FLOWS` | 实际可见分组 = 白名单 - 隐藏 | `settings.VISIBLE_FLOWS` |
| `QUERY_TIMEOUT` | 数据库查询超时（秒） | `settings.QUERY_TIMEOUT` |
| `MONTHLY_CACHE_TTL` | 月度缓存 TTL（秒） | `settings.MONTHLY_CACHE_TTL` |
| `PRODUCTION_ORDERS_SQLITE_PATH` | 生产订单 SQLite 快照路径 | `import_production_orders` 管理命令 |
| `PRODUCTION_ORDERS_IMPORT_BATCH_SIZE` | 生产订单批量写入大小 | `import_production_orders` 管理命令 |
| `PRODUCTION_ORDERS_PROGRESS_INTERVAL` | 生产订单导入进度间隔 | `import_production_orders` 管理命令 |
| `READ_MODEL_CACHE_PREFIX` | 版本化读模型键前缀 | `read_model.store` |
| `READ_MODEL_RETENTION_SECONDS` | 当前/上一版本键保留时间 | `read_model.store` |
| `READ_MODEL_STALE_AFTER_SECONDS` | 标记陈旧的软阈值，默认 120 秒 | `read_model.store` |
| `READ_MODEL_MAX_STALE_SECONDS` | 返回 503 的硬阈值，默认 600 秒 | `read_model.store` |
| `READ_MODEL_PUBLISH_LOCK_SECONDS` | 单日期发布锁时间 | `read_model.store` |
| `READ_MODEL_REFRESH_LOCK_SECONDS` | Celery 采集防重叠锁时间 | `tasks.py` |

**引用规则**：各模块在顶部建立引用，使用 `VISIBLE_FLOWS` 而非 `ALLOWED_FLOWS`：

```python
# queries.py / local_queries.py
ALLOWED_FLOWS = settings.VISIBLE_FLOWS  # 实际使用的可见分组

# statistics.py
flows = list(settings.VISIBLE_FLOWS)
```

**新增配置项**：必须在 `settings.py` 定义 → 在本手册表格中登记 → 在引用模块顶部建立引用。

---

## 3. 隐藏分组机制

**配置位置**：`settings.py` → `HIDDEN_FLOWS`

**效果**：
1. 后端：所有查询函数通过 `VISIBLE_FLOWS` 过滤，隐藏分组数据不查、不缓存
2. 前端：接收的数据已排除隐藏分组，无需前端过滤

**当前隐藏分组**（21 个）：

| 前缀 | Flow 列表 |
|------|-----------|
| SO2 | SO2-L2A ~ SO2-L2G（7 个） |
| SO6 | SO6-L6A ~ SO6-L6G（7 个） |
| SO10 | SO10-L10A ~ SO10-L10G（7 个） |

**修改方式**：编辑 `settings.py` 中 `HIDDEN_FLOWS` 列表，重启服务生效。Celery 会在下一个 60s 周期自动刷新 Redis 缓存。

---

## 4. 工单列表字段规范

工单列表在两个页面使用：实时数据看板（dashboard）和生产详情（production_detail）。

### 4.1 API 返回字段

```python
# get_workorders_paginated / get_workorders_list 返回
{
    'wrk_order': str,      # 工单号
    'total_qty': int,      # 总产量
    'worker_count': int,   # 人数（仅 paginated 版本）
    'flows': list[str],    # 关联的 Flow 分组列表
}
```

### 4.2 前端显示

| 页面 | 显示字段 | 分组列 |
|------|----------|--------|
| 实时数据看板 | 工单号、总产量、分组 | 具体分组名称列表（如 "SO3-L3A, SO5-L5E"） |
| 生产详情概览 | 工单号、总产量、工序数 | `{flows.length}道工序`（如 "3道工序"） |

两个页面的工单列表独立维护，显示逻辑不同。

**注意**：`step_count`（工序数）已移除，不再返回。工单关联的 Flow 分组通过 `_inject_flows()` 函数注入。

### 4.3 批量查询中的工单

`get_batch_workorders_list` 返回格式：
```python
{stepno: [{'wrk_order': str, 'total_qty': int, 'flows': list[str]}]}
```

### 4.4 Flow 员工明细

`get_batch_flow_employees` 按 `(WrkOrder, StepNo)` 从 `Pywrkstp` 批量注入
`description`、`step_time` 和 `output_value`。员工节点汇总 `output_value`；任一工序
缺少标准工时时汇总值为 `null`。历史详情必须读取 `HistoricalStepSnapshot`，不得在
普通请求中回查远程元数据，避免元数据变化改写历史产值。

Flow 详情保存在当前版本的 `detail` 视图中。缓存不保存实时效率；接口按请求时刻注入
`work_minutes` 和 `employee_efficiency`，并通过响应头返回快照版本和陈旧状态。

累计产量使用 `iwork_local.igarment_production_orders` 提供的工单创建日期。完整
`WrkOrder` 可能带 `-0`、`P` 等后缀，必须沿用产品映射规则，以前 6 位匹配
`customer_order_no`。若同一客户订单编号有多个创建时间，必须取
`MIN(created_date)` 并转换为业务日期；远程生产查询按相同
`(Flow, RegPerSysID, StepNo, WrkOrder)` 粒度汇总，日期条件必须为
`RegDate >= 创建日期`，包含创建当天。不同创建日期使用可索引的独立查询分支并通过
`UNION ALL` 合并，禁止重新拼成大型 `OR` 条件。当天事实与累计事实必须位于同一个
MySQL `REPEATABLE READ` 事务快照内，再一起发布到同一 Redis 版本；Web/API 请求
不得临时回源远程生产库。

### 4.5 整组目标产量与目标达成率

生产组（Flow）详情使用整组目标输入，不允许逐员工或逐工单编辑目标。当前页面通过
`POST /api/dashboard/set-targets/` 提交：

```json
{
  "flow": "SO3-L3A",
  "group_target": 1000
}
```

整组目标按业务日期和 Flow 保存到本地 `group_target_production` 表，并缓存为
`group_target:{date}:{flow}`。读取 Flow 详情时遵循以下规则：

1. 当前 Flow 出现的每道工序都获得完整的整组目标；整组目标为 1000 时，每道工序目标均为 1000。
2. 每道工序按去重员工人数分配整数个人目标；无法整除时按员工 ID 升序分配余数，确保个人目标合计严格等于工序目标。
3. 员工工序达成率 = 该员工在该工序的实际产量 / 该员工的工序目标 × 100%。
4. 员工汇总达成率 = 员工全部工序实际产量 / 员工全部工序目标合计 × 100%。
5. 未设置整组目标的旧日期继续读取旧员工/工单目标；新页面只提供整组目标编辑入口。
6. “按工序”详情可能跨多个 Flow，因此不提供整组目标编辑，避免把单个目标错误应用到多个生产组。

接口分配结果仅在响应副本中注入，不得修改 Redis 版本化快照中的原始员工和工序数据。

`statistics.py` 中 `get_batch_stats` 合并工单时，`flows` 字段会跨工序合并去重。

---

## 5. 时间与时区

所有前端时间显示使用 **UTC+7**（越南/曼谷时区）：

```javascript
new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Bangkok' })
```

生产详情默认日期也必须使用 `Asia/Bangkok`，不得使用 UTC 的
`new Date().toISOString()`。后端 Flow 详情使用同一业务日期判断“今日”缓存。

员工有效上班分钟从 07:00 起算，11:00-12:00 固定为 240 分钟，12:00 后扣除一
小时午休；历史日期、07:00 前和分钟数为 0 时不计算员工效率。

**适用位置**：
- `dashboard.html`：`lastUpdate`（SSE 接收时更新）
- `production_detail.html`：`lastUpdateTime`（数据加载/刷新时更新）

**修改方式**：如需调整时区，全局替换 `Asia/Bangkok` 为目标时区标识符。

---

## 6. 图表配置

### 6.1 全局默认值（dashboard.html `chartDefaults()`）

```javascript
{
    plugins: { legend: { labels: { color: '#94a3b8', font: { size: 14 } } } },
    scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 14 } } },
        y: { ticks: { color: '#94a3b8', font: { size: 14 } } },
    }
}
```

### 6.2 生产详情图表（production_detail.html）

柱状折线组合图（Flow 产量 & 人数）：
- X/Y 轴刻度：14px
- Y1 轴（人数）：14px
- 图例：14px

### 6.3 工序颜色规范（生产详情页）

```javascript
function stepColor(idx, stepno) {
    if (String(stepno) === '70') return '#f59e0b';  // 工序70 突出显示（金色）
    return '#3b82f6';  // 其他工序统一蓝色
}
```

- 所有工序统一蓝色 `#3b82f6`
- 工序 70 突出显示为金色 `#f59e0b`

### 6.4 产品视图状态与图表生命周期

- “按产品名称”的激活维度及顺序、树状展开路径和图表指标保存在浏览器
  `localStorage`，存储键为 `iwork:production-detail:product-view:v1`。
- 恢复状态时必须校验维度和图表指标白名单；产品数据加载成功后，树状路径只保留
  当前数据中仍然有效的连续层级，避免旧缓存造成空白列表或图表。
- Vue 的 `v-if` 会在标签切换时替换产品图 `<canvas>`。复用 Chart.js 实例前必须确认
  `chart.canvas` 仍是当前画布；不一致时销毁旧实例并在当前画布重新创建。
- 浏览器存储失败不得阻断数据加载和图表渲染，应静默回退到页面默认状态。

---

## 7. SSE 异步架构

**服务器**：Uvicorn ASGI，4 workers，每 worker 异步处理数百连接。

**端点**：`/api/dashboard/stream/`（`api_views.py` → `async def dashboard_stream`）

**实现要点**：
- 使用 `StreamingHttpResponse` + 异步生成器
- `sync_to_async` 包装同步 Redis 读取，不阻塞事件循环
- 心跳：每 15 秒发送 SSE 注释（`: heartbeat\n\n`）
- 数据推送：每 60 秒固定一次 `current` 指针，同时读取实时、工序和详情视图
- 每条数据事件包含 `snapshot_version`、`generated_at` 和 `stale`
- 快照不可用时发送 `snapshot_unavailable` 事件，仍继续发送 15 秒心跳
- 前端直接使用 `msg.data.workorders`，禁止 SSE 事件后再次请求工单接口

**性能**：每个连接仅占一个 asyncio 协程（~KB 级），支持 300+ 并发。

---

## 8. 工单列表数据流规范

**原则**：不显示中间版本。消费者只通过 `current` 读取已经完整发布的快照。

**`workorderItems` 计算属性**：
```javascript
const workorderItems = computed(() => {
    return workorderCache[workorderPage.value] || [];
});
```

首次加载和手工翻页使用工单分页 API；SSE 更新必须使用事件中的
`msg.data.workorders`，因为它与同一事件的 KPI、图表和快照版本一致。

**数据更新流程**：
1. Celery 完成全部视图后切换 `current`；
2. SSE 将事件内工单写入 `workorderCache[1]` 并更新分页状态；
3. 然后清除其他页旧缓存；
4. 不允许在 SSE 回调中再发工单请求。

---

## 9. 前后端字段同步

### 8.1 实时数据 API → dashboard.html

| API 字段 | 前端变量 | 用途 |
|----------|----------|------|
| `total_qty` | `data.total_qty` | KPI 卡片 |
| `workorder_count` | `data.workorder_count` | KPI 卡片 |
| `hourly_stats` | `data.hourly_stats` | 每小时趋势图 |
| `process_flow_stats` | `data.process_flow_stats` | 工序×Flow 对比图 |
| `monthly_process_stats` | `data.monthly_process_stats` | 每日工序堆积图 |
| `monthly_total_trend` | `data.monthly_total_trend` | 月度趋势 |
| `workorders` | `data.workorders` | 工单列表 |
| `all_stepnos` | `data.all_stepnos` | 工序下拉列表 |

### 8.2 生产详情 API → production_detail.html

| API 字段 | 前端变量 | 用途 |
|----------|----------|------|
| `flow_overview` | `flowCards` | Flow 概览卡片 |
| `workorders.items` | `workorderList` | 工单汇总列表 |
| `employees` | `employees` | 员工明细（详情页） |
| `employees[].steps[].description` | `row._step.description` | 组合键工序描述 |
| `employees[].steps[].step_time` | `row._step.step_time` | 标准工时 |
| `employees[].steps[].output_value` | `row._step.output_value` | 工序产值 |
| `employees[].steps[].cumulative_qty` | `row._step.cumulative_qty` | 员工/工序/工单累计产量 |
| `employees[].cumulative_qty` | `emp.cumulative_qty` | 员工累计产量 |
| `cumulative_qty` | `detailSummary.cumulative_qty` | 当前 Flow 累计产量汇总 |
| `employees[].output_value` | `emp.output_value` | 员工总产值 |
| `employees[].employee_efficiency` | `emp.employee_efficiency` | 员工效率 |
| `source` | 历史快照标识 | `local_snapshot` 表示本地只读历史数据 |
| `snapshot_date` / `snapshot_version` | 历史状态 | 标识快照日期和发布版本 |

历史日期通过 URL 的 `date` 参数传递。Flow、工序和产品视图之间的导航必须保留日期；
历史日期禁止目标编辑和 60 秒自动刷新。快照不存在时，前端应调用
`POST /api/history/snapshots/<date>/ensure/`。接口只提交后台任务并返回 202；前端显示构建状态并在完成后重试原 GET；构建
失败时显示明确错误，不能把错误 JSON 或空列表当作有效历史数据。历史目标只使用后端
按日期返回的 `target` / `wo_targets`，不得使用浏览器旧值覆盖。

### 8.3 修改规则

1. **后端新增字段** → 前端 `Object.assign` / `map` 中同步添加
2. **后端删除字段** → 前端引用处同步删除，否则显示 `undefined`
3. **后端重命名字段** → 前端所有引用处同步修改

---

## 9. 生产订单每日同步

### 9.1 数据流与一致性

```text
D:\DM\iwork\sqlite\production_orders.db（只读挂载）
    → Django 管理命令 import_production_orders
    → iwork_local.production_orders（MySQL 精确镜像）
```

- `docker-compose.yml` 将宿主机 `./sqlite` 只读挂载到容器 `/app/sqlite`；
- 导入前必须通过 SQLite 完整性、`orders` 表、五个必需字段、空值、字段长度和复合重复校验；
- MySQL 删除旧快照与批量写入新快照位于同一个 `iwork_local` 事务；任何异常均回滚到上一版；
- SQLite 空表不得覆盖已有 MySQL 快照；
- 成功发布后必须核对 SQLite 与 MySQL 行数一致。

### 9.2 计划任务

- 任务名：`\DKT\iwork-Production-Orders-Sync`；
- 执行账户：`SYSTEM`，最高权限；
- 时间：服务器北京时间每天 `00:00`；
- 并发策略：`IgnoreNew`，脚本另使用全局互斥锁；
- 超时：20 分钟；失败后每隔 5 分钟重试，最多 2 次；
- 安装入口：`scripts\install-production-orders-sync-task.ps1`；
- 执行入口：`scripts\sync-production-orders.ps1`，使用 `-Force` 可忽略哈希强制发布。

脚本以 SHA-256 记录上次成功快照。源文件哈希未变化时返回成功并跳过 Docker；只有导入成功后才原子更新成功状态，失败不得覆盖成功哈希。

### 9.3 看门狗维护窗口

同步脚本在导入期间创建带 30 分钟 TTL 的维护标记：

```text
D:\DM\DTD_nginx\logs\watchdog\maintenance\iwork-production-orders.json
```

有效维护期只跳过 iwork HTTP 探测。Docker Engine、`DKT_iwork` 容器、其他容器及其他应用 HTTP 仍正常监控。Python 告警监控保留 iwork 维护前状态，不发送虚假故障或恢复邮件。过期、损坏或字段不匹配的标记一律不放行。

### 9.4 iGarment 创建日期快照同步

服务器额外维护以下精简快照：

```text
D:\DM\iwork\sqlite\iGarment_ProdOrder.db（只读挂载）
    → 客戶訂單編號、訂單編號、數量、創建日期
    → iwork_local.igarment_production_orders
```

- 任务名：`\DKT\iwork-iGarment-Production-Orders-Sync`；
- 时间：服务器北京时间每天 `00:30`，避开 `00:00` 原生产订单任务的最长执行窗口；
- 执行脚本：`scripts\sync-igarment-production-orders.ps1`；
- 导入脚本：`scripts\import_igarment_production_orders.py`；
- 与原生产订单任务共享全局互斥锁和看门狗认可的 30 分钟维护标记；
- 使用独立 SHA-256 状态和日志，源文件未变化时成功跳过；
- MySQL 的旧快照删除、批量写入和行数复核位于同一个事务，失败保留上一版；
- `客戶訂單編號` 为空的源行允许保留，但累计查询不得将其用于 WrkOrder 匹配。

## 10. 修改检查清单

每次修改后，按以下清单检查：

- [ ] **配置变更**：`settings.py` → 更新本手册第 2 节
- [ ] **字段变更**：API 返回字段 → 更新本手册第 4/8 节 + 前端模板
- [ ] **查询变更**：`queries.py` 的历史同语义查询 → 同步修改 `local_queries.py`；仅用于当前业务日单次采集的事实入口不新增历史镜像
- [ ] **图表变更**：字体/颜色/数据源 → 更新本手册第 6 节
- [ ] **时区变更**：修改 `toLocaleTimeString` → 更新本手册第 5 节
- [ ] **隐藏分组**：修改 `HIDDEN_FLOWS` → 更新本手册第 3 节
- [ ] **重建容器**：`docker compose up -d --build`

---

## 11. 产量看板模块

> 新增于 2026-06-16

### 11.1 架构

| 文件 | 变更 |
|------|------|
| `iwork/queries.py` | Celery 构建员工×工序×工单×Flow 最低粒度事实 |
| `iwork/local_queries.py` | 镜像新增 5 个函数 |
| `iwork/read_model/queries.py` | 今日统计、排行和筛选项共享同一份快照事实 |
| `iwork/api_views.py` | 今日读 Redis 快照；历史日期继续读 `iwork_local` |
| `iwork/urls.py` | 新增 4 条路由（页面 + 3 API） |
| `iwork/views.py` | 新增 `kanban_page` |
| `iwork/templates/iwork/kanban.html` | 产量看板页面（Vue 3 + Tailwind CDN） |
| `iwork/templates/iwork/_header.html` | 添加"产量看板"标签 |
| `iwork/settings.py` | 新增 `KANBAN_DEFAULT_STEPNO='70'`、`KANBAN_DEFAULT_PAGE_SIZE=50` |

### 11.2 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kanban/` | 页面 |
| GET | `/api/kanban/stats/` | 统计汇总（worker_count, total_production, avg_production, max_production, max_worker_name） |
| GET | `/api/kanban/ranking/` | 排行榜分页列表（50条/页） |
| GET | `/api/kanban/filter-options/` | 筛选项（stepnos, wrk_orders, flows, employees） |

### 11.3 默认配置

```python
KANBAN_DEFAULT_STEPNO = '70'    # 默认工序
KANBAN_DEFAULT_PAGE_SIZE = 50   # 每页条数
```

### 11.4 筛选器

- **工序**：单选，默认 `'70'`
- **款号**：单选，默认全部（空字符串）
- **分组（Flow）**：多选下拉，默认全选（空数组）
- **员工**：单选，默认全部（空字符串），Flow 变化时级联更新
- **清空按钮**：恢复默认值（stepno='70'，其余全部）
- **日期**：日期选择器，默认当天

### 11.5 前端技术栈

- Vue 3 CDN（分隔符 `{[` `]}`）
- Tailwind CSS CDN（darkMode: 'class'）
- 统计卡片数字滚动动画
- 表格行滑入动画（rowIn）
- 柱状图升起动画（barIn）
- 排名 1/2/3 金银铜徽章
