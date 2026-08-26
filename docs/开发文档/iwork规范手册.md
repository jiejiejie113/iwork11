# 车间工效看板（iwork）— 开发规范手册

> 本手册是项目的活文档，每次修改必须同步更新对应章节。
> 最后更新：2026-08-26

---

## 1. 架构概览

```
Uvicorn ASGI (4 workers)
    ├── 实时数据：Celery Beat (60s) → 单次基础事实查询 → 内存派生 → 版本化 Redis 快照
    ├── Web/SSE：Redis Pub/Sub 版本通知 → Worker 共享负载 → 最新事件队列
    ├── 今日生产详情：轻量 SSE 版本通知 → 当前视图 REST 读取 Redis 快照
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
| `sse_events.py` | Redis 版本通知、Worker 级订阅、最新事件队列和共享负载单飞构建 |
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
- DITU 命名迁移后正式生产入口为 `dituportal.dongming.local`，认证入口为
  `auth.dituportal.dongming.local`；观察期内 `DJANGO_ALLOWED_HOSTS` 必须同时保留
  两个旧 DKT 域名，由 Portal Nginx 执行 307 兼容跳转，iwork 不自行生成跨域跳转；
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
| `SSE_NOTIFICATION_CHANNEL` | 完整快照切换后发布轻量版本通知的 Redis 频道 | `tasks.py` / `sse_events.py` |
| `SSE_CLIENT_QUEUE_SIZE` | 每客户端最新通知队列容量，固定为 1 | `sse_events.py` |
| `SSE_PAYLOAD_CACHE_SIZE` | 每 Worker 共享序列化负载的最大键数量，默认 64 | `sse_events.py` |
| `SSE_PAYLOAD_BUILD_CONCURRENCY` | 不同日期/工序负载的最大并行构建数，默认 4 | `sse_events.py` |
| `SSE_HEARTBEAT_SECONDS` | SSE 注释心跳间隔，默认 15 秒 | `api_views.py` |
| `SSE_CONNECTION_LEASE_SECONDS` | 每条SSE连接的授权租约，默认60秒；到期正常结束并由EventSource重连重新经过Portal应用权限检查 | `api_views.py` |
| `SSE_NOTIFICATION_POLL_SECONDS` | Pub/Sub 丢消息时的共享版本核对间隔，默认 60 秒 | `api_views.py` / `sse_events.py` |
| `HISTORY_SNAPSHOT_LOCK_TIMEOUT` | 历史快照构建和执行中请求锁租约，默认 1800 秒 | `history_store.py` / `tasks.py` |
| `HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL` | 历史快照构建锁续租间隔，默认 60 秒 | `history_store.py` |
| `HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT` | 入队确认阶段的循环续租时长，默认 30 秒 | `api_views_local.py` |
| `HISTORY_SNAPSHOT_REQUEST_RENEW_INTERVAL` | Broker 阻塞期间请求锁续租间隔，默认 10 秒 | `api_views_local.py` |

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
3. “按初版款号”与“按生产线”使用同一普通线口径，只允许聚合
   `ALLOWED_FLOWS` 内的 `flow_employees`；空初版款号统一归入“未设置”，不得把
   产品视图的全 Flow 例外扩展到该视图。

**当前隐藏分组**（21 个）：

| 前缀 | Flow 列表 |
|------|-----------|
| SO2 | SO2-L2A ~ SO2-L2G（7 个） |
| SO6 | SO6-L6A ~ SO6-L6G（7 个） |
| SO10 | SO10-L10A ~ SO10-L10G（7 个） |

**修改方式**：编辑 `settings.py` 中 `HIDDEN_FLOWS` 列表，重启服务生效。Celery 会在下一个 60s 周期自动刷新 Redis 缓存。

---

## 4. 今日/当日生产列表字段规范

生产列表在两个页面使用：实时数据看板（dashboard）和生产详情（production_detail）。
界面统一称为“今日生产列表”；历史日期称为“当日生产列表”。API 为兼容既有消费者继续
使用 `workorders`、`wrk_order` 和 `total_qty` 字段名，前端显示名称不得再写“工单号”或
“总产量”。

### 4.1 API 返回字段

```python
# get_workorders_paginated / get_workorders_list 返回
{
    'wrk_order': str,      # 本厂款号
    'initial_style_no': str, # 初版款号，来源 pywrkord.ExtField01
    'total_qty': int,      # 今日/当日产量
    'worker_count': int,   # 人数（仅 paginated 版本）
    'flows': list[str],    # 关联的 Flow 分组列表
    'product_name': str,   # 产品名称
    'order_no': str,       # 生产单号
}
```

### 4.2 前端显示

| 页面 | 显示字段 | 分组列 |
|------|----------|--------|
| 实时数据看板 | 本厂款号、初版款号、今日产量、产品名称、生产单号、分组 | 具体分组名称列表（如 "SO3-L3A, SO5-L5E"） |
| 生产详情概览 | 本厂款号、初版款号、今日/当日产量、分组 | 具体分组名称列表 |

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
    'initial_style_no': str,
}]}
```

每个工序视图的 `flows` 必须按 `(StepNo, WrkOrder)` 隔离，禁止混入同一工单在其他
工序出现的分组。SSE 内嵌工单与首次加载的分页工单 API 必须同时提供产品名称、生产
单号、初版款号和当前工序分组，避免一分钟刷新后覆盖为字段不完整的数据。

### 4.4 Flow 员工明细

`get_batch_flow_employees` 按 `(WrkOrder, StepNo)` 从 `Pywrkstp` 批量注入
`description`、`step_time` 和 `output_value`。员工节点汇总 `output_value`；任一工序
缺少标准工时时汇总值为 `null`。历史详情必须读取 `HistoricalStepSnapshot`，不得在
普通请求中回查远程元数据，避免元数据变化改写历史产值。

初版款号必须按完整 `WrkOrder` 从远程只读表 `payroll.pywrkord` 一次批量读取，
`ExtField01` 去除首尾空白后映射为 `initial_style_no`。该查询和 `pytckreg3` 当日事实必须
位于 Celery 的同一 `REPEATABLE READ` 事务水位；Web 请求禁止远程回源。初版款号进入
实时生产列表、Flow 员工步骤、Flow 概览和产品树。Flow 概览必须从该分组全部工序记录
收集当天出现的初版款号；每个初版款号的件数只统计 `ALLOWED_FLOWS_STEPNO`（当前工序
70），没有工序 70 记录的初版款号仍保留并显示 0 件，避免同一件产品在多工序重复累计。

历史快照把 `initial_style_no` 冻结在 `HistoricalStepSnapshot`。新增字段上线后使用
`backfill_historical_initial_styles` 幂等回填：只处理成功快照中的空字段，按日期使用
本地事务批量更新，不删除或重建 `HistoricalProductionFact`；只有实际改变的日期才将
`HistoricalSyncState.snapshot_version` 递增一次。远程没有映射时保留空字符串并告警。

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
8. Flow 详情的整组目标和工作时间输入框在表格、卡片布局中始终可见；未点击“编辑”或
   查看历史日期时必须为只读。只有今日页面点击“编辑”后才能输入、保存或取消。

接口返回 `group_target`、`current_group_target`、`work_hours` 和 `step_targets`。分配结果
仅在响应副本中注入，不得修改 Redis 版本化快照中的原始员工和工序数据。左侧工序栏
不显示目标值；展开明细列默认顺序为：员工 ID、初版款号、本厂款号、工序号、工序描述、
今日/当日产量、累计产量、员工今日/当日产量、目标、目标达成率、标准工时、产值、总产值、
员工效率。Flow 详情的初版款号筛选控件放在“员工汇总”左侧，默认“全部初版款号”，按
员工步骤中的 `initial_style_no` 过滤表格、卡片和左侧工序汇总。

Flow 员工明细表提供“字段设置”面板，展开和收起视图分别维护列显隐、拖拽顺序和手动
列宽。设置存入浏览器 `localStorage` 的 `production-detail-columns:v1`，在不同 Flow
页面间复用，不写入后端数据或 Redis；新增字段必须在读取旧设置时自动追加，已删除或
未知字段必须忽略。表头右边界支持鼠标和触控笔拖动，宽度限制为 72～480 像素；所有
字段默认单行不换行，超出列宽时以省略号显示，完整的文本字段通过单元格标题查看。
收起视图必须在员工 ID 后显示当前筛选结果内去重汇总的初版款号和工序号；初版款号
自然排序，工序号按数值升序，多个值使用顿号连接。“字段设置”中的字段卡片必须提供
普通悬停、拖动中和目标卡片三种视觉反馈，并在交换顺序时使用位移动画。“恢复默认”
只重置当前展开/收起视图，不能影响另一视图的用户设置。
右侧明细卡片作为 Flex 子项必须保留 `min-width: 0`，使固定宽度表格在卡片内部产生
横向溢出；不得仅使用 `overflow: visible`，否则卡片会被表格撑宽并同时破坏横向滚动条
和按住表格拖拽查看功能。

### 4.6 按初版款号生产详情

生产详情概览入口固定为“按生产线 / 按初版款号 / 按产品名称”。“按初版款号”替换原
“按工序”概览按钮，但旧工序 API 与 `/production/detail-data/stepno/<stepno>/` 页面继续
保留兼容，不得因导航移除而删除路由。

初版款号视图只对既有普通线 `flow_employees` 快照做内存聚合，不新增远程 SQL、iGarment
依赖或 Redis 数据结构：

1. `GET /api/dashboard/detail/initial-style-overview/?date=YYYY-MM-DD` 返回初版款号、
   总产量、跨生产线去重员工数、本厂款号数、各生产线产量及全部工序汇总。卡片总件数、
   分组件数和图表产量只累计工序 70，避免把同一件产品的多道工序重复相加；员工数与
   本厂款号数仍按全部工序去重统计。卡片按初版款号自然顺序，“未设置”固定最后；卡片内
   生产线按工序 70 产量降序，图表按总件数降序显示产量与去重人数。
2. “按生产线”和“按初版款号”卡片都必须从完整 `stepnos` 汇总中显示最慢工序。最慢
   工序是卡片内产量最低的已出现工序；低于平均百分比按
   `(工序平均产量 - 最慢工序产量) / 工序平均产量 × 100%` 四舍五入为整数。并列最低时
   按工序号升序取第一个；无工序时不显示，平均产量为 0 时显示 `0%`。
3. “按生产线”和“按初版款号”概览卡片使用相同的标题、人数、工序70汇总、下级对象
   数量、分项标签、今日/当日产量和最慢工序结构。生产线卡片的下级对象是初版款号，
   初版款号卡片的下级对象是生产线；两者分项件数均使用工序70口径。生产线独有的目标
   与效率作为公共结构后的扩展保留，初版款号卡片不得因此新增跨生产线目标。
4. `GET /api/dashboard/detail/initial-style/?initial_style_no=...&date=YYYY-MM-DD`
   返回该初版款号跨生产线的员工、工序和本厂款号明细。参数必须显式存在，空字符串表示
   “未设置”；每条工序必须保留 `flow`，同一员工跨生产线只计一人但产量完整求和。
5. 今日接口只读 Redis 当前版本详情快照，历史接口只读本地成功快照；Web 请求不得远程
   回源。今日页面随统一 SSE 快照通知静默刷新，历史日期不建立 EventSource。
6. 初版款号详情只提供表格视图，不显示表格/卡片切换入口，也不得渲染员工卡片。表格
   工具栏提供“全部分组”筛选、字段设置、今日/当日产量与累计产量切换；分组筛选必须
   同时影响工序栏、员工明细和汇总字段。
7. 初版款号详情不提供整组目标编辑，但必须只读显示分组详情中已设置的个人目标和目标
   达成率。后端必须先在完整 Flow 员工集合中沿用 `_distribute_group_target` 分配目标并
   计算达成率，再筛选当前初版款号；禁止按款号子集重新分配或重算。跨 Flow 的相同工序
   号按 `(Flow, StepNo)` 隔离，不能合并成同一目标单元格。
8. 初版款号详情使用独立字段配置：展开默认为员工 ID、生产线、本厂款号、工序号、工序
   描述、今日/当日产量、累计产量、员工产量、目标、目标达成率、标准工时、产值、总产值、
   员工效率；收起默认为员工 ID、生产线汇总、工序号汇总、员工产量、累计产量、目标、
   目标达成率、总产值、员工效率。
   配置继续存入 `production-detail-columns:v1` 的 `initial_style_expanded` 和
   `initial_style_collapsed`，不能覆盖生产线详情的 `expanded` / `collapsed` 配置。

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
- 产品维度池顺序为“产品名称、初版款号、本厂款号、工序号、生产线”。初版款号只新增到
  备选区，默认激活层级仍为产品名称，读取旧浏览器状态时不得自动插入该维度。
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

该端点有两种负载模式：

- 默认模式：向实时看板发送 KPI、图表、工序和第一页工单数据；
- `mode=notification`：只发送 `snapshot_published`、业务日期、快照版本、生成时间和
  陈旧标记，供今日生产详情在统一发布水位到达后刷新当前 REST 视图。通知模式不得
  携带实时看板业务负载。

**实现要点**：
- 使用 `StreamingHttpResponse` + 异步生成器
- Celery 只能在完整快照发布并原子切换 `current` 后发送 Redis 版本通知
- 每个 Uvicorn Worker 最多一个 `redis.asyncio` 订阅任务，断线后指数退避并带随机抖动重连
- Pub/Sub 消息只包含协议版本、业务日期和快照版本，禁止携带业务负载
- `sync_to_async(thread_sensitive=False)` 包装同步 Redis 读取，不阻塞事件循环
- 心跳：每 15 秒发送 SSE 注释（`: heartbeat\n\n`）
- 数据推送：快照通知到达后立即读取当前完整版本并广播；60 秒核对仅作丢消息补偿
- 同 Worker 内相同 `(business_date, stepno)` 使用单飞任务，只读取和序列化一次
- 不同负载最多并行构建 4 个，超过部分进入异步等待队列
- 每客户端队列容量固定为 1；队列满时覆盖旧通知，只保留最新快照版本
- 每条数据事件包含 `snapshot_version`、`generated_at` 和 `stale`
- 快照不可用时发送 `snapshot_unavailable` 事件，仍继续发送 15 秒心跳
- 前端直接使用 `msg.data.workorders`，禁止 SSE 事件后再次请求工单接口
- 前端按 `snapshot_version` 去重，并用 `generated_at` 拒绝旧事件覆盖新数据
- 通知发送失败只记录告警，禁止重新执行完整远程数据库采集
- 今日生产详情禁止再建立浏览器独立的 60 秒刷新计时器；生产线、初版款号、工序、产品和明细
  视图必须由轻量快照通知触发静默刷新
- 生产详情切换到历史日期时必须关闭 EventSource；切回今日时在初次 REST 数据加载完成
  后重新连接，避免初始通知和首屏请求竞争
- 同一详情页面同一时刻只允许一个静默刷新；刷新期间的新通知覆盖待处理旧通知，只保留
  最新版本；请求失败按 5 秒到 60 秒指数退避并加入随机抖动，日期或连接代次改变后
  丢弃晚到响应，避免多客户端同步重试形成惊群

**容量基线（2026-08-07，改造前本地 4 Worker）**：100 连接成功率 100%、p99
1.45 秒；200 连接虽全部成功但 p99 2.75 秒，超过 2 秒稳定门槛；500 连接 p99
9.52 秒。因此改造前的稳定预算按 100 个同时建连计算，200 个起必须依赖共享负载
和背压队列，不能把“连接成功”等同于“延迟稳定”。

**改造后本地验收（相同 4 Worker、工序 70）**：

| 同时建连数 | 成功率 | 首事件 p99 | 结论 |
|-----------:|-------:|-----------:|------|
| 50 | 100% | 137 ms | 稳定 |
| 100 | 100% | 153 ms | 稳定 |
| 200 | 100% | 270 ms | 稳定 |
| 300 | 100% | 566 ms | 稳定 |
| 500 | 100% | 959 ms | 稳定 |
| 750 | 100% | 1.27 s | 稳定 |
| 1000 | 100% | 2.14 s | 超过 2 秒门槛 |

本机当前配置按 2 秒 p99 门槛可确认的稳定容量为至少 750、低于 1000；1000 个连接
仍全部成功，只是不再满足延迟目标。该数字是本地应用层直连结果，不代表 Portal、认证、
Nginx 和真实浏览器整链路的容量承诺。容量会随主机、Worker 数、负载大小和网络变化，
变更这些条件后必须重测。

全工序大事件（约 240 KiB/事件）复测的容量边界一致：750 连接 100% 成功、p99
1.57 秒；1000 连接 100% 成功、p99 2.57 秒。因此“至少 750、低于 1000”的
稳定区间同时覆盖默认工序 70 和当前全工序负载；新增更大字段后仍需重新测试。

真实发布广播另以 200 个已连接客户端等待下一次 Celery 快照验证：200/200 收到同一
新版本，客户端到达时间相对最早事件的 p99 离散为 41.6 ms、最大 42.0 ms；容器日志
显示 4 个 Worker 订阅者均收到发布通知。该结果证明数据更新由服务端发布水位统一触发，
不再依赖每个客户端各自的 60 秒计时器。

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
| `workorders` | `data.workorders` | 今日/当日生产列表 |
| `workorders[].initial_style_no` | `wo.initial_style_no` | 初版款号 |
| `all_stepnos` | `data.all_stepnos` | 工序下拉列表 |

### 9.2 生产详情 API → production_detail.html

| API 字段 | 前端变量 | 用途 |
|----------|----------|------|
| `flow_overview` | `flowCards` | Flow 概览卡片；完整工序汇总用于计算最慢工序 |
| `flow_overview.*.initial_styles` | `card.initial_styles` | 全工序收集初版款号、工序70统计件数；支持概览部分匹配搜索 |
| `flow_overview.*.stepnos[70].qty` | `card.output_qty` | 生产线卡片显示的工序70总件数 |
| `initial-style-overview.items` | `initialStyleCards` | 普通线初版款号卡片、工序70总件数、去重人数和本厂款号数 |
| `initial-style-overview.items[].flows` | `card.flows` | 初版款号在各生产线的工序70件数与人数 |
| `initial-style-overview.items[].stepnos` | `card.stepnos` | 初版款号完整工序汇总，用于计算最慢工序和低于平均百分比 |
| `workorders.items` | `workorderList` | 工单汇总列表 |
| `workorders.items[].initial_style_no` | `wo.initial_style_no` | 今日/当日生产列表初版款号 |
| `employees` | `employees` | 员工明细（详情页） |
| `employees[].steps[].description` | `row._step.description` | 组合键工序描述 |
| `employees[].steps[].step_time` | `row._step.step_time` | 标准工时 |
| `employees[].steps[].output_value` | `row._step.output_value` | 工序产值 |
| `employees[].steps[].initial_style_no` | `row._step.initial_style_no` | Flow 表格、卡片和初版款号筛选 |
| `initial-style.employees[].steps[].flow` | `row._step.flow` | 初版款号详情每条工序的生产线归属 |
| `initial-style.employees[].steps[].target` | `getRowStepTarget(row)` | 完整分组口径分配的只读个人目标 |
| `initial-style.employees[].steps[].target_rate` | `getRowStepTargetRate(row)` | 完整分组实际产量计算的只读目标达成率 |
| `initial-style.flow_targets` | 分组目标摘要 | 各分组整组目标、当前时段目标和计划工作时间 |
| `employees[].steps[].cumulative_qty` | `row._step.cumulative_qty` | 员工/工序/工单累计产量 |
| `employees[].cumulative_qty` | `emp.cumulative_qty` | 员工累计产量 |
| `cumulative_qty` | `detailSummary.cumulative_qty` | 当前 Flow 累计产量汇总 |
| `group_target` | `groupTarget` | 整组全天目标 |
| `current_group_target` | `currentGroupTarget` | 按有效工作时长折算的当前时段目标 |
| `work_hours` | `workHours` | 计划工作小时数 |
| `step_targets` | 当前未直接绑定 | 顶层工序目标汇总，供接口核对和后续展示使用 |
| `employees[].step_targets` | `emp.step_targets` | 员工各工序的全天/当前目标及达成率 |
| `products` | `productList` | 按产品、工单、工序和 Flow 聚合的完整产品树 |
| `products[].wrk_orders[].initial_style_no` | 产品叶子 `initial_style_no` | 产品视图可选“初版款号”层级 |
| `normal_flows` | `productNormalFlows` | 产品视图“普通线”本地过滤白名单 |
| `employees[].output_value` | `emp.output_value` | 员工总产值 |
| `employees[].employee_efficiency` | `emp.employee_efficiency` | 员工效率 |
| `source` | 历史快照标识 | `local_snapshot` 表示本地只读历史数据 |
| `snapshot_date` / `snapshot_version` | 历史状态 | 标识快照日期和发布版本 |

今日生产详情的 REST 接口仍负责返回具体业务数据，但刷新时机统一由
`/api/dashboard/stream/?mode=notification` 驱动。服务端快照发布后，前端按当前状态只
刷新正在显示的生产线概览、初版款号概览、工序概览、产品概览或员工明细；不得接收并丢弃实时看板大包，
也不得恢复每浏览器独立 60 秒计时器。`EventSource` 断线由浏览器自动重连，服务端首次
连接和 60 秒共享核对保证重连或 Pub/Sub 丢消息后仍能发现当前版本。

历史日期通过 URL 的 `date` 参数传递。Flow、工序和产品视图之间的导航必须保留日期；
历史日期禁止目标编辑和 60 秒自动刷新。快照不存在时，前端应调用
`POST /api/history/snapshots/<date>/ensure/`。接口只提交后台任务并返回 202；前端显示构建状态并在完成后重试原 GET；构建
失败时显示明确错误，不能把错误 JSON 或空列表当作有效历史数据。历史目标只使用后端
按日期返回的 `target` / `wo_targets`，不得使用浏览器旧值覆盖。

历史快照入队使用带唯一所有权令牌的 Redis 请求锁防止前端轮询重复提交。Web 请求取得锁后，
必须通过 Redis 锁对象的 `locked()` 原生语义检查真实构建锁，不能使用 `cache.get()` 读取
redis-py 写入的原始锁值。请求锁首次申请使用完整构建时长保护续租器启动窗口，申请成功后
立即启动短租约续租器；真实构建锁检查及 Broker 调用阻塞期间每 10 秒检查一次，仅在剩余
TTL 不足 30 秒时原子补回 30 秒，
避免入队流程尚未返回时锁先过期。Broker 确认成功后，必须先停止并等待旧续租操作结束，再
提升为完整构建时长；后台续租必须使用带所有权校验的原子封顶语义，晚到的 Web 续租不能
覆盖或缩短 Celery 已提升的长租约，也不能让待确认 TTL 无界累积。提交失败且 Redis 清理
暂时不可用时也能在短时间内自愈。Broker 已接收任务但请求锁丢失、完整租约提升失败或
Redis 确认异常或完成状态查询异常时，接口必须返回带
`history_snapshot_queue_unavailable` 的 503，不能把
未受完整租约保护的任务报告为 202 成功；前端后续重试由所有权令牌决定等待或重新入队。
若 Worker 已在最终租约确认前完成并发布快照，则接口应返回 200 和已发布快照，不能把
正常完成后的锁释放误判为队列故障。
Celery 任务
通过随任务传递的
令牌恢复并续租所有权，中间重试保留请求锁，成功、最终失败或遇到其他构建者时使用令牌
比较释放。旧任务失去令牌后必须直接退出，不得构建快照或删除新一代请求锁。

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
不属于定时同步、Redis 快照构建或应用运行依赖。脚本通过顶部全局配置显式选择模式：

| `EXPORT_MODE` | 配置项 | 行为 | 适用场景 |
| --- | --- | --- | --- |
| `detail`（默认） | `WRKORDER` | 按一个完整工单号逐行导出全部源字段，不汇总、不去重 | 核对单工单累计产量差异和追溯源记录 |
| `compact` | `WRKORDERS` | 批量输出各工单最早 `RegDate`，以及工序 1、3、6 的 `Qty` 总和 | 一次核对多个工单的起始日期和指定工序累计量 |

默认使用 `detail`，避免误操作触发大批量汇总。每次执行前必须同时检查
`EXPORT_MODE` 和对应的 `WRKORDER` / `WRKORDERS`，不能只修改工单配置而忽略当前模式。

`detail` 模式必须按完整 `WrkOrder` 精确匹配 `pytckreg3`：

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

`compact` 模式是受控的显式例外，必须遵循以下口径：

- 使用一个参数化 `WrkOrder IN (...)` 查询，并按完整 `WrkOrder` 分组；不得按工单循环查询；
- `起始RegDate` 使用该工单全部源记录的 `MIN(RegDate)`。工序条件不能提前放入 `WHERE`，
  否则会把起始日期错误限制为工序 1、3、6 的最早日期；
- 只对 `COMPACT_STEP_NOS` 中的工序分别执行条件 `SUM(Qty)`，当前固定为工序 1、3、6；
- 输出顺序必须与 `WRKORDERS` 配置一致。生产表中不存在的工单仍输出一行，起始日期为空，
  三个工序数量为 0，不能静默删除；
- 输出文件名为 `pytckreg3_工单累计产量精简汇总_<时间戳>.xlsx`，同样使用唯一临时文件
  完成后替换，不得留下半成品。

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
- [ ] **明细表列设置**：展开/收起配置隔离、显隐、顺序、宽度、默认不换行和旧配置兼容同时覆盖测试
- [ ] **初版款号**：`pywrkord` 批量只读、同事务水位、工序70卡片口径、今日/历史字段、
  产品备选维度、普通线初版款号概览/详情、分组筛选、完整分组口径只读目标、独立列配置
  和历史幂等回填同时覆盖测试
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

---

## 13. 账号职能、目标责任与站内警报

### 13.1 身份边界

- 写接口必须使用Nginx/Authorizer注入的稳定`Remote-Subject`。
- iwork只信任`IWORK_TRUSTED_PROXY_HOSTS`解析出的明确代理地址；禁止按整个私网网段信任身份头。
- 可信代理声明中的Keycloak短组名`admin`或全路径组名`/admin`推导管理员；当日有效`ManagedFlowAssignment`推导组长；其余iwork账号为普通用户。不得接受其他管理员组名。
- 本地Principal只保存展示快照，授权判断始终使用当前请求身份和有效分配。

### 13.2 目标责任

- 管理接口`GET /api/account-admin/flows/`只允许管理员访问，返回
  `VISIBLE_FLOWS`作为Portal分配页面的候选清单。
- 创建Flow分配未提供`effective_date`时默认取当前业务日，并立即生成或刷新该日责任；
  截止时间后分配会直接形成逾期责任，不自动顺延到下一业务日。
- 每日责任必须固化截止时间；当天新增的有效负责人应立即追加到负责人快照，
  已进入快照的历史负责人不得删除。负责人全部撤销时按既有规则豁免未完成责任，
  当天重新分配后恢复为待提交或逾期，保证分配立即生效且历史责任关系可审计。
- 组长只能写当前业务日且属于自己的Flow；历史修正和旧目标格式只允许管理员。
- 0目标属于有效提交，不得用“大于0”判断是否填写。
- 目标、责任状态和审计日志必须使用`iwork_local`同一事务保存。
- Flow负责人写入必须通过Portal轻量账号接口实时复验目标subject和`/apps/iwork`；
  不能只依赖Portal页面按钮或代理层校验。复验必须携带当前管理员会话、使用固定
  内网URL、禁止重定向，Portal的`access_only`查询不得回调iwork。
- 默认截止时间和业务时区统一由`IWORK_TARGET_SUBMISSION_DEFAULT_DEADLINE`、
  `IWORK_BUSINESS_TIME_ZONE`配置，业务模块和模型不得硬编码。

### 13.3 警报与通知

- 快照发布只异步入队，不得因警报故障回滚Redis current指针。
- 警报任务只进入`alerts`队列，由`DKT_iwork_alert_worker`消费。
- 事件、评估运行、投递必须使用数据库唯一约束和领取租约保证幂等。
- 保存订阅、生成受众和读取通知时都要重新校验当前角色及Flow范围。
- 通知SSE只允许发送通用唤醒，正文必须由经过当前身份过滤的HTTP接口重新读取。
- 通知列表HTTP响应可以返回经过当前身份过滤的事件`payload`，每日责任摘要在打开、
  恢复和再次打开时都必须同步刷新payload，禁止展示旧责任状态。
- 通知抽屉默认先显示未读消息，已读消息折叠展示；只有带
  `payload.type=daily_summary`的通知允许打开责任详情。

### 13.4 生产详情账号视图

- 按生产线概览始终展示全部可见分组；当前账号负责的分组置顶归入“我管理的分组”，
  其余分组在下方单独展示，搜索条件同时作用于两个区域。
- 分组展示顺序不得影响目标写入权限；目标编辑仍以当前请求身份和有效Flow分配判断。

---

## 14. GitHub Actions生产交付门禁

### 14.1 Skill版本与安装

- `dkt-cicd`版本化源码固定存放于`tools/skills/dkt-cicd`，用户目录
  `%USERPROFILE%\.agents\skills\dkt-cicd`仅为安装副本。
- 修改Skill后必须运行`scripts/Install-DktCicdSkill.ps1`，并通过
  `tests/test_install_dkt_cicd_skill.ps1`验证文件清单和SHA-256一致。
- Skill脚本和测试必须同时通过PowerShell 7与Windows PowerShell 5.1解析及行为测试；
  对预期非零的子进程调用应显式检查退出码，不能依赖不同版本对stderr的默认处理差异。
- Skill只能使用当前Windows用户已经登录的`gh`，不得读取或保存Token、Cookie、私钥或
  `dkt-secrets.env`。

### 14.2 Commit与Digest绑定

- CI、GHCR发布、生产预检和部署只接受`Keycloak`远程分支当前完整Commit。
- 生产预检和部署必须重新读取同一Commit的成功Release日志；iwork输入Digest必须与
  `ghcr.io/guchenkano/iwork`发布产物完全一致。
- 只校验`sha256:`格式不构成有效准入，Release日志缺失、Digest不唯一或不一致时必须
  fail-closed。
- 新Tag首次推送后，GHCR清单可能短暂不可查询；发布Workflow只允许在`docker push`成功后
  对Digest解析执行6次、每次间隔5秒的有界重试。发布前的复用检查保持单次，其他构建、
  推送或OCI revision错误不得自动重试。

### 14.3 生产两段确认

- `deploy`第一次调用必须不带确认词，只生成并展示服务、仓库、分支、Commit、Digest、
  环境、迁移开关和变更说明。
- 本地确认状态与完整预览指纹绑定，有效期15分钟且只能消费一次；参数变化、状态缺失、
  状态损坏、过期或直接携带确认词时均不得触发Workflow。
- iwork确认词必须绑定完整Commit；确认只是防误操作门禁，不能替代Workflow actor、分支、
  固定脚本哈希及服务器强SHA准入。
