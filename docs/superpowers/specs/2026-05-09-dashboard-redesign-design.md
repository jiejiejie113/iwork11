# 看板改版设计文档

> 日期：2026-05-09 | 状态：已确认

---

## 一、改版目标

重构生产看板前端视图，调整字段使用、主题布局、交互方式，聚焦成衣工序（StepNo=70），增强工序级分析与产线平衡可视化。

---

## 二、字段变更

### 删除字段

| 字段 | 原因 |
|------|------|
| `TimeCost`（平均耗时 KPI） | 非核心指标，移除 |

### 字段使用总览

| DB 字段 | 角色 | 聚合方式 | 使用主题 |
|---------|------|---------|---------|
| `Qty` | 核心度量 | SUM | 全部主题 |
| `RegDate` | 全局过滤 | WHERE 范围 | 全部主题 |
| `RegTime` | 维度 | HOUR() | 主题2、主题5 |
| `StepNo` | 维度/过滤 | IN 筛选 | 主题1、主题3a、主题3b |
| `Flow` | 维度 | GROUP BY | 主题3a、主题5 |
| `StationID` | 维度 | GROUP BY | 主题4、主题6 |
| `WrkOrder` | 维度 | GROUP BY | 主题7 |
| `TicketNo` | 辅助计数 | COUNT | 主题7 |

---

## 三、主题设计

### 主题 1：KPI 概览卡片

| 属性 | 内容 |
|------|------|
| 图表类型 | 3 个数字卡片 |
| 卡片 1 | **成衣工序产量**：`SUM(Qty) WHERE StepNo=70` |
| 卡片 2 | **今日工单数**：`COUNT(DISTINCT WrkOrder)` |
| 卡片 3 | **统计日期**：当前日期展示 |
| 数据范围 | 当天 |
| 目标 | 一秒掌握成衣工序的核心产量和活跃工单数 |

### 主题 2：每小时成衣产量趋势

| 属性 | 内容 |
|------|------|
| 图表类型 | 折线图（Line） |
| 维度 X | `HOUR(RegTime)` |
| 度量 Y | `SUM(Qty)` |
| 过滤 | `StepNo=70` |
| 数据范围 | 当天 |
| 目标 | 观察成衣工序产量随时间波动，发现产能高峰/低谷时段 |

### 主题 3a：工序产量对比（按 Flow 分组）

| 属性 | 内容 |
|------|------|
| 图表类型 | 分组柱状图（Grouped Bar） |
| 维度 X | `StepNo`（Top 10） |
| 分组 | `Flow`（每个 Flow 一个 dataset） |
| 度量 Y | `SUM(Qty)` |
| 数据范围 | 当天 |
| 工序选择 | 支持搜索多选，默认 Top 8 |
| 目标 | 对比各工序在不同流水线的产量分布 |

### 主题 3b：每日工序产量（堆积柱状图）

| 属性 | 内容 |
|------|------|
| 图表类型 | 堆积柱状图（Stacked Bar） |
| 维度 X | 日期（当月 1 日 ~ 今日） |
| 堆积段 | `StepNo`（用户选择的工序，默认 Top 8） |
| 度量 Y | `SUM(Qty)` |
| 数据范围 | 当月 |
| 工序选择 | 同 3a，共享选择器 |
| 目标 | 查看当月每日的工序产量结构变化 |

### 主题 3c：总产量日趋势

| 属性 | 内容 |
|------|------|
| 图表类型 | 折线图（Line） |
| 维度 X | 日期（当月 1 日 ~ 今日） |
| 度量 Y | `SUM(Qty)`（全工序合计或筛选工序合计） |
| 数据范围 | 当月 |
| 目标 | 看总产量逐日波动，快速感知产能变化趋势 |

### 主题 4：工站分布

| 属性 | 内容 |
|------|------|
| 图表类型 | 环形图（Doughnut） |
| 维度 | `StationID`，Top 10 |
| 度量 | `SUM(Qty)` |
| 数据范围 | 当天 |
| 目标 | 产量在各工站的分布占比 |

### 主题 5：工位负荷热力图

| 属性 | 内容 |
|------|------|
| 图表类型 | HTML Table 热力图（非 Chart.js） |
| Y 轴 | `Flow`（流水线） |
| X 轴 | `HOUR(RegTime)`（时段） |
| 颜色深度 | `SUM(Qty)`，5 阶色 |
| 配色 | `#BE5C37` → `#D78851` → `#DBBF92` → `#F3E1AF` → `#F7F7E9` |
| 数据范围 | 当天 |
| 工序过滤 | 支持任意 StepNo 选择 + 全工序切换 |
| 目标 | 一眼看出各流水线各时段的负荷分布，识别不均衡 |

### 主题 6：工站产量排行

| 属性 | 内容 |
|------|------|
| 图表类型 | 横向条形图（Horizontal Bar） |
| Y 轴 | `StationID` |
| X 轴 | `SUM(Qty)` |
| 数据范围 | 当天 |
| 工序过滤 | 支持任意 StepNo 选择 + 全工序切换 |
| 目标 | 快速识别产量最高/最低的工站，辅助资源调配 |

### 主题 7：工单列表

| 属性 | 内容 |
|------|------|
| 图表类型 | 分页表格 |
| 列 | 工单号、总产量、工序数、更新时间 |
| 分页 | 每页 20 条，支持上一页/下一页/页码点击/输入框跳转 |
| 数据范围 | 当天 |
| 目标 | 追踪活跃工单，支持翻页浏览全量工单 |

---

## 四、前端技术栈

| 项目 | 选择 |
|------|------|
| 框架 | **Vue 3**（CDN 引入，Composition API） |
| CSS | Tailwind CSS（CDN） |
| 图表 | Chart.js（CDN），热力图除外（HTML Table） |
| 构建 | 无构建工具，单文件 HTML |

### Vue 3 组件拆分

| 组件 | 职责 |
|------|------|
| `KpiCards` | 3 个 KPI 卡片 |
| `HourlyTrend` | 每小时产量趋势折线图 |
| `ProcessCompare` | 工序×Flow 分组柱状图 |
| `DailyProcessStack` | 每日工序产量堆积柱状图 |
| `MonthlyTrend` | 总产量日趋势折线图 |
| `StationDistribution` | 工站分布环形图 |
| `HeatmapTable` | 工位负荷热力图（HTML Table） |
| `StationRanking` | 工站产量排行横向条形图 |
| `WorkOrderTable` | 工单分页表格 |
| `StepNoSelector` | 工序搜索多选下拉（被 3a/3b 复用） |
| `Pagination` | 通用分页组件（被主题7 使用） |
| `AppToolbar` | 顶部工具栏（视图切换、StepNo 全局过滤、日期选择） |

### 响应式状态管理

使用 Vue 3 `reactive()` 管理全局状态：

```js
const state = reactive({
  currentView: 'realtime',   // 'realtime' | 'history'
  currentMode: 'local',      // 'local' | 'remote'
  stepnoFilter: [70],        // 全局工序过滤
  selectedDate: '',          // 历史视图日期
  dashboardData: { /* 所有主题的响应数据 */ }
})
```

---

## 五、后端 API 设计

### 新增查询函数（queries.py / local_queries.py）

| 函数 | SQL 聚合 | 用途 |
|------|---------|------|
| `get_monthly_total_trend(start, end, stepno_filter)` | `RegDate, SUM(Qty)` | 主题 3c |
| `get_monthly_process_stats(start, end, stepno_list, limit)` | `RegDate, StepNo, SUM(Qty)` | 主题 3b |
| `get_process_by_flow(target_date, stepno_list, limit)` | `StepNo, Flow, SUM(Qty)` | 主题 3a |
| `get_heatmap_data(target_date, stepno_filter)` | `HOUR(RegTime), Flow, SUM(Qty)` | 主题 5 |
| `get_station_ranking(target_date, stepno_filter, limit)` | `StationID, SUM(Qty)` | 主题 6 |
| `get_workorders_paginated(target_date, stepno_filter, page, page_size)` | `WrkOrder, SUM(Qty), COUNT(StepNo)` + OFFSET/LIMIT | 主题 7 |

### 修改现有函数

所有现有查询函数（`get_basic_stats`、`get_hourly_stats`、`get_process_stats`、`get_flow_stats`、`get_station_stats`、`get_worker_ranking`、`get_workorders_list`）统一增加 `stepno_filter: list[int] | None = None` 参数。传入时 SQL 追加 `AND StepNo IN (...)`。

### 新增 API 端点

| 端点 | 方法 | 参数 | 用途 |
|------|------|------|------|
| `/api/dashboard/monthly-trend/` | GET | `?stepno=70,69` | 主题 3c |
| `/api/dashboard/process-compare/` | GET | `?date=2026-05-09&stepnos=70,69,68` | 主题 3a |
| `/api/dashboard/heatmap/` | GET | `?date=2026-05-09&stepno=70` | 主题 5 |
| `/api/dashboard/station-ranking/` | GET | `?date=2026-05-09&stepno=70&limit=15` | 主题 6 |

### 修改现有端点

| 端点 | 改动 |
|------|------|
| `/api/dashboard/realtime/` | 增加 `?stepno=70` 参数，透传给各查询函数 |
| `/api/dashboard/workorders/` | 增加 `?page=1&page_size=20&stepno=70`，返回 `{items, total, page, page_size, total_pages}` |

### Celery 任务同步

`tasks.py` 中的 `sync_dashboard_stats` 需要同步更新缓存的 stats 结构，以包含新增的热力图和工站排行数据。

---

## 六、布局结构

```
┌─────────────────────────────────────────────────────────┐
│  AppToolbar: 视图切换 | StepNo选择 | 日期 | 连接状态      │
├─────────────────────────────────────────────────────────┤
│  KPI卡片 ×3          │                                  │
├───────────────────────┼──────────────────────────────────┤
│  主题2: 每小时趋势     │  主题3c: 月总产量日趋势           │
├───────────────────────┼──────────────────┬───────────────┤
│  主题3a: 工序×Flow    │ 主题3b: 每日堆积  │ 主题4: 工站分布 │
├───────────────────────┼──────────────────┼───────────────┤
│  主题5: 热力图         │ 主题6: 工站排行   │               │
├───────────────────────┴──────────────────┴───────────────┤
│  主题7: 工单列表（分页表格）                              │
└─────────────────────────────────────────────────────────┘
```

---

## 七、不纳入本次范围

- 员工排行（主题 6 原版）— 已删除
- Flow 效率环形图（主题 4 原版）— 已合并入工序对比
- 平均耗时 KPI — 已删除
- 后端历史 API 的月度查询 — 历史视图暂不提供月趋势，仅实时视图支持

---

## 八、风险与注意事项

1. **当月月趋势查询性能**：跨 1~31 天查询 `pytckreg3`（~3900 万行），需确保 `RegDate` 索引生效。需在 WHERE 条件中始终包含 `RegDate` 范围。
2. **热力图 HTML Table 实现**：Chart.js 无原生热力图支持，用 HTML Table + 动态 CSS 背景色实现，需注意数据量大时 DOM 节点数。
3. **Vue 3 CDN + Chart.js 集成**：Chart.js 实例需要在 `onMounted` 中初始化、`onUnmounted` 中销毁，避免图表重复创建。
4. **工序选择器搜索性能**：90+ 工序的下拉搜索，使用本地数组过滤即可，无需远程搜索。
