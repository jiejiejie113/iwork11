# 车间工效看板（iwork）— 开发规范手册

> 本手册是项目的活文档，每次修改必须同步更新对应章节。
> 最后更新：2026-07-14

---

## 1. 架构概览

```
Uvicorn ASGI (4 workers)
    ├── 实时数据：Celery Beat (60s) → statistics.py → Redis → SSE 推送 + API 读缓存
    ├── 历史数据：API → statistics.py → queries.py 直查远程库
    ├── 本地历史：API → statistics.py → local_queries.py 查本地库
    └── 生产详情：API → api_views.py → queries/local_queries → Redis 缓存
```

| 文件 | 职责 |
|------|------|
| `queries.py` | 远程数据库查询（iwork 只读） |
| `local_queries.py` | 本地数据库查询（iwork_local 读写），与 queries.py 镜像 |
| `statistics.py` | 缓存编排层：批量构建 + Redis 读写 + 回退逻辑 |
| `api_views.py` | 实时看板 API + 生产详情 API（含异步 SSE） |
| `api_views_local.py` | 历史数据 API + 数据同步 API |
| `tasks.py` | Celery 定时任务 |

### 运行与测试环境

- Docker 使用 `env/local.env` 或 `env/production.env` 保存非敏感配置；
- 真实密钥从两个仓库共同上级目录的 `dkt-secrets.env` 显式注入；
- `DKT_iwork` 的 8000 端口只在 `docker_dkt-net` 内暴露，外部请求必须经过 Nginx 和 oauth2-proxy；
- pytest 固定加载 `iwork.test_settings`，使用内存 SQLite、LocMem 缓存和内存 Celery，不依赖开发数据库或 Redis；
- `Pywrkstp` 使用 `(WrkOrder, StepNo)` 复合主键，禁止查询隐式 `id`。

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
缺少标准工时时汇总值为 `null`。本地历史查询远程元数据失败时保留产量并将元数据
和产值降级为空。

Flow 详情缓存使用 `stats:detail:flow:v2:<flow_name>`。缓存不保存实时效率；接口按
请求时刻注入 `work_minutes` 和 `employee_efficiency`。

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

---

## 7. SSE 异步架构

**服务器**：Uvicorn ASGI，4 workers，每 worker 异步处理数百连接。

**端点**：`/api/dashboard/stream/`（`api_views.py` → `async def dashboard_stream`）

**实现要点**：
- 使用 `StreamingHttpResponse` + 异步生成器
- `sync_to_async` 包装同步 Redis 读取，不阻塞事件循环
- 心跳：每 15 秒发送 SSE 注释（`: heartbeat\n\n`）
- 数据推送：每 60 秒从 Redis 读缓存推送

**性能**：每个连接仅占一个 asyncio 协程（~KB 级），支持 300+ 并发。

---

## 8. 工单列表数据流规范

**原则**：不显示中间数据。缓存为空时显示"暂无数据"，数据到达后显示正确数据。

**`workorderItems` 计算属性**：
```javascript
const workorderItems = computed(() => {
    return workorderCache[workorderPage.value] || [];
});
```

**禁止** fallback 到 `data.workorders`（该字段来自 SSR 预填充，可能与分页 API 数据不一致）。

**数据更新流程**：
1. fetch 新数据 → 写入 `workorderCache` → 更新分页状态
2. 然后才清除旧缓存条目
3. 不允许先清缓存再异步获取（会产生空档期）

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
| `employees[].output_value` | `emp.output_value` | 员工总产值 |
| `employees[].employee_efficiency` | `emp.employee_efficiency` | 员工效率 |

### 8.3 修改规则

1. **后端新增字段** → 前端 `Object.assign` / `map` 中同步添加
2. **后端删除字段** → 前端引用处同步删除，否则显示 `undefined`
3. **后端重命名字段** → 前端所有引用处同步修改

---

## 9. 修改检查清单

每次修改后，按以下清单检查：

- [ ] **配置变更**：`settings.py` → 更新本手册第 2 节
- [ ] **字段变更**：API 返回字段 → 更新本手册第 4/8 节 + 前端模板
- [ ] **查询变更**：`queries.py` → 同步修改 `local_queries.py`（镜像）
- [ ] **图表变更**：字体/颜色/数据源 → 更新本手册第 6 节
- [ ] **时区变更**：修改 `toLocaleTimeString` → 更新本手册第 5 节
- [ ] **隐藏分组**：修改 `HIDDEN_FLOWS` → 更新本手册第 3 节
- [ ] **重建容器**：`docker compose up -d --build`

---

## 10. 产量看板模块

> 新增于 2026-06-16

### 10.1 架构

| 文件 | 变更 |
|------|------|
| `iwork/queries.py` | 新增 `get_kanban_stats`、`get_kanban_ranking`、`get_kanban_filter_options`、`_apply_kanban_filters`、`_merge_worker_rows` |
| `iwork/local_queries.py` | 镜像新增 5 个函数 |
| `iwork/api_views.py` | 新增 `kanban_stats`、`kanban_ranking`、`kanban_filter_options`、`_parse_kanban_date` |
| `iwork/urls.py` | 新增 4 条路由（页面 + 3 API） |
| `iwork/views.py` | 新增 `kanban_page` |
| `iwork/templates/iwork/kanban.html` | 产量看板页面（Vue 3 + Tailwind CDN） |
| `iwork/templates/iwork/_header.html` | 添加"产量看板"标签 |
| `iwork/settings.py` | 新增 `KANBAN_DEFAULT_STEPNO='70'`、`KANBAN_DEFAULT_PAGE_SIZE=50` |

### 10.2 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kanban/` | 页面 |
| GET | `/api/kanban/stats/` | 统计汇总（worker_count, total_production, avg_production, max_production, max_worker_name） |
| GET | `/api/kanban/ranking/` | 排行榜分页列表（50条/页） |
| GET | `/api/kanban/filter-options/` | 筛选项（stepnos, wrk_orders, flows, employees） |

### 10.3 默认配置

```python
KANBAN_DEFAULT_STEPNO = '70'    # 默认工序
KANBAN_DEFAULT_PAGE_SIZE = 50   # 每页条数
```

### 10.4 筛选器

- **工序**：单选，默认 `'70'`
- **款号**：单选，默认全部（空字符串）
- **分组（Flow）**：多选下拉，默认全选（空数组）
- **员工**：单选，默认全部（空字符串），Flow 变化时级联更新
- **清空按钮**：恢复默认值（stepno='70'，其余全部）
- **日期**：日期选择器，默认当天

### 10.5 前端技术栈

- Vue 3 CDN（分隔符 `{[` `]}`）
- Tailwind CSS CDN（darkMode: 'class'）
- 统计卡片数字滚动动画
- 表格行滑入动画（rowIn）
- 柱状图升起动画（barIn）
- 排名 1/2/3 金银铜徽章
