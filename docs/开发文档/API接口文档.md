# iWork 项目 API 接口文档

> 最后更新：2026-07-16

## 一、架构概览

```
浏览器
  ├── GET /                              → HTML 页面（实时看板 + SSE 推送）
  ├── GET /history/                      → HTML 页面（历史看板）
  ├── GET /production/detail-data/       → HTML 页面（生产详情模块）
  ├── GET /api/dashboard/*               → 实时数据 API（来源：api_views.py）
  ├── GET /api/history/*                 → 历史数据 API（来源：api_views_local.py）
  ├── POST /api/history/snapshots/*/ensure/ → 缺失快照按需构建
  ├── GET /api/dashboard/stream/         → SSE 实时推送
  └── POST /api/dashboard/set-targets/   → 目标产量设置

Celery Beat (每 60s)
  ├── get_batch_stats()           → 工序聚合数据 → Redis 缓存
  ├── get_batch_detail_stats()    → Flow/StepNo 员工明细 → Redis 缓存
  └── SSE 端点从 Redis 读取 → 推送 dashboard_update → 浏览器
```

**数据源路由：**

| 日期 | 参数 | 查询模块 | 数据库 |
| --- | --- | --- | --- |
| 今日 | 无 | `iwork.queries` / Redis | 远程 `iwork`（只读） |
| 历史 | `?date=YYYY-MM-DD` | `iwork.historical_queries` / `local_queries` | 本地 `iwork_local`（只读快照） |

**共享工具函数 `_parse_stepno(request)`：**
将 `?stepno=70,69` 解析为 `[70, 69]`，空参数返回 `None`（全工序）。

---

## 二、页面视图（返回 HTML）

### `GET /`

- **文件：** `iwork/views.py` → `dashboard()`
- **说明：** 实时看板主页。渲染 `dashboard.html`，预填 Redis 缓存的实时统计数据，启用 SSE 实时推送。
- **参数：** 无

### `GET /history/`

- **文件：** `iwork/views.py` → `history_dashboard()`
- **说明：** 历史数据看板。同一模板，`initial_view='history'`，初始数据归零，不建立 SSE 连接。
- **参数：** 无

### `GET /production/detail-data/`

- **文件：** `iwork/views.py` → `production_detail()`
- **说明：** 生产详情 — Flow 概览页。渲染 `production_detail.html`，卡片网格展示各 Flow 汇总。
- **参数：** 无

### `GET /production/detail-data/flow/<flow_name>/`

- **文件：** `iwork/views.py` → `production_detail_flow(request, flow_name)`
- **说明：** 生产详情 — Flow 员工明细。渲染 `production_detail.html`，`initial_view='detail'`。
- **参数：** `flow_name`（路径参数）

### `GET /production/detail-data/stepno/<stepno>/`

- **文件：** `iwork/views.py` → `production_detail_stepno(request, stepno)`
- **说明：** 生产详情 — 工序员工明细。渲染 `production_detail.html`，`initial_view='detail'`。
- **参数：** `stepno`（路径参数，整数）

---

## 三、实时数据 API（`/api/dashboard/`）

> 来源：`iwork/api_views.py`，注册于 `iwork/urls.py`

### `GET /api/dashboard/realtime/`

获取实时看板全量统计数据（从 Redis 缓存读取，<1ms 响应）。

| 参数       | 类型   | 必填 | 说明                                                |
| ---------- | ------ | ---- | --------------------------------------------------- |
| `stepno` | string | 否   | 逗号分隔工序号，如 `?stepno=70,69`。无参数=全工序 |

返回字段：`total_qty`, `workorder_count`, `date`, `hourly_stats`, `process_flow_stats`, `monthly_process_stats`, `monthly_total_trend`, `station_stats`, `heatmap_matrix`, `station_ranking`, `top_processes`, `workorders`, `all_stepnos`

---

### `GET /api/dashboard/hourly/`

获取按小时产量统计。

| 参数       | 类型   | 必填 | 说明                       |
| ---------- | ------ | ---- | -------------------------- |
| `date`   | string | 否   | 日期（ISO 格式），默认今天 |
| `stepno` | string | 否   | 工序过滤                   |

缓存：Redis key `dashboard:hourly:<date>:<filter>`，TTL 24h。

---

### `GET /api/dashboard/flow/<flow_name>/`

获取指定 Flow 组统计。

| 参数          | 类型 | 必填 | 说明                   |
| ------------- | ---- | ---- | ---------------------- |
| `flow_name` | path | 是   | Flow 组名称，如 `A1` |

---

### `GET /api/dashboard/workorders/`

获取工单列表（分页）。

| 参数          | 类型   | 必填 | 默认值 | 说明     |
| ------------- | ------ | ---- | ------ | -------- |
| `page`      | int    | 否   | 1      | 页码     |
| `page_size` | int    | 否   | 20     | 每页条数 |
| `stepno`    | string | 否   | -      | 工序过滤 |

返回：`{ "items": [...], "total": N, "page": 1, "page_size": 20, "total_pages": N }`

---

### `GET /api/dashboard/workorders/<wrk_order>/`

获取指定工单详情（含各工序明细）。

| 参数          | 类型   | 必填 | 说明           |
| ------------- | ------ | ---- | -------------- |
| `wrk_order` | path   | 是   | 工单号         |
| `date`      | string | 否   | 日期，默认今天 |

返回：`{ "wrk_order": "...", "total_qty": N, "steps": [...] }`

---

### `GET /api/dashboard/monthly-trend/`

获取当月每日总产量趋势（主题 3c）。

| 参数       | 类型   | 必填 | 说明                                        |
| ---------- | ------ | ---- | ------------------------------------------- |
| `date`   | string | 否   | 参考日期，默认今天。取该日期所在月 1 日至今 |
| `stepno` | string | 否   | 工序过滤                                    |

---

### `GET /api/dashboard/process-compare/`

工序 × Flow 分组产量对比（主题 3a）。

| 参数        | 类型   | 必填 | 说明                               |
| ----------- | ------ | ---- | ---------------------------------- |
| `date`    | string | 否   | 日期，默认今天                     |
| `stepnos` | string | 否   | 要对比的工序号。不传则取当天 Top 8 |

---

### `GET /api/dashboard/heatmap/`

工位负荷热力图（主题 5）。

| 参数       | 类型   | 必填 | 说明           |
| ---------- | ------ | ---- | -------------- |
| `date`   | string | 否   | 日期，默认今天 |
| `stepno` | string | 否   | 工序过滤       |

返回：`{ "hours": [8,9,10,...], "flows": ["A1","A2",...], "data": [[qty,...], ...] }`

---

### `GET /api/dashboard/station-ranking/`

工站产量排行（主题 6）。

| 参数       | 类型   | 必填 | 默认值 | 说明     |
| ---------- | ------ | ---- | ------ | -------- |
| `date`   | string | 否   | 今天   | 日期     |
| `limit`  | int    | 否   | 15     | 返回条数 |
| `stepno` | string | 否   | -      | 工序过滤 |

---

## 四、历史数据 API（`/api/history/`）

> 来源：`iwork/api_views_local.py`，注册于 `iwork/history_urls.py`

### `GET /api/history/date/<target_date>/`

获取指定日期的全量统计数据（字段与实时接口完全一致）。

| 参数            | 类型   | 必填 | 默认值    | 说明                                |
| --------------- | ------ | ---- | --------- | ----------------------------------- |
| `target_date` | path   | 是   | -         | 日期，ISO 格式                      |
| `mode`        | string | 否   | `local` | `local`=本地库，`remote`=远程库 |
| `stepno`      | string | 否   | -         | 工序过滤                            |

返回字段（14 个）：`date`, `source`, `total_qty`, `workorder_count`, `hourly_stats`, `station_stats`, `workorders`, `process_flow_stats`, `monthly_process_stats`, `monthly_total_trend`, `heatmap_matrix`, `station_ranking`, `process_stats`/`top_processes`, `all_stepnos`

缓存：本地 1h / 远程 30min，同步后自动失效。

---

### `GET /api/history/dates/`

获取有数据的可用日期列表（前端日期选择器使用）。

| 参数     | 类型   | 必填 | 默认值    | 说明   |
| -------- | ------ | ---- | --------- | ------ |
| `mode` | string | 否   | `local` | 数据源 |

返回：`{ "mode": "local", "dates": ["2026-05-12", "2026-05-11", ...] }`

---

### `GET /api/history/processes/`

获取指定日期所有可用工序号（前端下拉菜单使用，轻量接口）。

| 参数     | 类型   | 必填 | 默认值    | 说明           |
| -------- | ------ | ---- | --------- | -------------- |
| `mode` | string | 否   | `local` | 数据源         |
| `date` | string | 否   | 今天      | 日期，ISO 格式 |

返回：`{ "date": "2026-05-12", "mode": "local", "stepnos": [70, 69, 68, ...] }`

---

### `POST /api/history/snapshots/<target_date>/ensure/`

确保指定已结束日期存在本地历史快照；已有成功快照时直接返回，缺失时从远程只读源
聚合并原子发布。前端自动调用，不提供手动同步按钮。

| 参数            | 类型 | 必填 | 说明                   |
| --------------- | ---- | ---- | ---------------------- |
| `target_date` | path | 是   | 要确保快照的日期，ISO 格式 |

返回：`{ "created": true, "snapshot": { "date": "...", "version": 1 } }`

---

## 五、生产详情 API（`/api/dashboard/detail/`）

> 来源：`iwork/api_views.py`，注册于 `iwork/urls.py`

今日视图优先读取 Redis。早于缅甸业务日期的请求默认读取 `iwork_local` 中已经发布的
历史快照，不访问远程生产库，也不支持 `mode` 切换。

### `GET /api/dashboard/detail/flows/`

获取 Flow 概览卡片数据（所有 Flow 的汇总统计）。

| 参数     | 类型   | 必填 | 默认值    | 说明                      |
| -------- | ------ | ---- | --------- | ------------------------- |
| `date` | string | 否   | 今天      | 日期，ISO 格式            |

返回：`{ "VCO-L5": { "total_qty": 800, "worker_count": 15 }, ... }`

缓存：今日 `stats:detail:flow_overview`（TTL 到午夜）；历史直接查询本地聚合事实表。

---

### `GET /api/dashboard/detail/flow/<flow_name>/`

获取指定 Flow 的员工明细 + 小时趋势。

| 参数          | 类型   | 必填 | 默认值    | 说明           |
| ------------- | ------ | ---- | --------- | -------------- |
| `flow_name` | path   | 是   | -         | Flow 名称      |
| `date`      | string | 否   | 今天      | 日期，ISO 格式 |
| `mode`      | string | 否   | 自动       | 今日远程/Redis，历史本地快照 |

响应顶层包含当前有效上班分钟，员工节点包含总产值与员工效率，工序节点按
`(workorder, stepno)` 返回元数据：

```json
{
  "flow": "SO3-L3A",
  "date": "2026-07-15",
  "total_qty": 516,
  "worker_count": 1,
  "source": "local_snapshot",
  "snapshot_date": "2026-07-15",
  "work_minutes": 210,
  "hourly_trend": [],
  "employees": [{
    "reg_per_sys_id": 2122,
    "total_qty": 516,
    "output_value": 420.0,
    "employee_efficiency": 200.0,
    "steps": [{
      "workorder": "BU0724",
      "stepno": 15,
      "description": "走定领底边线",
      "step_time": 0.266,
      "qty": 172,
      "output_value": 45.752
    }]
  }]
}
```

员工效率为 `output_value / work_minutes * 100`。`work_minutes` 使用 UTC+6:30：
07:30 起算，扣除午休 11:30-12:00 与晚休 16:00-16:30，18:30 收工后封顶 600 分钟。
历史日期、尚未上班、工时缺失或分钟数为 0 时效率返回 `null`。

缓存：今日 `stats:detail:flow:v2:<name>`（TTL 到午夜）。缓存产值快照；上班分钟和
员工效率在请求时计算。

---

### `GET /api/dashboard/detail/stepno/<stepno>/`

获取指定工序的员工明细。

| 参数       | 类型   | 必填 | 默认值    | 说明           |
| ---------- | ------ | ---- | --------- | -------------- |
| `stepno` | path   | 是   | -         | 工序号（整数） |
| `date`   | string | 否   | 今天      | 日期，ISO 格式 |
| `mode`   | string | 否   | `remote` | 数据源         |

返回：`{ "stepno": ..., "date": "...", "total_qty": N, "worker_count": N, "employees": [{ "reg_per_sys_id": ..., "qty": ..., "flows": [...] }] }`

---

## 六、SSE 实时推送（`/api/dashboard/stream/`）

- **视图：** `iwork/api_views.py` → `dashboard_stream`
- **协议：** Server-Sent Events（SSE，text/event-stream）
- **数据源：** 从 Redis 缓存读取 Celery 预计算结果
- **推送间隔：** 每 60 秒推送一次

**服务端 → 客户端（推送事件）：**

| 事件类型 | 说明 |
| -------- | ---- |
| `dashboard_update` | 实时数据更新（Celery 写 Redis → SSE 读推送） |
| `targets_updated` | 目标产量已保存（广播确认） |

**客户端：** 前端使用 `EventSource` 连接 `/api/dashboard/stream/`，收到 `dashboard_update` 后更新页面数据。

---

## 七、Celery 定时任务

- **任务：** `iwork/tasks.py` → `sync_dashboard_stats`
- **调度：** 每 60 秒（`iwork/celery.py` 配置）
- **流程：**
  1. `get_batch_stats()` 一次性计算所有工序的 6 个维度统计数据
  2. `get_batch_detail_stats()` 并行计算 Flow/StepNo 员工明细
  3. `cache_batch_to_redis()` + `cache_detail_batch_to_redis()` 写入 Redis，TTL 到午夜
  4. SSE 端点从 Redis 读取，推送给所有在线客户端
- **重试：** 最多 3 次，间隔 10 秒

---

## 八、接口速查表

| # | 方法 | URL | 视图函数 | 所属文件 | 关键参数 |
| -- | ---- | --- | -------- | -------- | -------- |
| 1 | GET | `/` | `dashboard` | `views.py` | - |
| 2 | GET | `/history/` | `history_dashboard` | `views.py` | - |
| 3 | GET | `/api/dashboard/realtime/` | `realtime_stats` | `api_views.py` | `stepno` |
| 4 | GET | `/api/dashboard/hourly/` | `hourly_stats` | `api_views.py` | `date`, `stepno` |
| 5 | GET | `/api/dashboard/processes/` | `process_list` | `api_views.py` | - |
| 6 | GET | `/api/dashboard/flow/<name>/` | `flow_stats` | `api_views.py` | - |
| 7 | GET | `/api/dashboard/workorders/` | `workorder_list` | `api_views.py` | `page`, `page_size`, `stepno` |
| 8 | GET | `/api/dashboard/workorders/<wo>/` | `workorder_detail` | `api_views.py` | `date` |
| 9 | GET | `/api/dashboard/monthly-trend/` | `monthly_trend` | `api_views.py` | `date`, `stepno` |
| 10 | GET | `/api/dashboard/process-compare/` | `process_compare` | `api_views.py` | `date`, `stepnos` |
| 11 | GET | `/api/dashboard/heatmap/` | `heatmap` | `api_views.py` | `date`, `stepno` |
| 12 | GET | `/api/dashboard/station-ranking/` | `station_ranking` | `api_views.py` | `date`, `limit`, `stepno` |
| 13 | GET | `/api/dashboard/stream/` | `dashboard_stream` | `api_views.py` | SSE 实时推送 |
| 14 | POST | `/api/dashboard/set-targets/` | `set_targets` | `api_views.py` | `targets` JSON body |
| 15 | GET | `/api/history/date/<date>/` | `local_date_stats` | `api_views_local.py` | `stepno` |
| 16 | GET | `/api/history/dates/` | `available_dates` | `api_views_local.py` | - |
| 17 | POST | `/api/history/snapshots/<date>/ensure/` | `ensure_snapshot` | `api_views_local.py` | - |
| 19 | GET | `/production/detail-data/` | `production_detail` | `views.py` | - |
| 20 | GET | `/production/detail-data/flow/<name>/` | `production_detail_flow` | `views.py` | - |
| 21 | GET | `/production/detail-data/stepno/<n>/` | `production_detail_stepno` | `views.py` | - |
| 22 | GET | `/api/dashboard/detail/stepno-overview/` | `stepno_overview` | `api_views.py` | `date` |
| 23 | GET | `/api/dashboard/detail/flows/` | `flow_overview` | `api_views.py` | `date` |
| 24 | GET | `/api/dashboard/detail/flow/<name>/` | `flow_detail` | `api_views.py` | `date` |
| 25 | GET | `/api/dashboard/detail/stepno/<n>/` | `stepno_detail` | `api_views.py` | `date` |

---

## 九、已废弃的路由

`iwork/api_urls.py` 定义了旧版路由前缀（`stats/realtime/` 等），**未被任何 `urls.py` 引用**，已废弃。所有实时 API 已迁移至 `api/dashboard/` 前缀。
