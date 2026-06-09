# 历史数据独立API端点实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为历史数据创建独立的URL端点 `/api/history/`，避免与WebSocket推送冲突

**Architecture:** 新建 `history_urls.py` 路由文件，在 `urls.py` 中使用 `include()` 引入，前端修改API调用路径

**Tech Stack:** Django, JavaScript

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `iwork/history_urls.py` | 新建 | 历史数据独立路由文件 |
| `iwork/urls.py` | 修改 | 移除历史数据路由，添加include |
| `iwork/templates/iwork/dashboard.html` | 修改 | 更新前端API调用路径 |

---

### Task 1: 新建历史数据路由文件

**Files:**
- Create: `iwork/history_urls.py`

- [ ] **Step 1: 创建 history_urls.py**

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

- [ ] **Step 2: 验证文件创建成功**

Run: `python -c "from iwork.history_urls import urlpatterns; print(f'路由数量: {len(urlpatterns)}')"`
Expected: `路由数量: 3`

- [ ] **Step 3: Commit**

```bash
git add iwork/history_urls.py
git commit -m "[2026-04-24][FEAT] 新建历史数据独立路由文件"
```

---

### Task 2: 修改主路由文件

**Files:**
- Modify: `iwork/urls.py`

- [ ] **Step 1: 更新 urls.py**

将 `iwork/urls.py` 修改为：

```python
"""
URL configuration for iwork project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
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

- [ ] **Step 2: 验证路由加载成功**

Run: `python -c "from iwork.urls import urlpatterns; print(f'路由数量: {len(urlpatterns)}')"`
Expected: `路由数量: 6`

- [ ] **Step 3: Commit**

```bash
git add iwork/urls.py
git commit -m "[2026-04-24][FEAT] 修改主路由，引入历史数据独立路由"
```

---

### Task 3: 更新前端API调用

**Files:**
- Modify: `iwork/templates/iwork/dashboard.html`

- [ ] **Step 1: 修改 loadAvailableDates() 函数**

找到第420行，将：
```javascript
const response = await fetch(`/api/dashboard/dates/?mode=${currentMode}`);
```
修改为：
```javascript
const response = await fetch(`/api/history/dates/?mode=${currentMode}`);
```

- [ ] **Step 2: 修改 loadHistoryData() 函数**

找到第438行，将：
```javascript
const response = await fetch(`/api/dashboard/date/${selectedDate}/?mode=${currentMode}`);
```
修改为：
```javascript
const response = await fetch(`/api/history/date/${selectedDate}/?mode=${currentMode}`);
```

- [ ] **Step 3: 修改 syncData() 函数**

找到第468行，将：
```javascript
const response = await fetch(`/api/sync/${selectedDate}/`, {
```
修改为：
```javascript
const response = await fetch(`/api/history/sync/${selectedDate}/`, {
```

- [ ] **Step 4: 验证前端修改**

Run: `python -c "import re; content=open('iwork/templates/iwork/dashboard.html').read(); print('历史数据API调用数:', len(re.findall(r'/api/history/', content)))"`
Expected: `历史数据API调用数: 3`

- [ ] **Step 5: Commit**

```bash
git add iwork/templates/iwork/dashboard.html
git commit -m "[2026-04-24][FEAT] 更新前端API调用，使用历史数据独立端点"
```

---

### Task 4: 集成测试

**Files:**
- Test: 手动测试

- [ ] **Step 1: 启动开发服务器**

Run: `python manage.py runserver`

- [ ] **Step 2: 测试实时数据视图**

1. 打开浏览器访问 `http://localhost:8000/`
2. 确认默认显示"实时数据"视图
3. 确认WebSocket连接正常（状态指示器为绿色）
4. 确认数据正常更新

- [ ] **Step 3: 测试历史数据视图**

1. 点击"历史数据"按钮切换视图
2. 确认日期选择器显示
3. 选择一个日期
4. 确认历史数据正常加载
5. 确认图表正常更新

- [ ] **Step 4: 测试数据同步功能**

1. 在历史数据视图中，点击"同步数据"按钮
2. 确认同步请求成功
3. 确认同步后数据正常刷新

- [ ] **Step 5: 测试视图切换**

1. 在实时数据和历史数据视图之间多次切换
2. 确认没有数据覆盖问题
3. 确认WebSocket推送不会影响历史数据视图

- [ ] **Step 6: Commit（如果需要修复）**

如果测试中发现问题，修复后提交：
```bash
git add -A
git commit -m "[2026-04-24][FIX] 修复集成测试中发现的问题"
```

---

## 成功标准

1. ✅ 历史数据API调用不再与WebSocket推送冲突
2. ✅ 前端实时数据和历史数据视图切换正常
3. ✅ 所有现有功能保持不变
4. ✅ 代码通过基本测试

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 旧URL被外部调用 | 可考虑保留旧URL做重定向 |
| 前端缓存问题 | 清除浏览器缓存后测试 |
| 路由冲突 | 测试所有URL路径确保无冲突 |
