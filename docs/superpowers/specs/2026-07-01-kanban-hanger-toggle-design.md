# 产量看板"吊挂线"开关

## 概述

在产量看板添加"吊挂线"开关，控制是否排除 HIDDEN_FLOWS 中配置的隐藏分组。

## 行为

- **默认关闭**：应用 HIDDEN_FLOWS 排除规则（使用 VISIBLE_FLOWS）
- **打开**：不排除，显示全部分组（使用 ALLOWED_FLOWS）
- **切换不自动查询**：用户需点击"查询"按钮触发

## 改动范围

### 1. 后端 — queries.py / local_queries.py

产量看板 3 个函数新增 `show_all_flows` 参数：

- `get_kanban_stats`
- `get_kanban_ranking`  
- `get_kanban_filter_options`

内部将 `Flow__in=settings.ALLOWED_FLOWS` 替换为：

```python
flows_filter = settings.ALLOWED_FLOWS if show_all_flows else settings.VISIBLE_FLOWS
```

### 2. 后端 — api_views.py

3 个 API 解析 `show_all_flows` 查询参数（bool，默认 false），传给对应查询函数。

### 3. 前端 — kanban.html

- 清空按钮右侧添加 toggle 开关（slider 样式）
- 标签"吊挂线"
- 新增 `showAllFlows` ref，默认 `false`
- 3 个 fetch 函数参数中追加 `show_all_flows`

### 4. 接口参数

```
GET /api/kanban/stats/?date=...&stepno=...&show_all_flows=true
GET /api/kanban/ranking/?date=...&stepno=...&show_all_flows=true
GET /api/kanban/filter-options/?date=...&stepno=...&show_all_flows=true
```
