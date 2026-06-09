# 看板布局调整 + BUG 修复 设计文档

**日期**：2026-05-18
**状态**：设计中

---

## 1. 概述

对 `dashboard.html`（实时数据 + 历史数据共用模板）进行布局优化，同时修复两个线上 BUG。

### 1.1 布局变更

| 位置 | 变更 |
|------|------|
| Row 1 | 3 KPI 卡片 — 不变 |
| Row 2 左 | 每小时成衣产量趋势 — 不变 |
| Row 2 右 | 总产量日趋势（当月）→ **删除**，换为「每日工序产量（堆积）」 |
| Row 3 | 工序产量对比（按 Flow 分组）→ 独占全宽 |
| Row 4 左 | 工站分布（从 Row 3 移入） |
| Row 4 右 | 工站产量排行（从原 Row 4 移入） |
| Row 5 | 工位负荷热力图 → 独占全宽 |
| Row 6 | 工单列表 — 全宽（改为服务端分页） |

### 1.2 BUG 修复

| BUG | 根因 | 修复方向 |
|-----|------|----------|
| 工单列表无法翻页 | 前端假分页，后端批量只返回 20 条 | 翻页时调服务端分页 API |
| 全工序时 3 个图表无数据 | `statistics.py` 中 `batch['all']` 的 `process_flow_stats`/`heatmap_data`/`monthly_process_stats` 硬编码为空 | 在后端合并全工序数据 |

---

## 2. 后端修复：`iwork/statistics.py`

### 2.1 新增合并函数

在 `get_batch_stats()` 中，`batch['all']` 的三个字段需要从全工序数据合并而来：

```python
def _merge_batch_process_flow(batch_pf: dict) -> list:
    """合并全工序的 Flow 分组数据 → 'all' 视图"""
    merged = []
    for stepno, items in batch_pf.items():
        merged.extend(items)
    return merged


def _merge_batch_monthly_total(batch_monthly_total: dict) -> list:
    """合并全工序的月总趋势，按 date 求和"""
    merged = {}
    for stepno, items in batch_monthly_total.items():
        for item in items:
            d = item['date']
            merged[d] = merged.get(d, 0) + item['qty']
    return [{'date': d, 'qty': qty} for d, qty in sorted(merged.items())]


def _merge_batch_monthly_proc(batch_monthly_proc: dict, all_stepnos: set) -> list:
    """合并全工序的月工序堆积，限制显示的工序数为 Top 8"""
    # 先找 Top 8 工序（按总产量）
    step_qty = {}
    for stepno, items in batch_monthly_proc.items():
        step_qty[stepno] = sum(item['qty'] for item in items)
    top_steps = {s for s, _ in sorted(step_qty.items(), key=lambda kv: kv[1], reverse=True)[:8]}

    merged = []
    for stepno, items in batch_monthly_proc.items():
        if stepno in top_steps:
            merged.extend(items)
    return merged


def _merge_batch_heatmap(batch_heatmap: dict) -> dict:
    """合并全工序的热力图矩阵"""
    hours_set = set()
    flows_set = set()
    matrix = {}
    for stepno, hm in batch_heatmap.items():
        for hi, h in enumerate(hm['hours']):
            hours_set.add(h)
            for fi, f in enumerate(hm['flows']):
                flows_set.add(f)
                val = hm['data'][hi][fi] if hi < len(hm['data']) and fi < len(hm['data'][hi]) else 0
                matrix[(h, f)] = matrix.get((h, f), 0) + val

    hours = sorted(hours_set)
    flows = sorted(flows_set)
    return {
        'hours': hours,
        'flows': flows,
        'data': [[matrix.get((h, f), 0) for f in flows] for h in hours],
    }
```

### 2.2 修改 `batch['all']` 组装

```python
batch['all'] = {
    'workorder_count': len(wo_merged),
    'total_qty': all_total_qty,
    'date': today,
    'hourly_stats': all_hourly,
    'process_flow_stats': _merge_batch_process_flow(batch_pf),          # 修复
    'monthly_process_stats': _merge_batch_monthly_proc(batch_monthly_proc, all_stepnos),  # 修复
    'monthly_total_trend': _merge_batch_monthly_total(batch_monthly_total),  # 修复
    'station_stats': all_station_full[:10],
    'heatmap_data': _merge_batch_heatmap(batch_heatmap),                # 修复
    'station_ranking': all_station_full,
    'top_processes': all_top,
    'workorders': all_wo,
    'all_stepnos': all_stepnos_sorted,
}
```

### 2.3 历史查询路径确认

`_get_date_stats()` 的非 batch 路径（用于 `get_date_stats`/`get_local_date_stats` 的 `use_cache=False` 模式）不受影响：
- `stepno_filter=None` 时，`top_processes` 从 `get_process_stats(target, limit=8)` 取 Top 8 工序
- `stepno_list` 正确传递给 `get_process_by_flow`、`get_monthly_process_stats` 等
- 热力图 `get_heatmap_data(target, stepno_filter=None)` 查询全工序

---

## 3. 前端修复：工单服务端分页

### 3.1 API 端点

已有端点：`GET /api/dashboard/workorders/?page=2&page_size=20&stepno=70`

实时/历史视图共用，历史视图加 `&mode=local&date=2026-05-18`。

返回格式：
```json
{
  "items": [{ "wrk_order": "...", "total_qty": 100, "step_count": 3 }],
  "total": 150,
  "page": 2,
  "page_size": 20,
  "total_pages": 8
}
```

### 3.2 前端改动

新增状态：
```javascript
const workorderCache = reactive({});  // { page: [items] }
const workorderPagination = reactive({
    page: 1, page_size: 20, total: 0, total_pages: 1
});
```

修改 `workorderItems`：
```javascript
const workorderItems = computed(() => {
    const cached = workorderCache[workorderPage.value];
    if (cached) return cached;
    return data.workorders.slice(0, 20);  // 首屏 fallback
});
```

新增 `fetchWorkorderPage(page)`：
```javascript
async function fetchWorkorderPage(page) {
    const params = [`page=${page}`, `page_size=20`, buildStepnoParam()];
    if (currentView.value === 'history') {
        params.push(`mode=${currentMode.value}`, `date=${selectedDate.value}`);
    }
    const resp = await fetch(`/api/dashboard/workorders/?${params.filter(Boolean).join('&')}`);
    const result = await resp.json();
    workorderCache[page] = result.items;
    workorderPagination.total = result.total;
    workorderPagination.total_pages = result.total_pages;
    workorderPagination.page = result.page;
    workorderPage.value = page;
}
```

修改 `goWorkorderPage(p)`：
```javascript
async function goWorkorderPage(p) {
    const total = Math.max(1, workorderPagination.total_pages);
    if (p < 1 || p > total) return;
    if (!workorderCache[p]) {
        await fetchWorkorderPage(p);
    } else {
        workorderPage.value = p;
    }
    jumpPage.value = String(p);
}
```

### 3.3 历史视图 API 兼容

当前 `api_views.py` 的 `workorder_list` 端点只查远程数据库。需要支持 `?mode=local&date=...` 参数，在历史视图走本地数据库。

修改 `api_views.py` 的 `workorder_list`：
```python
@api_view(['GET'])
def workorder_list(request):
    mode = request.query_params.get('mode', 'remote')
    date_str = request.query_params.get('date', date.today().isoformat())
    target_date = date.fromisoformat(date_str)
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 20))
    stepno_filter = _parse_stepno(request)

    # 选择数据源
    if mode == 'local':
        from iwork.local_queries import get_workorders_paginated as local_paginated
        # 需要实现 local_queries 版本
    ...
```

**需要实现**：`local_queries.get_workorders_paginated()` — 目前不存在。需要新增。

---

## 4. 前端模板布局：`iwork/templates/iwork/dashboard.html`

### 4.1 HTML 结构变更

```html
<!-- ========== 第1行：KPI 卡片 ========== -->
<!-- 不变 -->

<!-- ========== 第2行：每小时趋势 + 每日工序堆积 ========== -->
<section class="grid grid-cols-2 gap-4 mb-6">
    <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <h3>每小时成衣产量趋势</h3>
        <div style="height:200px;"><canvas id="hourly-chart"></canvas></div>
    </div>
    <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <h3>每日工序产量（堆积）</h3>
        <div style="height:200px;"><canvas id="daily-process-chart"></canvas></div>
    </div>
</section>

<!-- ========== 第3行：工序产量对比（全宽） ========== -->
<section class="mb-6">
    <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <h3>工序产量对比（按 Flow 分组）</h3>
        <div class="flex items-center gap-2 mb-3">
            <!-- 工序选择器不变 -->
        </div>
        <div style="height:300px;"><canvas id="process-flow-chart"></canvas></div>
    </div>
</section>

<!-- ========== 第4行：工站分布 + 工站产量排行 ========== -->
<section class="grid grid-cols-2 gap-4 mb-6">
    <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <h3>工站分布</h3>
        <div style="height:250px;"><canvas id="station-dist-chart"></canvas></div>
    </div>
    <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <h3>工站产量排行</h3>
        <div style="height:250px;"><canvas id="station-rank-chart"></canvas></div>
    </div>
</section>

<!-- ========== 第5行：热力图（全宽） ========== -->
<section class="mb-6">
    <div class="bg-slate-800 border border-slate-700 rounded-lg p-4 overflow-x-auto">
        <h3>工位负荷热力图（时段 × 流水线）</h3>
        <!-- 热力图表格不变 -->
    </div>
</section>

<!-- ========== 第6行：工单列表 ========== -->
<!-- 翻页逻辑改为服务端分页 -->
```

### 4.2 JS 变更

1. **删除** `monthly-trend-chart` 渲染代码（`renderAllCharts` 中）
2. **删除** `data.monthly_total_trend` 的初始化
3. **新增** `workorderCache`、`fetchWorkorderPage()` 
4. **修改** `goWorkorderPage()` 为异步服务端分页
5. **调整**图表高度：流程对比图 180→300，工站分布/排行 180→250
6. `loadHistoryData` 中删除 `monthly_total_trend` 字段映射
7. `pageNumbers` computed 改用 `workorderPagination.total_pages`

---

## 5. 新增查询函数：`iwork/local_queries.py`

需要实现 `get_workorders_paginated()`（远程版已有，本地版缺失）：

```python
def get_workorders_paginated(target_date: date, page: int = 1, page_size: int = 20,
                              stepno_filter: list[int] | None = None) -> dict:
    """本地数据库分页工单列表"""
    # 与 queries.py 中的实现相同，但使用 LocalPytckreg3 模型
```

---

## 6. 测试要点

| 测试场景 | 验证内容 |
|----------|----------|
| 实时视图加载 | 新布局正确渲染 |
| 历史视图加载 | 切换日期后布局不变 |
| 全工序选择 | 工序产量对比、每日工序堆积、热力图均有数据 |
| 单选工序 | 图表按筛选正确过滤 |
| 工单翻页第 1 页 | 显示前 20 条 |
| 工单翻页第 2 页 | 调 API 获取新 20 条，不覆盖缓存 |
| 工单翻页切换回第 1 页 | 使用缓存，不重复请求 |
| 删除月趋势图 | 页面无报错，无空白区块 |
| 实时推送 | WebSocket 消息不破坏分页状态 |

---

## 7. 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `iwork/statistics.py` | 新增 4 个合并函数 + 修改 `batch['all']` |
| `iwork/templates/iwork/dashboard.html` | HTML 布局重排 + JS 分页逻辑改写 |
| `iwork/api_views.py` | `workorder_list` 支持 mode/date 参数 |
| `iwork/local_queries.py` | 新增 `get_workorders_paginated()` |
| `tests/test_statistics.py` | 新增合并函数单测 |
| `tests/test_local_queries.py` | 新增分页查询单测 |
