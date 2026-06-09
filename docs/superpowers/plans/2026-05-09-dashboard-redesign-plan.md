# 看板改版实施计划

> 基于设计文档 2026-05-09-dashboard-redesign-design.md

## 实施步骤

### 第 1 步：后端 — 修改现有查询函数，增加 stepno_filter 参数
文件：`iwork/queries.py`
- 所有查询函数增加 `stepno_filter: list[int] | None = None` 参数
- 传入时 SQL 追加 `AND StepNo IN (...)`
- 涉及：`get_basic_stats`, `get_hourly_stats`, `get_process_stats`, `get_flow_stats`, `get_station_stats`, `get_worker_ranking`, `get_workorders_list`

### 第 2 步：后端 — 新增查询函数
文件：`iwork/queries.py`
- `get_monthly_total_trend(start, end, stepno_filter)` — 月总产量日趋势
- `get_monthly_process_stats(start, end, stepno_list, limit)` — 月工序日产量
- `get_process_by_flow(target_date, stepno_list, limit)` — 工序×Flow
- `get_heatmap_data(target_date, stepno_filter)` — 热力图矩阵
- `get_station_ranking(target_date, stepno_filter, limit)` — 工站排行
- `get_workorders_paginated(target_date, stepno_filter, page, page_size)` — 分页工单

### 第 3 步：后端 — 本地查询镜像
文件：`iwork/local_queries.py`
- 同步第 1、2 步的改动到本地查询

### 第 4 步：后端 — 修改 statistics.py 和 tasks.py
文件：`iwork/statistics.py`, `iwork/tasks.py`
- statistics: 更新 stats 结构，包含新图表数据
- tasks: sync_dashboard_stats 同步新结构

### 第 5 步：后端 — 新增/修改 API 端点
文件：`iwork/api_views.py`
- 修改 `realtime_stats`：支持 `?stepno=` 参数
- 修改 `workorder_list`：支持分页 `?page=&page_size=`
- 新增：`monthly_trend`, `process_compare`, `heatmap`, `station_ranking`

### 第 6 步：前端 — Vue 3 + 组件重写
文件：`iwork/templates/iwork/dashboard.html`
- 引入 Vue 3 CDN + Chart.js
- 实现全部 11 个组件 + 全局状态管理
- 删除旧的纯 JS 代码

### 第 7 步：运行测试确保无回归
运行 `pytest` 确认现有测试通过，必要时更新测试
