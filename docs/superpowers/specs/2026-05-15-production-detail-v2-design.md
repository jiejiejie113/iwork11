# 生产详情页 v2 优化 — 技术设计

> 日期：2026-05-15 | 状态：已确认

## 一、布局整合

顶部工具栏与导航栏合并为一行，节省纵向空间：

```
[实时数据] [历史数据] [生产详情] | 生产看板 - 生产详情 | 🔍搜索 | 📅日期 | [按Flow] [按工序] | 更新 HH:MM:SS
```

**改动**：
- 移除独立的 `<header>` 标题行
- 搜索框、日期选择器、Tab 切换全部并入导航行
- 无权限卡片保留灰色不可点击样式

---

## 二、工序查询优化（消除 N+1）

### 当前问题

`loadStepnoOverview()` 对每个工序号逐条 `fetch(/api/dashboard/detail/stepno/{n}/)` —— 40 个工序 = 40 次 HTTP 请求。

### 优化方案

**后端**：在 `get_batch_detail_stats` 中追加 `get_batch_stepno_employees` 查询：

```python
# statistics.py — get_batch_detail_stats 新增第4个并行查询
f_stepno = pool.submit(q.get_batch_stepno_employees, today)
# 返回新增字段: 'stepno_employees': f_stepno.result()
```

在 `cache_detail_batch_to_redis` 中追加缓存写入：

```python
cache.set('stats:detail:stepno_overview', detail_batch['stepno_employees'], ttl)
```

**前端**：`loadStepnoOverview` 改为一次请求拿全数据：

```
fetch(/api/dashboard/processes/)          ← 获取工序号列表（已有）
fetch 单次读取 stats:detail:stepno_overview ← 新增（或扩展 processes API 返回汇总）
```

---

## 三、新增可视化图表

卡片网格上方新增图表区（左右并列，Chart.js 渲染）：

### 左：柱状折线图（组合图）

| 元素 | 说明 |
|------|------|
| 类型 | `type: 'bar'` + `type: 'line'` 组合 |
| X轴 | Flow 名称 / 工序号 |
| 柱状 | 产量 `qty`，蓝色 |
| 折线 | 人数 `worker_count`，绿色，`yAxisID: 'y1'`（右侧 Y 轴） |
| Tab切换 | `groupMode === 'flow'` 用 Flow 数据，`'stepno'` 用工序数据 |

### 右：环形图（Doughnut）

| 元素 | 说明 |
|------|------|
| 类型 | `type: 'doughnut'` |
| 数据 | 各 Flow/工序的产量占比 |
| 居中 | Chart.js 插件或 CSS 叠加显示总产量数字 |
| Tab切换 | 同样跟随 `groupMode` 切换数据源 |

### 数据源

两个图表共用同一份数据，由现有查询函数产生：

| 视图 | 数据来源 |
|------|---------|
| Flow 视图 | `get_batch_flow_overview`（已有）— `{flow: {total_qty, worker_count}}` |
| 工序视图 | `get_batch_stepno_employees`（新增到 batch）— 按 stepno 汇总 qty 和 worker_count |

前端转换为 Chart.js 格式：

```javascript
const chartData = flowCards.map(c => ({ label: c.flow, qty: c.total_qty, workers: c.worker_count }));
```

---

## 四、更新时间

| 来源 | 显示 |
|------|------|
| WebSocket `dashboard_update` 携带 `timestamp` | `更新 HH:MM:SS` |
| 各 Flow 卡片 | 上次数据刷新的时间（跟随概览页加载时间） |
| 无 WebSocket / 无数据 | `--` |

---

## 五、验收标准

| # | 验收项 | 预期行为 | 验证方式 |
|---|--------|---------|---------|
| 1 | 布局整合 | 标题、搜索框、日期、Tab 切换与导航栏在同一行 | 打开 `/production/detail-data/`，顶部只有一行工具栏 |
| 2 | 更新时间（概览） | 导航行右侧显示"更新 HH:MM:SS"，收到 WS 推送后刷新 | 等待 Celery 60s 推送，观察时间变化 |
| 3 | 更新时间（卡片） | 每个 Flow 卡片右上角显示更新时间 | 概览页所有卡片右上角均有时间 |
| 4 | 工序查询不再有 N+1 | 切换到工序视图时，浏览器 Network 面板无大量 stepno 请求 | 打开 F12 Network，切换"按工序"，请求数 < 5 |
| 5 | 柱状折线图（Flow） | 显示各 Flow 产量柱状 + 人数折线，右侧 Y 轴标注人数 | 概览页按 Flow 视图上方有组合图 |
| 6 | 柱状折线图（工序） | Tab 切换到工序后，图表自动切换到工序维度 | 点击"按工序"，图表 X 轴变为工序号 |
| 7 | 环形图 | 显示各分组产量占比，居中显示总产量 | 柱状折线图右侧有环形图 |
| 8 | 环形图切换 | Tab 切换时环形图同步切换数据源 | 切换"按工序"，环形图改为工序占比 |
| 9 | 图表切换无闪烁 | 切换 Tab 时旧卡片消失新卡片出现，图表平滑更新 | 切换时不出现全页白屏或加载蒙版 |
| 10 | 响应式 | 窄屏下图表上下堆叠，卡片从 3 列变 1 列 | 缩小浏览器宽度，布局自适应 |

---

## 六、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `iwork/statistics.py` | 修改 | `get_batch_detail_stats` 追加第4个并行查询 |
| `iwork/statistics.py` | 修改 | `cache_detail_batch_to_redis` 追加 stepno 缓存键 |
| `iwork/templates/iwork/production_detail.html` | 修改 | 布局重构 + 新图表 + 更新时间 + 工序批量查询 |
| `tests/test_statistics.py` | 追加 | `get_batch_detail_stats` 新增 stepno 字段测试 |
