# iwork Dashboard API 接口清单

> 生成日期：2026-05-29
> 版本：v2.0（看板改版后）

---

## 接口概览

| 模块 | 接口数 | 说明 |
|------|--------|------|
| 看板页面 | 2 | 主看板、历史看板 |
| 实时数据 API | 8 | 实时统计、工序、Flow、工单 |
| 看板改版 v2 API | 4 | 月趋势、工序对比、热力图、工位排行 |
| 历史数据 API | 3 | 历史日期查询、可用日期、数据同步 |
| 生产详情 API | 4 | 工序概览、Flow 概览、Flow 明细、工序明细 |
| 生产详情页面 | 3 | HTML 页面 |
| WebSocket | 1 | 实时数据推送 |

---

## 一、看板页面

### 1.1 主看板

```
GET /
```

返回主看板 HTML 页面，包含实时统计、工序分布、Flow 分组等模块。

**响应**：`text/html`

---

### 1.2 历史看板

```
GET /history/
```

返回历史数据查询页面，支持按日期回溯查看过去的生产数据。

**响应**：`text/html`

---

## 二、实时数据 API

### 2.1 实时统计数据

```
GET /api/dashboard/realtime/
```

获取当日实时汇总统计数据（总产量、总人数、工单数等）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `stepno` | string | 否 | 全部 | 按工序号过滤，逗号分隔（如 `?stepno=70,69`） |

**响应示例**：

```json
{
  "total_qty": 12580,
  "total_workers": 342,
  "total_workorders": 156,
  "process_count": 45,
  "flow_count": 12,
  "date": "2026-05-29"
}
```

---

### 2.2 工序列表

```
GET /api/dashboard/processes/
```

获取可用工序号列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `mode` | string | 否 | `remote` | 数据源：`remote`（远程库）或 `local`（本地同步库） |
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "processes": [2, 3, 5, 6, 8, 9, 10, 11, 14],
  "date": "2026-05-29",
  "mode": "remote"
}
```

---

### 2.3 小时统计

```
GET /api/dashboard/hourly/
```

获取当日按小时分布的产量统计数据。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |
| `stepno` | string | 否 | 全部 | 按工序号过滤，逗号分隔 |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "hours": [
    {"hour": 8, "qty": 520, "workers": 45},
    {"hour": 9, "qty": 680, "workers": 52}
  ]
}
```

---

### 2.4 Flow 统计数据

```
GET /api/dashboard/flow/<flow_name>/
```

获取指定 Flow 分组的统计数据。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `flow_name` | string | Flow 名称（如 `SO10-L10A`） |

**响应示例**：

```json
{
  "flow_name": "SO10-L10A",
  "total_qty": 2340,
  "total_workers": 56,
  "stations": [
    {"station_id": "A01", "qty": 120, "workers": 3}
  ]
}
```

---

### 2.5 工单列表

```
GET /api/dashboard/workorders/
```

获取工单列表（支持分页）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `mode` | string | 否 | `remote` | 数据源：`remote` 或 `local` |
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "count": 156,
  "results": [
    {"wrk_order": "WO20260529001", "qty": 500, "step_count": 8}
  ]
}
```

---

### 2.6 工单详情

```
GET /api/dashboard/workorders/<wrk_order>/
```

获取指定工单的详细生产信息。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `wrk_order` | string | 工单号（14 位，如 `WO20260529001`） |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "wrk_order": "WO20260529001",
  "total_qty": 500,
  "steps": [
    {"stepno": 2, "qty": 100, "completed": true},
    {"stepno": 5, "qty": 200, "completed": false}
  ]
}
```

---

## 三、看板改版 v2 API

### 3.1 月趋势（主题 3c）

```
GET /api/dashboard/monthly-trend/
```

获取当月每日总产量趋势数据。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "month": "2026-05",
  "trend": [
    {"day": 1, "qty": 12500},
    {"day": 2, "qty": 13200}
  ]
}
```

---

### 3.2 工序对比（主题 3a）

```
GET /api/dashboard/process-compare/
```

获取工序 × Flow 矩阵产量对比数据。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "steps": [2, 3, 5, 6, 8, 9, 10, 11, 14],
  "flows": ["SO10-L10A", "SO10-L10B"],
  "matrix": [
    {"stepno": 2, "flow": "SO10-L10A", "qty": 340},
    {"stepno": 2, "flow": "SO10-L10B", "qty": 280}
  ]
}
```

---

### 3.3 热力图（主题 5）

```
GET /api/dashboard/heatmap/
```

获取工位负荷热力图数据（工序 × Flow 矩阵 + 红绿双向渐变）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |
| `stepno` | string | 否 | 全部 | 按工序号过滤，逗号分隔 |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "heatmap": [
    {"stepno": 2, "flow": "SO10-L10A", "load": 0.82, "qty": 340},
    {"stepno": 2, "flow": "SO10-L10B", "load": 0.45, "qty": 280}
  ]
}
```

---

### 3.4 工位排行（主题 6）

```
GET /api/dashboard/station-ranking/
```

获取工站产量排名数据。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |
| `limit` | int | 否 | `15` | 返回前 N 条排行 |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "ranking": [
    {"rank": 1, "station_id": "A01", "qty": 1520, "workers": 12},
    {"rank": 2, "station_id": "B03", "qty": 1380, "workers": 10}
  ]
}
```

---

## 四、历史数据 API

### 4.1 历史日期统计

```
GET /api/history/date/<target_date>/
```

获取指定日期的全量统计数据（字段与实时视图一致）。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `target_date` | string | 目标日期，格式 `YYYY-MM-DD` |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `mode` | string | 否 | `local` | 数据源：`local` 或 `remote` |
| `stepno` | string | 否 | 全部 | 按工序号过滤，逗号分隔 |

---

### 4.2 可用日期列表

```
GET /api/history/dates/
```

获取本地有同步数据的可用日期列表。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `mode` | string | 否 | `local` | 数据源 |

**响应示例**：

```json
{
  "dates": ["2026-05-01", "2026-05-02", "2026-05-03"],
  "mode": "local"
}
```

---

### 4.3 数据同步

```
POST /api/history/sync/<target_date>/
```

手动触发指定日期的数据从远程库同步到本地库。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `target_date` | string | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "synced_count": 12500,
  "updated_count": 0,
  "skipped_count": 340,
  "elapsed": 2.35
}
```

---

## 五、生产详情 API

### 5.1 工序概览

```
GET /api/dashboard/detail/stepno-overview/
```

获取所有工序的概览汇总数据（从 Redis 缓存一次读取，避免 N+1 查询）。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "steps": [
    {
      "stepno": 2,
      "total_qty": 2340,
      "total_workers": 45,
      "flow_count": 8,
      "status": "normal"
    }
  ]
}
```

---

### 5.2 Flow 概览

```
GET /api/dashboard/detail/flows/
```

获取所有 Flow 分组的概览数据。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "date": "2026-05-29",
  "flows": [
    {
      "flow_name": "SO10-L10A",
      "total_qty": 340,
      "total_workers": 8,
      "step_count": 6
    }
  ]
}
```

---

### 5.3 Flow 员工明细

```
GET /api/dashboard/detail/flow/<flow_name>/
```

获取指定 Flow 分组的员工级别明细数据。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `flow_name` | string | Flow 名称（如 `SO10-L10A`） |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "flow_name": "SO10-L10A",
  "date": "2026-05-29",
  "workers": [
    {"employee_id": 1001, "name": "张三", "qty": 120, "stepno": 5, "station_id": "A01"}
  ]
}
```

---

### 5.4 工序员工明细

```
GET /api/dashboard/detail/stepno/<stepno>/
```

获取指定工序的员工级别明细数据。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `stepno` | int | 工序号（如 `2`, `10`, `70`） |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 否 | 今日 | 目标日期，格式 `YYYY-MM-DD` |

**响应示例**：

```json
{
  "stepno": 2,
  "date": "2026-05-29",
  "total_qty": 2340,
  "workers": [
    {"employee_id": 1001, "name": "张三", "qty": 200, "flow": "SO10-L10A", "station_id": "A01"}
  ]
}
```

---

## 六、生产详情页面

### 6.1 生产详情主页

```
GET /production/detail-data/
```

返回生产详情 HTML 页面，包含工序和 Flow 概览。

---

### 6.2 Flow 详情页

```
GET /production/detail-data/flow/<flow_name>/
```

返回指定 Flow 的详情 HTML 页面。

---

### 6.3 工序详情页

```
GET /production/detail-data/stepno/<stepno>/
```

返回指定工序的详情 HTML 页面。

---

## 七、WebSocket

### 7.1 看板实时推送

```
ws://<host>/ws/dashboard/
```

WebSocket 连接，每 60 秒（由 Celery Beat 触发）主动推送当日统计数据。

**推送消息示例**：

```json
{
  "type": "dashboard_update",
  "timestamp": "2026-05-29T14:30:00",
  "data": {
    "total_qty": 12580,
    "total_workers": 342,
    "total_workorders": 156,
    "date": "2026-05-29"
  }
}
```

---

## 八、通用说明

### 8.1 请求格式

- 所有 API 均为 RESTful 风格
- GET 请求使用查询参数（query string）
- POST 请求使用 JSON 格式（Content-Type: application/json）
- 除 `/api/history/sync/<date>/` 外，所有接口均为 GET

### 8.2 日期格式

所有日期参数和返回值统一使用 **ISO 8601 格式**：`YYYY-MM-DD`

### 8.3 响应格式

所有 API 响应均为 `application/json` 格式（HTML 页面除外）。

### 8.4 错误码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误（如日期格式不正确） |
| 404 | 资源不存在（如无效的 flow_name） |
| 500 | 服务器内部错误 |

### 8.5 数据源模式（mode 参数）

| 值 | 说明 | 适用场景 |
|----|------|---------|
| `remote` | 直连远程业务库（`192.168.3.15`） | 当日实时数据 |
| `local` | 查询本地同步库（`iwork_local`） | 历史日期查询 |

### 8.6 Flow 白名单

当前系统仅处理以下 45 个 Flow 分组：

```
SO2-L2A/B/C/D/E/F/G, SO3-L3A/B/C/D/E/F,
SO5-L5B/C/D/E, SO6-L6A/B/C/D/E/F/G,
SO8-L8A/B/C/D/E/F, SO9-L9A/B/C/D,
SO10-L10A/B/C/D/E/F/G, SO11-L11A/B/D/E,
SO14-L14A/B/C/D
```
