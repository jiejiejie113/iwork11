# 生产详情数据模块 — 技术设计

> 日期：2026-05-14 | 状态：已确认

## 一、模块定位

"生产详情"模块是"实时数据"的深化拓展，展示当日生产数据的员工明细层级（按 Flow/StepNo 分组钻取），而非仅展示聚合后的实时状态。

---

## 二、数据获取策略（扩展 Batch 引擎）

- **今日数据**：Celery 每 60s 批量预计算全部 Flow/StepNo 明细 → 写入 Redis → API 纯读缓存（<1ms）
- **历史数据**：API → Redis 缓存（远程 30min / 本地 1h）→ 未命中 → 查询对应库
- **扩展 Celery batch 引擎**：在现有 `sync_dashboard_stats` 任务中新增明细维度的批量查询，与现有工序聚合数据一并写入 Redis

---

## 三、后端变更

### 3.1 查询层 — Batch 批量查询函数（queries.py + local_queries.py）

新增 4 个 Batch 风格查询函数（一次查询覆盖全部分组维度），对齐现有 `get_batch_basic_stats` 等模式：

| Batch 函数                                  | 返回                                                                   |
| ------------------------------------------- | ---------------------------------------------------------------------- |
| `get_batch_flow_overview(target_date)`    | `{flow_name: {worker_count, total_qty}}`                             |
| `get_batch_flow_hourly(target_date)`      | `{flow_name: [{hour, qty}]}`                                         |
| `get_batch_flow_employees(target_date)`   | `{flow_name: [{reg_per_sys_id, total_qty, steps: [{stepno, qty}]}]}` |
| `get_batch_stepno_employees(target_date)` | `{stepno: [{reg_per_sys_id, qty, flows: ["VCO-L5",...]}]}`           |

SQL 实现示例（`get_batch_flow_employees`）：

```sql
SELECT Flow, RegPerSysID, StepNo, SUM(Qty)
FROM pytckreg3 WHERE RegDate = today
GROUP BY Flow, RegPerSysID, StepNo
ORDER BY Flow, RegPerSysID
```

→ Python 层二次分组为 `{flow_name: [{reg_per_sys_id, total_qty, steps: [...]}]}`

另新增 1 个轻量工具函数：

| 函数                           | 返回                                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------- |
| `get_all_flows(target_date)` | `["VCO-L5", "VCO-C1", ...]` — 复用 `get_records_queryset` + `values('Flow').distinct()` |

### 3.2 统计引擎扩展（statistics.py）

新增函数 `get_batch_detail_stats(q=None)` 并行构建详情数据：

```
get_batch_detail_stats():
  ThreadPoolExecutor(max_workers=3)
    ├── get_batch_flow_overview()   → {flow: {worker_count, total_qty}}
    ├── get_batch_flow_hourly()     → {flow: [{hour, qty}]}
    └── get_batch_flow_employees()  → {flow: [{reg_per_sys_id, ...}]}
  → 组装为统一结构 → 返回 dict
```

在 `cache_batch_to_redis()` 中新增详情缓存写入：

```python
# 写入 Flow 概览 + 每个 Flow 的员工明细
cache.set('stats:detail:flow_overview', detail['flow_overview'], ttl)
for flow_name, employees in detail['flow_employees'].items():
    cache.set(f'stats:detail:flow:{flow_name}', employees, ttl)
```

在 `sync_dashboard_stats` Celery 任务中追加调用：

```python
detail_batch = get_batch_detail_stats()
cache_detail_batch_to_redis(detail_batch)
```

### 3.3 API 端点（api_views.py）

今日视图**纯读 Redis**（对齐 `get_realtime_stats` 模式），历史视图**查库+缓存**（对齐 `get_date_stats` 模式）：

| 方法 | URL                                        | 视图函数          | 今日数据流                           | 历史数据流         |
| ---- | ------------------------------------------ | ----------------- | ------------------------------------ | ------------------ |
| GET  | `/api/dashboard/detail/flows/`           | `flow_overview` | Redis `stats:detail:flow_overview` | 查库 → 缓存 30min |
| GET  | `/api/dashboard/detail/flow/<name>/`     | `flow_detail`   | Redis `stats:detail:flow:<name>`   | 查库 → 缓存 30min |
| GET  | `/api/dashboard/detail/stepno/<stepno>/` | `stepno_detail` | 使用 batch_stepno_employees 的缓存   | 查库 → 缓存 30min |

参数：`?date=2026-05-14`（默认今日）、`?mode=local`（历史视图使用本地库）

### 3.4 缓存键规范

| 场景                   | 键格式                                         | TTL          |
| ---------------------- | ---------------------------------------------- | ------------ |
| 今日 Flow 概览         | `stats:detail:flow_overview`                 | 到今晚 24:00 |
| 今日 Flow 小时趋势     | `stats:detail:flow_hourly`                   | 到今晚 24:00 |
| 今日 Flow 员工明细     | `stats:detail:flow:<name>`                   | 到今晚 24:00 |
| 今日 StepNo 员工明细   | `stats:detail:stepno:<stepno>`               | 到今晚 24:00 |
| 历史 Flow 详情（远程） | `stats:detail:date:<date>:flow:<name>`       | 1800s        |
| 历史 Flow 详情（本地） | `stats:detail:local:date:<date>:flow:<name>` | 3600s        |

### 3.5 页面视图（views.py）

| 函数                                           | 模板                       | 初始状态                                                              |
| ---------------------------------------------- | -------------------------- | --------------------------------------------------------------------- |
| `production_detail(request)`                 | `production_detail.html` | `initial_view='overview'`                                           |
| `production_detail_flow(request, flow_name)` | `production_detail.html` | `initial_view='detail', detail_type='flow', detail_key=<flow_name>` |
| `production_detail_stepno(request, stepno)`  | `production_detail.html` | `initial_view='detail', detail_type='stepno', detail_key=<stepno>`  |

### 3.6 URL 路由（urls.py）

```python
path("production/detail-data/", views.production_detail, name="production-detail"),
path("production/detail-data/flow/<str:flow_name>/", views.production_detail_flow, name="production-detail-flow"),
path("production/detail-data/stepno/<int:stepno>/", views.production_detail_stepno, name="production-detail-stepno"),
```

### 3.7 导航栏（dashboard.html 修改）

在现有"历史数据"右侧新增"生产详情"链接：

```html
<a href="/production/detail-data/"
   class="px-4 py-2 rounded-md text-sm transition-colors font-medium bg-slate-700 hover:bg-slate-600">
   生产详情
</a>
```

---

## 四、前端设计（production_detail.html）

### 4.1 技术栈

Vue 3（CDN）+ Chart.js 4（CDN）+ Tailwind CSS（CDN），与 `dashboard.html` 完全一致。

### 4.2 页面状态

通过 Django 注入 `data-initial-view` 区分：

| URL                                      | initial_view | 其他 data-*                                   |
| ---------------------------------------- | ------------ | --------------------------------------------- |
| `/production/detail-data/`             | `overview` | —                                            |
| `/production/detail-data/flow/<name>/` | `detail`   | `detail_type='flow'`, `detail_key=<name>` |

### 4.3 概览页

- **顶部工具栏**：搜索框（按 RegPerSysID）+ 日期选择器 + Flow/工序 Tab 切换
- **Tab 切换**：`groupMode: 'flow' | 'stepno'`
- **Flow 卡片网格**（3 列响应式）：
  - 卡片顶部：Flow 名称 + 员工数 + 总产量
  - 迷你柱状图：今日小时产量趋势（Chart.js bar chart）
  - 无权限卡片：灰色不可点击 + 锁图标
- **点击卡片** → `window.location.href = '/production/detail-data/flow/' + name`
- **工序视图**：对称结构，点击进入 `/production/detail-data/stepno/<stepno>/`

### 4.4 详情页

- **面包屑导航**：生产详情 > Flow名称
- **汇总信息**：员工数、总产量、日期
- **搜索框**：员工内搜索过滤
- **员工表格**（按总产量降序）：
  | RegPerSysID | 当日总产量 | 当前工序 | 工序明细 |
- **返回按钮** → `window.location.href = '/production/detail-data/'`
- **浏览器前进后退**：Django 独立 URL 路由天然支持

### 4.5 图表管理

Chart.js 实例生命周期管理与 `dashboard.html` 一致（`charts` 对象 + `initChart`/`destroyAllCharts` 模式）。

---

## 五、目标产量功能

### 5.1 数据流

```
用户输入员工目标产量 → 点击保存
  → WebSocket 发送: {type: "set_targets", flow: "L01", targets: {1001: 100, 1002: 150, ...}}
  → Consumer 接收 → 写入 Redis → 广播确认给所有在线客户端
  → 前端重新计算：效率 = 实时产量 / 目标 * 100%
```

### 5.2 Redis 存储

```
targets:{date}:{flow_name} → {reg_per_sys_id: target_qty, ...}  (JSON hash)
```

TTL 到当晚 24:00（与实时缓存同步过期）。每个 Flow 一条记录，存储该 Flow 下所有员工的目标值。

### 5.3 WebSocket 协议扩展（consumers.py）

**客户端 → 服务端：**

```json
{
  "type": "set_targets",
  "flow": "L01",
  "targets": {"1001": 100, "1002": 150}
}
```

**服务端处理：**

1. 接收消息，解析 `type`
2. 写入 Redis：`SET targets:{today}:{flow} = JSON.dumps(targets)`，TTL 到午夜
3. 广播确认：`group_send('dashboard', {type: 'targets_updated', flow: 'L01', targets: {...}})`

**服务端 → 客户端（广播）：**

```json
{
  "type": "targets_updated",
  "flow": "L01",
  "targets": {"1001": 100, "1002": 150}
}
```

### 5.4 前端计算逻辑

| 字段        | 公式                                             |
| ----------- | ------------------------------------------------ |
| 员工效率    | `employee_actual_qty / employee_target * 100%` |
| 员工达标    | `employee_actual >= employee_target` → "达标" |
| Flow 总目标 | `SUM(该 Flow 下所有员工目标)`                  |
| Flow 效率   | `Flow_actual_qty / Flow_total_target * 100%`   |
| Flow 达标   | `Flow_actual >= Flow_total_target` → "达标"   |

当员工未设置目标（Redis 中无对应键）时，效率和达标显示为 `--`。

### 5.5 前端 UI 改动

**概览卡片（新增 2 列）：**

在原卡片汇总信息行下方增加目标产量输入区：

| Flow | 实时产量 | 人数 | 目标产量      | 达标情况 | 效率 |
| ---- | -------- | ---- | ------------- | -------- | ---- |
| L01  | 1250     | 10   | [1000] [保存] | 达标 ✓  | 125% |

点击卡片进入详情后，可逐个员工设置目标。

**Flow 详情表格（新增 3 列）：**

| RegPerSysID | 工序 | 实时产量 | 目标产量 | 达标情况  | 效率 |
| ----------- | ---- | -------- | -------- | --------- | ---- |
| A1001       | 70   | 90       | [100]    | 不达标 ✗ | 90%  |

每行目标产量为可编辑输入框，底部提供"全部保存"按钮，批量提交当前 Flow 所有员工目标。

**工序视图卡片（新增 3 列）：**

| 工序 | 实时产量 | 目标产量 | 达标情况 | 效率 |
| ---- | -------- | -------- | -------- | ---- |
| 70   | 1250     | 1000     | 达标 ✓  | 125% |

目标产量 = 该工序下所有 Flow 中员工目标之和。

### 5.6 文件变更（追加）

| 文件                                             | 操作     | 说明                                            |
| ------------------------------------------------ | -------- | ----------------------------------------------- |
| `iwork/consumers.py`                           | 修改     | 新增 `receive_json` 处理 `set_targets` 消息 |
| `iwork/templates/iwork/production_detail.html` | 修改     | 概览卡片 + 详情表格新增目标列和保存按钮         |
| `tests/test_consumers.py`                      | 新增用例 | `set_targets` 消息处理测试                    |

---

## 六、排序规则

- Flow 卡片：按 Flow 名称字母顺序升序
- StepNo 卡片：按 StepNo 数字降序
- 员工表格：按当日总产量 `SUM(qty)` 降序

---

## 七、权限控制

**暂不实现**，所有 Flow 对所有人可见。设计中预留权限钩子（无权限卡片的 UI 样式已准备），后续可通过 Django 权限系统扩展。

---

## 八、文件变更清单

| 文件                                             | 操作             | 说明                                                                |
| ------------------------------------------------ | ---------------- | ------------------------------------------------------------------- |
| `iwork/queries.py`                             | 新增函数         | 5 个远程 Batch 查询函数                                             |
| `iwork/local_queries.py`                       | 新增函数         | 5 个本地 Batch 查询函数                                             |
| `iwork/statistics.py`                          | 新增函数         | get_batch_detail_stats + cache_detail_batch_to_redis                |
| `iwork/tasks.py`                               | 修改             | sync_dashboard_stats 追加详情批量构建                               |
| `iwork/api_views.py`                           | 新增 3 个视图    | flow_overview, flow_detail, stepno_detail                           |
| `iwork/views.py`                               | 新增 3 个视图    | production_detail, production_detail_flow, production_detail_stepno |
| `iwork/urls.py`                                | 新增 3 条路由    | 页面路由                                                            |
| `iwork/templates/iwork/production_detail.html` | **新文件** | 独立模板                                                            |
| `iwork/templates/iwork/dashboard.html`         | 修改导航栏       | 新增"生产详情"菜单项                                                |
| `docs/开发文档/API接口文档.md`                 | 更新             | 新增 3 个端点 + Celery 扩展                                         |
| `docs/开发文档/数据流通与模块职责.md`          | 更新             | 新增详情模块描述 + 数据流路径 D                                     |
| `tests/test_queries.py`                        | 新增用例         | 5 个新 Batch 查询函数测试                                           |
| `tests/test_statistics.py`                     | 新增用例         | get_batch_detail_stats 测试                                         |
| `tests/test_api_views.py`                      | 新增用例         | 3 个新端点测试                                                      |

---

## 八、设计决策记录

| 问题     | 选择                   | 理由                                                                        |
| -------- | ---------------------- | --------------------------------------------------------------------------- |
| 导航结构 | 独立路由（方案 B）     | 支持浏览器前进后退，URL 反映层级                                            |
| 数据来源 | 扩展 Batch 引擎        | Celery 预计算全部 Flow/StepNo 明细 → Redis，API 纯读缓存（对齐现有路径 A） |
| 搜索方式 | 仅 RegPerSysID         | 模型仅有数字 ID，无姓名字段                                                 |
| 权限控制 | 暂时跳过               | 先交付功能，预留钩子                                                        |
| 迷你图表 | 当日小时趋势           | 对齐 path B 数据粒度                                                        |
| 视角切换 | 概览页顶部 Tab         | Flow/StepNo 视图对称，切换清晰                                              |
| 页面架构 | 独立模板 + data-* 状态 | 对齐现有 dashboard.html 模式                                                |
| 目标产量 | 员工级独立设置         | 每员工独立目标值，Flow 总目标由员工目标求和                                 |
| 目标存储 | Redis JSON hash        | `targets:{date}:{flow}` = `{id: target}`，TTL 到午夜                    |
| 目标保存 | WebSocket 双向通信     | 前端发送 set_targets → Consumer 写入 Redis → 广播确认                     |
