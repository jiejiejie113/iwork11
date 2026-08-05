# 车间工效看板（iwork）— 开发规范手册

> 本手册是项目的活文档，每次修改必须同步更新对应章节。
> 最后更新：2026-08-05

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

当前业务日只允许对远程 `pytckreg3` 执行两类受控产量查询：
`get_read_model_fact_rows()` 的当天基础事实聚合，以及
`get_read_model_cumulative_rows()` 的当前工单累计事实聚合，两者必须各执行一次并共享
同一个可重复读事务水位。实时、当前日月趋势、生产详情、产品视图和 Kanban 必须由
`ReadModelFactSource` 在内存中从这两批不可变事实派生，禁止为任一今日视图追加其他
`pytckreg3` 查询。月度历史远程查询最多截止当前业务日的前一天；产品信息读取本地
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
1. “按生产线”后端查询继续通过 Flow 白名单过滤，隐藏分组数据不查、不缓存。
2. “按产品名称”是受控例外：后端按 `(WrkOrder, StepNo, Flow)` 聚合并返回全部
   Flow，同时通过 `normal_flows` 返回普通线白名单；前端默认仅显示普通线，可用
   “普通线”按钮在浏览器本地切换全部 Flow，不得为切换重复查询远程数据库。

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
    'product_name': str,   # 产品名称
    'order_no': str,       # 生产单号
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
{stepno: [{
    'wrk_order': str,
    'total_qty': int,
    'flows': list[str],
    'product_name': str,
    'order_no': str,
}]}
```

每个工序视图的 `flows` 必须按 `(StepNo, WrkOrder)` 隔离，禁止混入同一工单在其他
工序出现的分组。SSE 内嵌工单与首次加载的分页工单 API 必须同时提供产品名称、生产
单号和当前工序分组，避免一分钟刷新后覆盖为字段不完整的数据。

### 4.4 Flow 员工明细

`get_batch_flow_employees` 按 `(WrkOrder, StepNo)` 从 `Pywrkstp` 批量注入
`description`、`step_time` 和 `output_value`。员工节点汇总 `output_value`；任一工序
缺少标准工时时汇总值为 `null`。历史详情必须读取 `HistoricalStepSnapshot`，不得在
普通请求中回查远程元数据，避免元数据变化改写历史产值。

Flow 详情保存在当前版本的 `detail` 视图中。缓存不保存实时效率；接口按请求时刻注入
`work_minutes` 和 `employee_efficiency`，并通过响应头返回快照版本和陈旧状态。

累计产量直接从远程生产事实表按完整 `WrkOrder` 精确匹配，不再依赖 iGarment 创建
日期。查询必须排除 `RegDate IS NULL` 的无效登记记录，并通过单个 `WrkOrder IN (...)`
聚合查询按 `(Flow, RegPerSysID, StepNo, WrkOrder)` 粒度执行 `SUM(Qty)`；不得截取
工单前 6 位，不得先查询 `MIN(RegDate)` 后再执行第二次范围聚合，也不得按工单循环
请求远程数据库。当天事实与累计事实必须位于同一个 MySQL `REPEATABLE READ` 事务
快照内，再一起发布到同一 Redis 版本；Web/API 请求不得临时回源远程生产库。

累计产量的展示和聚合必须遵循以下边界：

1. 当前业务日的 Flow 详情在员工、工序、工单和 Flow 汇总层同时返回
   `cumulative_qty`；左侧工序栏默认显示今日产量，只允许通过“今日产量/累计产量”按钮
   切换汇总口径，工序顺序始终按工序号数值升序。
2. 产品树必须合并“当天产品视图已经出现的工单”所对应的累计事实，因此同一工单内
   “今日产量为 0、但历史累计产量大于 0”的工序仍需保留。当天完全未出现的工单不会
   仅因存在历史累计事实而重新加入产品树；产品、工单、工序和 Flow 四层累计值必须由
   当前节点集的同一批叶子事实逐级汇总。
3. 产品视图的累计产量指标只对当前业务日开放。切换到历史日期时必须隐藏累计产量按钮，
   如果浏览器曾保存该指标则回退到今日产量，不能把缺失的历史累计值当作有效数据。
4. 当前快照中没有匹配累计事实的叶子按累计产量 `0` 汇总。产值元数据不完整时界面显示
   `--`，参与产品树排序时按 `0` 处理，但不能把 `0` 回写到 API 或 Redis 快照中掩盖
   缺失的产值元数据。
5. 历史 Flow 快照目前不保存累计产量；历史 Flow 页面即使出现累计切换，其缺失值回退
   结果也只是兼容显示，不是真实累计数据，不得用于报表或跨日期比较。历史累计功能需在
   历史快照模型单独落地后才能开放。

### 4.5 整组目标产量与目标达成率

生产组（Flow）详情使用整组目标输入，不允许逐员工或逐工单编辑目标。当前页面通过
`POST /api/dashboard/set-targets/` 提交：

```json
{
  "flow": "SO3-L3A",
  "group_target": 1000,
  "work_hours": 10
}
```

整组目标按业务日期和 Flow 保存到本地 `group_target_production` 表，并缓存为
`group_target:{date}:{flow}`；计划工作时长换算成分钟保存到 `planned_work_minutes`，并
缓存为 `group_work_minutes:{date}:{flow}`。`work_hours` 必须大于 0 且不超过 24，允许
小数，保存时按四舍五入换算为整数分钟，且换算结果必须至少为 1 分钟；请求未提供时
沿用已有计划工作时长。

当前时段目标按有效工作分钟计算：

```text
取整工作分钟 = min(ceil(有效工作分钟 / 60) × 60, 计划工作分钟)
当前时段目标 = round_half_up(整组全天目标 × 取整工作分钟 / 计划工作分钟)
```

有效工作分钟必须先按第 5 节的班次规则扣除午休，再向上取整到下一整小时；已在整点时
不继续进位，超过计划工作时间时封顶为全天目标。历史日期或旧记录没有计划工作时长时，
当前时段目标等于整组全天目标。读取 Flow 详情时遵循以下规则：

1. 当前 Flow 出现的每道工序都获得完整的整组目标；整组目标为 1000 时，每道工序目标均为 1000。
2. 全天目标和当前时段目标分别按每道工序的去重员工人数分配整数个人目标；无法整除时
   按员工 ID 数值升序分配余数，确保个人目标合计严格等于对应工序目标。
3. 页面“目标”列展示当前时段个人目标；员工工序达成率 = 该员工在该工序所有工单的
   实际产量合计 / 当前时段个人目标 × 100%。
4. 同一员工负责多个本厂款号且工序相同时，只计算一份工序目标和达成率。展开表格必须
   将这两列按员工与工序合并单元格显示，不能按工单重复展示。
5. 员工汇总达成率 = 员工全部工序实际产量 / 员工全部当前时段目标合计 × 100%。
6. 未设置整组目标的旧日期继续读取旧员工/工单目标；新页面只提供整组目标和工作时间
   编辑入口。
7. “按工序”详情可能跨多个 Flow，因此不提供整组目标编辑，避免把单个目标错误应用到多个生产组。

接口返回 `group_target`、`current_group_target`、`work_hours` 和 `step_targets`。分配结果
仅在响应副本中注入，不得修改 Redis 版本化快照中的原始员工和工序数据。左侧工序栏
不显示目标值；展开明细列顺序固定为：员工 ID、本厂款号、工序号、工序描述、产量、
累计产量、总产量、目标、目标达成率、标准工时、产值、总产值、员工效率。

`statistics.py` 中 `get_batch_stats` 生成 `all` 视图时，`flows` 字段会跨工序合并去重，
同时必须保留 `product_name` 和 `order_no`。

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
- 产品视图默认固定图表：固定时产品区本身不滚动，仅下方树状表格滚动；取消固定时
  改由整个产品区统一纵向滚动，树状表格不得保留第二个纵向滚动容器。
- 产品区与树状表格只隐藏滚动条外观，必须保留滚轮、触摸和程序滚动能力。
- 树状表格表头必须使用 `sticky` 固定在当前滚动容器顶部；切换滚动方式后仍应保持可见。
- 产品接口只返回一份按 `(WrkOrder, StepNo, Flow)` 聚合的完整产品树及
  `normal_flows` 白名单；“普通线”按钮默认开启，树表和图表共同使用同一份本地过滤
  结果，切换时不得发起新请求。普通线开关不写入 `localStorage`，每次进入页面均回到
  默认开启状态。
- 产品图表指标是树表和图表的唯一排序来源：今日产量对应 `qty`，累计产量对应
  `cumulative_qty`，产值对应 `output_value`。产品名称、本厂款号和生产线层按当前指标
  降序；工序层不受指标切换影响，始终按工序号数值升序。
- 以上排序规则必须递归应用到每个树层级；指标值相同时保持输入的稳定顺序，不增加名称
  或 Flow 的次级排序。
- 图表只能读取当前焦点节点的直属子节点，并严格沿用树表顺序，禁止再对图表数据执行
  独立排序。切换指标后必须同时重建树表和图表，并保留仍然有效的展开路径。

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

### 9.1 实时数据 API → dashboard.html

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

### 9.2 生产详情 API → production_detail.html

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
| `group_target` | `groupTarget` | 整组全天目标 |
| `current_group_target` | `currentGroupTarget` | 按有效工作时长折算的当前时段目标 |
| `work_hours` | `workHours` | 计划工作小时数 |
| `step_targets` | 当前未直接绑定 | 顶层工序目标汇总，供接口核对和后续展示使用 |
| `employees[].step_targets` | `emp.step_targets` | 员工各工序的全天/当前目标及达成率 |
| `products` | `productList` | 按产品、工单、工序和 Flow 聚合的完整产品树 |
| `normal_flows` | `productNormalFlows` | 产品视图“普通线”本地过滤白名单 |
| `employees[].output_value` | `emp.output_value` | 员工总产值 |
| `employees[].employee_efficiency` | `emp.employee_efficiency` | 员工效率 |
| `source` | 历史快照标识 | `local_snapshot` 表示本地只读历史数据 |
| `snapshot_date` / `snapshot_version` | 历史状态 | 标识快照日期和发布版本 |

历史日期通过 URL 的 `date` 参数传递。Flow、工序和产品视图之间的导航必须保留日期；
历史日期禁止目标编辑和 60 秒自动刷新。快照不存在时，前端应调用
`POST /api/history/snapshots/<date>/ensure/`。接口只提交后台任务并返回 202；前端显示构建状态并在完成后重试原 GET；构建
失败时显示明确错误，不能把错误 JSON 或空列表当作有效历史数据。历史目标只使用后端
按日期返回的 `target` / `wo_targets`，不得使用浏览器旧值覆盖。

### 9.3 修改规则

1. **后端新增字段** → 前端 `Object.assign` / `map` 中同步添加
2. **后端删除字段** → 前端引用处同步删除，否则显示 `undefined`
3. **后端重命名字段** → 前端所有引用处同步修改

---

## 10. 生产订单每日同步

### 10.1 数据流与一致性

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

### 10.2 计划任务

- 任务名：`\DKT\iwork-Production-Orders-Sync`；
- 执行账户：`SYSTEM`，最高权限；
- 时间：服务器北京时间每天 `00:00`；
- 并发策略：`IgnoreNew`，脚本另使用全局互斥锁；
- 超时：20 分钟；失败后每隔 5 分钟重试，最多 2 次；
- 安装入口：`scripts\install-production-orders-sync-task.ps1`；
- 执行入口：`scripts\sync-production-orders.ps1`，使用 `-Force` 可忽略哈希强制发布。

脚本以 SHA-256 记录上次成功快照。源文件哈希未变化时返回成功并跳过 Docker；只有导入成功后才原子更新成功状态，失败不得覆盖成功哈希。

### 10.3 看门狗维护窗口

同步脚本在导入期间创建带 30 分钟 TTL 的维护标记：

```text
D:\DM\DTD_nginx\logs\watchdog\maintenance\iwork-production-orders.json
```

有效维护期只跳过 iwork HTTP 探测。Docker Engine、`DKT_iwork` 容器、其他容器及其他应用 HTTP 仍正常监控。Python 告警监控保留 iwork 维护前状态，不发送虚假故障或恢复邮件。过期、损坏或字段不匹配的标记一律不放行。

### 10.4 iGarment 创建日期快照同步

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
- `客戶訂單編號` 为空的源行允许保留；当前累计产量查询不读取该快照，数据模型、查询
  接口和同步任务继续保留，供后续订单信息功能使用。

### 10.5 累计产量源明细审计导出

`scripts/export_wrkorder_cumulative_details.py` 是人工核对累计产量差异的只读审计工具，
不属于定时同步、Redis 快照构建或应用运行依赖。使用时只修改脚本顶部的全局
`WRKORDER`，脚本必须按完整 `WrkOrder` 精确匹配 `pytckreg3`：

- 查询不得添加日期、Flow 或工序白名单，不得执行 `SUM`、`GROUP BY`、去重或字段转换；
- 导出字段只由脚本顶部 `SOURCE_FIELDS` 定义，源记录逐行写入，按工序号、登记日期时间、
  TicketNo 和 SeqNo 排序，便于与应用聚合结果反向核对；
- 运维必须提供只读生产库账号；脚本只保证执行参数化 `SELECT`，不会验证账号权限。
  凭据按顺序从 `scripts/export.env`、当前工作目录的 `export.env` 或现有 `iwork/.env`
  读取，不得写入脚本或提交到 Git；
- 使用服务端游标和 `openpyxl` 只写模式处理大结果集，输出到 `scripts/output`，文件名为
  `pytckreg3_<WrkOrder>_累计产量源明细_<时间戳>.xlsx`；
- 文件先写入同目录唯一临时文件，成功关闭后再替换为正式文件；失败时清理临时文件并
  保留日志，不能留下看似完整的半成品。

## 11. 修改检查清单

每次修改后，按以下清单检查：

- [ ] **配置变更**：`settings.py` → 更新本手册第 2 节
- [ ] **字段变更**：API 返回字段 → 更新本手册第 4/9 节 + 前端模板
- [ ] **查询变更**：`queries.py` 的历史同语义查询 → 同步修改 `local_queries.py`；仅用于当前业务日单次采集的事实入口不新增历史镜像
- [ ] **图表变更**：字体/颜色/数据源 → 更新本手册第 6 节
- [ ] **时区变更**：修改 `toLocaleTimeString` → 更新本手册第 5 节
- [ ] **Flow 语义**：按生产线继续应用白名单；按产品名称返回完整 Flow，并在浏览器本地切换普通线
- [ ] **累计产量**：完整工单匹配、排除空 RegDate、单 SQL 聚合、同事务水位、完整产品 Flow 和历史日期限制保持一致
- [ ] **目标规则**：整组目标、计划工作时长、整点取整、员工工序合并展示同时覆盖测试
- [ ] **本地交付**：代码或配置变更先通过风险相称的相关测试和涉及文件 Ruff，再按规范提交 Git；
  使用 `deploy.ps1 -Environment local` 或 `..\DTD_nginx\scripts\Rebuild-Local.ps1 -Target iwork`
  完成最终重建并验证容器状态和实际接口。用户明确要求暂不提交、暂不部署或仅修改代码时
  从其要求；仅文档变更无需重建应用

---

## 12. 产量看板模块

> 新增于 2026-06-16

### 12.1 架构

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

### 12.2 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kanban/` | 页面 |
| GET | `/api/kanban/stats/` | 统计汇总（worker_count, total_production, avg_production, max_production, max_worker_name） |
| GET | `/api/kanban/ranking/` | 排行榜分页列表（50条/页） |
| GET | `/api/kanban/filter-options/` | 筛选项（stepnos, wrk_orders, flows, employees） |

### 12.3 默认配置

```python
KANBAN_DEFAULT_STEPNO = '70'    # 默认工序
KANBAN_DEFAULT_PAGE_SIZE = 50   # 每页条数
```

### 12.4 筛选器

- **工序**：单选，默认 `'70'`
- **款号**：单选，默认全部（空字符串）
- **分组（Flow）**：多选下拉，默认全选（空数组）
- **员工**：单选，默认全部（空字符串），Flow 变化时级联更新
- **清空按钮**：恢复默认值（stepno='70'，其余全部）
- **日期**：日期选择器，默认当天

### 12.5 前端技术栈

- Vue 3 CDN（分隔符 `{[` `]}`）
- Tailwind CSS CDN（darkMode: 'class'）
- 统计卡片数字滚动动画
- 表格行滑入动画（rowIn）
- 柱状图升起动画（barIn）
- 排名 1/2/3 金银铜徽章
