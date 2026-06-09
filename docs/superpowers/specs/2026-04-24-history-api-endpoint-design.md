# 历史数据独立API端点设计

## 问题陈述

当前历史数据API和实时数据API都在 `/api/dashboard/` 路径下，导致前端同时调用时数据覆盖问题。

## 解决方案

为历史数据创建独立的URL端点 `/api/history/`，实现前后端分离。

## URL路由结构

### 实时数据（保持不变）
```
/api/dashboard/realtime/
/api/dashboard/hourly/
/api/dashboard/flow/<name>/
/api/dashboard/workorders/
/api/dashboard/workorders/<id>/
```

### 历史数据（迁移到新端点）
```
/api/history/date/<date>/         # 历史数据查询
/api/history/dates/               # 可用日期查询
/api/history/sync/<date>/         # 数据同步
```

## 后端实现

### 新建文件：`iwork/history_urls.py`

```python
from django.urls import path
from iwork import api_views_local

app_name = 'history'

urlpatterns = [
    path('date/<str:target_date>/', api_views_local.local_date_stats, name='local-date-stats'),
    path('dates/', api_views_local.available_dates, name='available-dates'),
    path('sync/<str:target_date>/', api_views_local.sync_date, name='sync-date'),
]
```

### 修改文件：`iwork/urls.py`

```python
from django.urls import path, include
from iwork import views, api_views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    
    # 实时数据API
    path("api/dashboard/realtime/", api_views.realtime_stats, name="realtime-stats"),
    path("api/dashboard/hourly/", api_views.hourly_stats, name="hourly-stats"),
    path("api/dashboard/flow/<str:flow_name>/", api_views.flow_stats, name="flow-stats"),
    path("api/dashboard/workorders/", api_views.workorder_list, name="workorder-list"),
    path("api/dashboard/workorders/<str:wrk_order>/", api_views.workorder_detail, name="workorder-detail"),
    
    # 历史数据API（迁移到独立路由）
    path("api/history/", include('iwork.history_urls')),
]
```

**注意**：视图函数 `api_views_local.py` 保持不变，只修改路由。

## 前端实现

### 修改文件：`iwork/templates/iwork/dashboard.html`

需要修改3处API调用：

1. **loadAvailableDates()** (第420行)
```javascript
// 旧：`/api/dashboard/dates/?mode=${currentMode}`
// 新：`/api/history/dates/?mode=${currentMode}`
```

2. **loadHistoryData()** (第438行)
```javascript
// 旧：`/api/dashboard/date/${selectedDate}/?mode=${currentMode}`
// 新：`/api/history/date/${selectedDate}/?mode=${currentMode}`
```

3. **syncData()** (第468行)
```javascript
// 旧：`/api/sync/${selectedDate}/`
// 新：`/api/history/sync/${selectedDate}/`
```

## 成功标准

1. 历史数据API调用不再与WebSocket推送冲突
2. 前端实时数据和历史数据视图切换正常
3. 所有现有功能保持不变

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 旧URL被外部调用 | 可考虑保留旧URL做重定向 |
| 前端缓存问题 | 清除浏览器缓存后测试 |
