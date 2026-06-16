# 产量看板模块 — 设计文档

> 日期：2026-06-16 | 状态：设计完成

## 1. 概述

在 iwork 项目中新增"产量看板"标签页，提供工人产量排行榜、统计卡片、产量分布图，支持多维筛选与分页。

**参考原型**：`产量看板demo.html`（dark-theme 独立原型，CSS 变量 + 动效）

**核心要求**：
- 保留原型所有卡片视图和动效
- 主题替换为 iwork 现有 Tailwind 暗色主题（slate-900/slate-800/blue-600）
- 字段替换为真实业务字段（Pytckreg3 表）
- 排行榜分页（50 条/页）
- 默认筛选：StepNo='70'、全部款号
- 筛选器：工序、款号、分组（Flow 多选）、员工（级联 Flow）+ 清空按钮
- 日期可选（默认当天）

---

## 2. 架构

```
┌─ 前端 ─────────────────────────────────────────────────┐
│  kanban.html (Django 模板 + Vue 3 CDN + Tailwind CSS)   │
│  ├─ 统计卡片（animated counters）                       │
│  ├─ 筛选栏（日期/工序/款号/Flow多选/员工/清空）          │
│  ├─ 排行榜表格（分页 50 条/页，排名徽章，产量条）         │
│  └─ 产量分布图（柱状图，消费同一排行榜数据）              │
├─ API 层 ────────────────────────────────────────────────┤
│  api_views.py — 3 个新端点                              │
├─ 查询层 ────────────────────────────────────────────────┤
│  queries.py — 3 个新函数 + 1 个共用过滤工具              │
│  local_queries.py — 镜像实现（3 + 1）                   │
├─ 数据层 ────────────────────────────────────────────────┤
│  Pytckreg3（远程只读）+ LocalPytckreg3（本地）           │
└─────────────────────────────────────────────────────────┘
```

**与现有系统关系**：
- 作为新标签页加入，与"实时数据""历史数据""生产详情"并列
- 历史数据模式复用 `api_views_local.py` 的模式（`?mode=local|remote`）
- 查询函数遵循 `queries.py` 现有模式（`get_records_queryset` + Django ORM 聚合）
- 筛选逻辑参考现有 `apply_stepno_filter` / `apply_flow_filter`

---

## 3. API 接口

### 3.1 端点总览

| 序号 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 1 | GET | `/api/kanban/stats/` | 统计汇总（工人数/总产/人均/最高） |
| 2 | GET | `/api/kanban/ranking/` | 排行榜分页列表 |
| 3 | GET | `/api/kanban/filter-options/` | 筛选项（工序/款号/Flow/员工） |

### 3.2 `GET /api/kanban/stats/` — 统计汇总

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `date` | string | 是 | 当天 | `YYYY-MM-DD` |
| `stepno` | string | 否 | `70` | 工序号筛选 |
| `wrk_order` | string | 否 | — | 款号筛选，不传=全部 |
| `flow` | string | 否 | — | 分组筛选，可多传 `flow=SO3&flow=SO5` |
| `reg_per_sys_id` | string | 否 | — | 员工筛选 |

**响应示例**：

```json
{
  "worker_count": 150,
  "total_production": 5000,
  "avg_production": 33,
  "max_production": 200,
  "max_worker_name": "12345"
}
```

- `worker_count`：筛选条件下不重复工人数
- `total_production`：筛选条件下总产量（Qty 汇总）
- `avg_production`：`total / worker_count`（四舍五入取整）
- `max_production`：单人最高产量
- `max_worker_name`：最高产工人的 RegPerSysID（转字符串）

### 3.3 `GET /api/kanban/ranking/` — 排行榜

**查询参数**：同 stats，额外增加：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | `1` | 页码 |
| `page_size` | int | `50` | 每页条数 |

**响应示例**：

```json
{
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_pages": 3,
    "total_count": 128
  },
  "workers": [
    {
      "rank": 1,
      "reg_per_sys_id": "12345",
      "worker_name": "12345",
      "stepno": "70",
      "wrk_order": "SO3-20250601-001",
      "flow": "SO3",
      "production": 200
    }
  ]
}
```

- `workers` — 当前页数据，按 production 降序
- 表格和柱状图消费同一 `workers` 数组
- `stepno`/`wrk_order`/`flow` 取自该工人产量最大的那条记录
- `production` 是该工人在筛选条件下的 Qty 汇总
- `rank` 全局排名（跨页）

### 3.4 `GET /api/kanban/filter-options/` — 筛选项

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `date` | string | 是 | `YYYY-MM-DD` |
| `flow` | string | 否 | 传入时，员工列表仅返回这些 Flow 下的员工 |

**响应示例**：

```json
{
  "stepnos": ["60", "70", "80"],
  "wrk_orders": ["SO3-001", "SO5-002"],
  "flows": ["SO3", "SO5", "SO8"],
  "employees": [
    {"reg_per_sys_id": "12345", "name": "12345"}
  ]
}
```

- 筛选项从当天实际有数据的记录中动态生成
- `employees` 根据 `flow` 参数级联过滤

---

## 4. 查询函数

### 4.1 函数清单（queries.py + local_queries.py 镜像）

| 函数 | 对应端点 | 说明 |
|------|----------|------|
| `get_kanban_stats()` | stats/ | 聚合统计 |
| `get_kanban_ranking()` | ranking/ | 分页排行榜 |
| `get_kanban_filter_options()` | filter-options/ | 筛选项 |
| `_apply_kanban_filters()` | (内部) | 共用筛选逻辑 |

### 4.2 `_apply_kanban_filters(queryset, stepno, wrk_order, flows, reg_per_sys_id)`

```python
def _apply_kanban_filters(queryset, stepno=None, wrk_order=None,
                          flows=None, reg_per_sys_id=None):
    """产量看板通用筛选器（内部工具函数）

    对 QuerySet 依次应用工序、款号、分组、员工筛选。

    Args:
        queryset: Pytckreg3 QuerySet
        stepno (str|None): 工序号，None 或 '' 表示不过滤
        wrk_order (str|None): 款号，None 或 '' 表示不过滤
        flows (list[str]|None): 分组列表，None 或 [] 表示不过滤
        reg_per_sys_id (str|None): 员工ID，None 或 '' 表示不过滤

    Returns:
        QuerySet: 应用筛选后的 QuerySet
    """
    if stepno:
        queryset = queryset.filter(StepNo=stepno)
    if wrk_order:
        queryset = queryset.filter(WrkOrder=wrk_order)
    if flows:
        queryset = queryset.filter(Flow__in=flows)
    if reg_per_sys_id:
        queryset = queryset.filter(RegPerSysID=reg_per_sys_id)
    return queryset
```

### 4.3 `get_kanban_stats(target_date, stepno=None, wrk_order=None, flows=None, reg_per_sys_id=None)`

```python
def get_kanban_stats(target_date, stepno=None, wrk_order=None,
                     flows=None, reg_per_sys_id=None):
    """产量看板统计汇总

    按工人聚合产量后，计算工人数、总产、人均、最高产。

    Args:
        target_date (date): 查询日期
        stepno (str|None): 工序筛选
        wrk_order (str|None): 款号筛选
        flows (list[str]|None): 分组筛选（多选）
        reg_per_sys_id (str|None): 员工筛选

    Returns:
        dict: {worker_count, total_production, avg_production, max_production, max_worker_name}
    """
```

**实现逻辑**：
1. `get_records_queryset(target_date)` 获取当日记录
2. `_apply_kanban_filters()` 应用筛选
3. `.values('RegPerSysID').annotate(production=Sum('Qty'))` 按工人聚合
4. 对聚合结果做 `Count`/`Sum`/`Max` 二次聚合
5. 取 `max_worker_name` = 产量最高的 RegPerSysID

### 4.4 `get_kanban_ranking(target_date, stepno=None, wrk_order=None, flows=None, reg_per_sys_id=None, page=1, page_size=50)`

```python
def get_kanban_ranking(target_date, stepno=None, wrk_order=None,
                       flows=None, reg_per_sys_id=None,
                       page=1, page_size=50):
    """产量看板排行榜

    按工人聚合产量，取主要工序/款号/分组，分页返回。

    Args:
        target_date (date): 查询日期
        stepno (str|None): 工序筛选
        wrk_order (str|None): 款号筛选
        flows (list[str]|None): 分组筛选（多选）
        reg_per_sys_id (str|None): 员工筛选
        page (int): 页码（从1开始）
        page_size (int): 每页条数，默认50

    Returns:
        dict: {pagination: {page, page_size, total_pages, total_count},
               workers: [{rank, reg_per_sys_id, worker_name, stepno, wrk_order, flow, production}]}
    """
```

**实现逻辑**：
1. 获取当日记录，应用筛选
2. `.values('RegPerSysID', 'StepNo', 'WrkOrder', 'Flow').annotate(qty=Sum('Qty'))` 四级分组
3. Python 层 `_merge_worker_rows()`：同一工人在不同 WrkOrder/Flow 下的记录合并
   - `production` = SUM(qty)
   - `stepno` = 产量最大的那条的 StepNo
   - `wrk_order` = 产量最大的那条的 WrkOrder
   - `flow` = 产量最大的那条的 Flow
4. 按 production 降序排列
5. 计算 `total`、`total_pages`
6. 切片 `[(page-1)*page_size : page*page_size]`
7. 注入 `rank`（全局序号）

#### 辅助函数 `_merge_worker_rows(rows)`

```python
def _merge_worker_rows(rows):
    """合并同一工人在不同 WrkOrder/Flow 下的记录

    输入：ORM 返回的 [(RegPerSysID, StepNo, WrkOrder, Flow, qty), ...]
    输出：[{reg_per_sys_id, worker_name, stepno, wrk_order, flow, production}, ...]

    合并逻辑：
    - production = SUM(所有 qty)
    - stepno/wrk_order/flow = 取 qty 最大的那条记录的值
    - worker_name = str(reg_per_sys_id)
    """
```

### 4.5 `get_kanban_filter_options(target_date, flows=None)`

```python
def get_kanban_filter_options(target_date, flows=None):
    """产量看板筛选项

    获取当天可用的工序、款号、分组、员工列表。

    Args:
        target_date (date): 查询日期
        flows (list[str]|None): 分组筛选，用于级联员工列表

    Returns:
        dict: {stepnos, wrk_orders, flows, employees}
    """
```

**实现逻辑**：
1. 获取当日记录
2. `stepnos`：所有不重复 StepNo（按值升序）
3. `wrk_orders`：所有不重复 WrkOrder（按值升序）
4. `flows`：所有不重复非空 Flow（按值升序）
5. `employees`：按 (RegPerSysID) 分组求和后的员工列表，若传入 flows 则先筛选 Flow

---

## 5. 前端设计

### 5.1 模板文件

`iwork/templates/iwork/kanban.html`

- 继承或引入共享头部 `_header.html`（标签页导航）
- Vue 3 CDN（使用 `{[` `]}` 分隔符，与现有模板一致）
- Tailwind CSS CDN（`darkMode: 'class'`）
- 所有 CSS/JS 内联，无构建步骤

### 5.2 主题映射

demo 的 CSS 变量 → iwork Tailwind 类：

| demo CSS 变量 | demo 值 | iwork Tailwind |
|---------------|---------|----------------|
| `--bg` | `#0a0b0e` | `bg-slate-900` |
| `--surface` | `#12141a` | `bg-slate-800` |
| `--surface-2` | `#1a1d26` | `bg-slate-700` |
| `--surface-3` | `#22252f` | `bg-slate-600` |
| `--accent` | `#f0a500` | `text-blue-400` / `bg-blue-600` |
| `--accent-dim` | `#f0a50033` | `bg-blue-600/20` |
| `--text` | `#e8e6e1` | `text-slate-100` |
| `--text-muted` | `#6b6d75` | `text-slate-400` |
| `--text-dim` | `#3e4048` | `text-slate-500` |
| `--success` | `#2dd4a8` | `text-emerald-400` |
| `--danger` | `#f05545` | `text-red-500` |
| `--border` | `#282a33` | `border-slate-700` |
| `--radius` | `8px` | `rounded-lg` |
| 字体 Noto Sans SC | Google Fonts | 系统字体栈（`font-sans`） |
| 字体 DM Mono | Google Fonts | `font-mono` |

### 5.3 Vue 3 状态

```javascript
const state = reactive({
  // 日期
  date: new Date().toISOString().slice(0, 10),

  // 筛选值
  filters: {
    stepno: '70',         // 默认 70 工序
    wrk_order: '',        // 空字符串 = 全部
    flows: [],            // 空数组 = 全部（多选）
    reg_per_sys_id: '',   // 空字符串 = 全部
  },

  // 筛选可选项
  filterOptions: {
    stepnos: [],
    wrk_orders: [],
    flows: [],
    employees: [],
  },

  // 统计数据
  stats: {
    worker_count: 0,
    total_production: 0,
    avg_production: 0,
    max_production: 0,
    max_worker_name: '',
  },

  // 排行榜
  ranking: {
    workers: [],
    pagination: { page: 1, page_size: 50, total_pages: 1, total_count: 0 },
  },

  // 加载状态
  loading: {
    stats: false,
    ranking: false,
  },
});
```

### 5.4 核心方法

| 方法 | 触发时机 | 行为 |
|------|----------|------|
| `fetchStats()` | 页面加载、筛选变化 | 请求 stats/，更新统计卡片 |
| `fetchRanking(page)` | 页面加载、筛选变化、翻页 | 请求 ranking/?page=N，更新表格+图表 |
| `fetchFilterOptions()` | 页面加载、日期变化、Flow 变化 | 请求 filter-options/，更新下拉选项 |
| `onFilterChange()` | 任何筛选器值变化 | 重置 page=1，并行调用上面 3 个 |
| `onPageChange(page)` | 点击分页按钮 | 仅调用 fetchRanking(page) |
| `clearFilters()` | 点击清空按钮 | 恢复默认值（stepno='70'，其余全部），触发 onFilterChange |
| `updateClock()` | 每秒 | 更新 Header 时钟显示 |

### 5.5 交互细节

**筛选联动**：
1. Flow 多选变化 → 重新请求 `filter-options/?flow=SO3&flow=SO5` 更新员工列表
2. 如果当前选中的员工不在新 Flow 筛选结果中 → 清空员工筛选
3. 其他筛选器变化 → 仅刷新 stats + ranking

**分页**：
- 表格底部显示：`◀ 上一页  第 1/3 页  下一页 ▶`
- 首页时"上一页"禁用，末页时"下一页"禁用
- 翻页不触发 stats 重新请求

**清空按钮**：
- 工序 → `'70'`（默认值，非全部）
- 款号 → `''`（全部）
- 分组 → `[]`（全部）
- 员工 → `''`（全部）

### 5.6 保留的动效

| 动效 | 实现方式 | 位置 |
|------|----------|------|
| 实时指示点脉冲 | CSS `@keyframes pulse` | Header `.live::before` |
| 表格行动画 | CSS `@keyframes rowIn` + `animation-delay` 递增 | tbody tr |
| 柱状图动画 | CSS `@keyframes barIn` + `animation-delay` 递增 | .bar-row |
| 产量条过渡 | CSS `transition: width 0.6s` | .prod-bar |
| 统计数字滚动 | JS `setInterval` 步进动画 | stat-card .value |
| 排名徽章渐变色 | CSS `linear-gradient` | .rank-1/2/3 |
| 背景微光 | CSS `radial-gradient`（Tailwind 无法完全复刻，保留少量自定义 CSS） | body::after |
| 纹理叠加 | SVG feTurbulence 噪声（保留） | body::before |

### 5.7 响应式

| 断点 | 行为 |
|------|------|
| `< 900px` | 统计卡片 2 列，内容区单列 |
| `< 600px` | 统计卡片 1 列，筛选器纵向排列，Header 纵向 |

---

## 6. URL 路由

### 6.1 页面路由（`iwork/urls.py`）

```python
path('kanban/', views.kanban_page, name='kanban_page'),
```

### 6.2 API 路由（`iwork/urls.py`）

```python
path('api/kanban/stats/', api_views.kanban_stats, name='kanban_stats'),
path('api/kanban/ranking/', api_views.kanban_ranking, name='kanban_ranking'),
path('api/kanban/filter-options/', api_views.kanban_filter_options, name='kanban_filter_options'),
```

### 6.3 头部标签页

在 `_header.html` 添加"产量看板"标签，链接到 `/kanban/`。

---

## 7. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `iwork/templates/iwork/kanban.html` | 产量看板页面模板（~500 行） |

### 修改

| 文件 | 变更 |
|------|------|
| `iwork/queries.py` | 新增 `get_kanban_stats`、`get_kanban_ranking`、`get_kanban_filter_options`、`_apply_kanban_filters`（~80 行） |
| `iwork/local_queries.py` | 镜像新增 4 个相同函数（~80 行） |
| `iwork/api_views.py` | 新增 3 个 API 视图函数（~60 行） |
| `iwork/urls.py` | 新增 4 条路由（页面 + 3 API） |
| `iwork/views.py` | 新增 `kanban_page` 视图函数（~5 行） |
| `iwork/templates/iwork/_header.html` | 新增"产量看板"标签 |

---

## 8. 错误处理

| 场景 | 处理 |
|------|------|
| 数据库查询超时 | API 返回 504，前端显示"加载失败，点击重试" |
| 筛选结果为空 | stats 返回 0 值，ranking 返回空数组，前端显示空状态占位图 |
| 非法日期格式 | API 返回 400 `{"error": "日期格式错误，需为 YYYY-MM-DD"}` |
| 页码越界 | API 返回空数据 + `total_pages`，前端修正页码 |
| 数据库连接失败 | API 返回 503，前端提示"服务暂时不可用" |

---

## 9. 测试策略

| 层级 | 测试内容 | 方法 |
|------|----------|------|
| 查询函数 | stats/ranking/filter-options 返回值结构和类型 | `pytest` + Django TestCase |
| 查询函数 | 筛选条件组合的正确性 | 参数化测试 |
| 查询函数 | 空结果处理 | 边界测试 |
| API | HTTP 状态码和响应格式 | DRF APITestCase |
| API | 参数校验 | 非法参数测试 |
| 前端 | 筛选联动、分页、清空 | 手动验证 |
| 镜像 | local_queries.py 与 queries.py 输出一致 | 对比测试 |

---

## 10. 配置项

在 `iwork/settings.py` 业务配置区块新增：

```python
# 产量看板默认配置
KANBAN_DEFAULT_STEPNO = '70'       # 默认工序筛选值
KANBAN_DEFAULT_PAGE_SIZE = 50      # 排行榜每页条数
```
