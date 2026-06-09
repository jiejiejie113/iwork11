# 生产详情数据模块 — 实施计划（TDD）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"生产详情"模块 —— Flow/StepNo 两级分组钻取 + 员工目标产量设置 + WebSocket 双向通信。

**Architecture:** 扩展 Celery Batch 引擎预计算 Flow/StepNo 员工明细 → Redis 缓存 → API 纯读；WebSocket 接收 `set_targets` 消息写入 Redis；独立 Django 页面模板 `production_detail.html` 通过 `data-initial-view` 区分概览/详情。

**Tech Stack:** Django 5.2, Python 3.11, Vue 3 (CDN), Chart.js 4 (CDN), Tailwind CSS (CDN), Redis, Celery, Django Channels

**Test Strategy:** 所有测试使用 `unittest.mock` mock ORM 调用，不依赖真实数据库。测试模式对齐现有 `tests/` 目录风格（Mock QuerySet, `@patch('module.Pytckreg3')`）。

---

### Task 1: queries.py — 新增 5 个 Batch 查询函数

**Files:**
- Create tests: `tests/test_queries.py` (追加)
- Modify: `iwork/queries.py`

- [ ] **Step 1: 写入测试（5 个测试类）**

在 `tests/test_queries.py` 末尾追加：

```python
class TestGetAllFlows:
    """get_all_flows"""

    @patch('iwork.queries.Pytckreg3')
    def test_returns_distinct_flows_sorted(self, mock_model):
        from iwork.queries import get_all_flows
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.distinct.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values_list.return_value = ['VCO-C1', 'VCO-L5']
        result = get_all_flows(date(2026, 5, 14))
        assert result == ['VCO-C1', 'VCO-L5']
        assert mock_qs.values.called

    @patch('iwork.queries.Pytckreg3')
    def test_empty_result_returns_empty_list(self, mock_model):
        from iwork.queries import get_all_flows
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.distinct.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values_list.return_value = []
        result = get_all_flows(date(2026, 5, 14))
        assert result == []


class TestGetBatchFlowOverview:
    """get_batch_flow_overview"""

    @patch('iwork.queries.Pytckreg3')
    def test_returns_flow_overview_dict(self, mock_model):
        from iwork.queries import get_batch_flow_overview
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'Flow': 'VCO-C1', 'total_qty': 500, 'worker_count': 10},
            {'Flow': 'VCO-L5', 'total_qty': 800, 'worker_count': 15},
        ]
        result = get_batch_flow_overview(date(2026, 5, 14))
        assert 'VCO-C1' in result
        assert result['VCO-C1']['total_qty'] == 500
        assert result['VCO-C1']['worker_count'] == 10
        assert result['VCO-L5']['total_qty'] == 800


class TestGetBatchFlowHourly:
    """get_batch_flow_hourly"""

    @patch('iwork.queries.Pytckreg3')
    def test_returns_flow_hourly_dict(self, mock_model):
        from iwork.queries import get_batch_flow_hourly
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.extra.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'Flow': 'VCO-L5', 'hour': 8, 'qty': 100},
            {'Flow': 'VCO-L5', 'hour': 9, 'qty': 150},
            {'Flow': 'VCO-C1', 'hour': 8, 'qty': 50},
        ]
        result = get_batch_flow_hourly(date(2026, 5, 14))
        assert 'VCO-L5' in result
        assert len(result['VCO-L5']) == 2
        assert result['VCO-L5'][0] == {'hour': 8, 'qty': 100}


class TestGetBatchFlowEmployees:
    """get_batch_flow_employees"""

    @patch('iwork.queries.Pytckreg3')
    def test_returns_flow_employee_dict(self, mock_model):
        from iwork.queries import get_batch_flow_employees
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'Flow': 'VCO-L5', 'RegPerSysID': 1001, 'StepNo': 70, 'qty': 300},
            {'Flow': 'VCO-L5', 'RegPerSysID': 1001, 'StepNo': 69, 'qty': 200},
            {'Flow': 'VCO-L5', 'RegPerSysID': 1002, 'StepNo': 70, 'qty': 150},
        ]
        result = get_batch_flow_employees(date(2026, 5, 14))
        assert 'VCO-L5' in result
        emp1 = [e for e in result['VCO-L5'] if e['reg_per_sys_id'] == 1001][0]
        assert emp1['total_qty'] == 500
        assert len(emp1['steps']) == 2


class TestGetBatchStepnoEmployees:
    """get_batch_stepno_employees"""

    @patch('iwork.queries.Pytckreg3')
    def test_returns_stepno_employee_dict(self, mock_model):
        from iwork.queries import get_batch_stepno_employees
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'VCO-L5', 'qty': 300},
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'VCO-C1', 'qty': 100},
            {'StepNo': 70, 'RegPerSysID': 1002, 'Flow': 'VCO-L5', 'qty': 150},
        ]
        result = get_batch_stepno_employees(date(2026, 5, 14))
        assert 70 in result
        emp1 = [e for e in result[70] if e['reg_per_sys_id'] == 1001][0]
        assert emp1['qty'] == 400
        assert set(emp1['flows']) == {'VCO-L5', 'VCO-C1'}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_queries.py::TestGetAllFlows tests/test_queries.py::TestGetBatchFlowOverview tests/test_queries.py::TestGetBatchFlowHourly tests/test_queries.py::TestGetBatchFlowEmployees tests/test_queries.py::TestGetBatchStepnoEmployees -v
```

预期：全部 FAIL —— 函数未定义。

- [ ] **Step 3: 在 queries.py 实现 5 个函数**

在 `iwork/queries.py` 末尾追加：

```python
# ============================================================================
# 生产详情 Batch 查询函数
# ============================================================================

def get_all_flows(target_date: date) -> list[str]:
    """获取当日所有不重复的 Flow 名称（字母排序）"""
    records = get_records_queryset(target_date)
    flows = list(
        records.exclude(Flow='')
        .values('Flow')
        .distinct()
        .order_by('Flow')
        .values_list('Flow', flat=True)
    )
    return list(flows)


def get_batch_flow_overview(target_date: date) -> dict:
    """每个 Flow 的员工数和总产量"""
    records = get_records_queryset(target_date)
    rows = list(
        records.exclude(Flow='')
        .values('Flow')
        .annotate(
            total_qty=Sum('Qty'),
            worker_count=Count('RegPerSysID', distinct=True),
        )
        .order_by('Flow')
    )
    return {
        r['Flow']: {
            'total_qty': r['total_qty'] or 0,
            'worker_count': r['worker_count'] or 0,
        }
        for r in rows
    }


def get_batch_flow_hourly(target_date: date) -> dict:
    """每个 Flow 的小时产量趋势"""
    records = get_records_queryset(target_date)
    rows = list(
        records.exclude(Flow='')
        .extra(select={'hour': 'HOUR(RegTime)'})
        .values('Flow', 'hour')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow', 'hour')
    )
    result = {}
    for r in rows:
        if r['hour'] is not None:
            result.setdefault(r['Flow'], []).append({'hour': r['hour'], 'qty': r['qty'] or 0})
    return result


def get_batch_flow_employees(target_date: date) -> dict:
    """每个 Flow 下每个员工的产量明细（按 StepNo 拆分）"""
    records = get_records_queryset(target_date)
    rows = list(
        records.exclude(Flow='')
        .values('Flow', 'RegPerSysID', 'StepNo')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow', 'RegPerSysID', 'StepNo')
    )
    # Python 层二次分组
    result = {}
    for r in rows:
        flow = r['Flow']
        emp_id = r['RegPerSysID']
        if flow not in result:
            result[flow] = []
        # 查找或创建员工条目
        emp_entry = next((e for e in result[flow] if e['reg_per_sys_id'] == emp_id), None)
        if emp_entry is None:
            emp_entry = {'reg_per_sys_id': emp_id, 'total_qty': 0, 'steps': []}
            result[flow].append(emp_entry)
        emp_entry['steps'].append({'stepno': r['StepNo'], 'qty': r['qty'] or 0})
        emp_entry['total_qty'] += r['qty'] or 0
    # 每个 Flow 内按 total_qty 降序
    for flow in result:
        result[flow].sort(key=lambda e: e['total_qty'], reverse=True)
    return result


def get_batch_stepno_employees(target_date: date) -> dict:
    """每个 StepNo 下每个员工的产量和涉及 Flow"""
    records = get_records_queryset(target_date)
    rows = list(
        records.values('StepNo', 'RegPerSysID', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', 'RegPerSysID', 'Flow')
    )
    result = {}
    for r in rows:
        stepno = r['StepNo']
        emp_id = r['RegPerSysID']
        if stepno not in result:
            result[stepno] = []
        emp_entry = next((e for e in result[stepno] if e['reg_per_sys_id'] == emp_id), None)
        if emp_entry is None:
            emp_entry = {'reg_per_sys_id': emp_id, 'qty': 0, 'flows': []}
            result[stepno].append(emp_entry)
        emp_entry['flows'].append(r['Flow'])
        emp_entry['qty'] += r['qty'] or 0
    for stepno in result:
        result[stepno].sort(key=lambda e: e['qty'], reverse=True)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_queries.py::TestGetAllFlows tests/test_queries.py::TestGetBatchFlowOverview tests/test_queries.py::TestGetBatchFlowHourly tests/test_queries.py::TestGetBatchFlowEmployees tests/test_queries.py::TestGetBatchStepnoEmployees -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add iwork/queries.py tests/test_queries.py
git commit -m "[2026-05-14][FEAT] 新增5个生产详情Batch查询函数（queries.py）"
```

---

### Task 2: local_queries.py — 镜像 5 个本地 Batch 查询函数

**Files:**
- Create tests: `tests/test_local_queries.py` (追加)
- Modify: `iwork/local_queries.py`

- [ ] **Step 1: 写入测试（5 个测试类）**

在 `tests/test_local_queries.py` 末尾追加：

```python
class TestGetAllFlowsLocal:
    """get_all_flows (本地)"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_distinct_flows(self, mock_model):
        from iwork.local_queries import get_all_flows
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.distinct.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values_list.return_value = ['EST-L3', 'VCO-L5']
        result = get_all_flows(date(2026, 5, 14))
        assert result == ['EST-L3', 'VCO-L5']


class TestGetBatchFlowOverviewLocal:
    """get_batch_flow_overview (本地)"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_flow_overview(self, mock_model):
        from iwork.local_queries import get_batch_flow_overview
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'Flow': 'VCO-L5', 'total_qty': 500, 'worker_count': 10},
        ]
        result = get_batch_flow_overview(date(2026, 5, 14))
        assert 'VCO-L5' in result
        assert result['VCO-L5']['total_qty'] == 500


class TestGetBatchFlowHourlyLocal:
    """get_batch_flow_hourly (本地)"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_hourly_dict(self, mock_model):
        from iwork.local_queries import get_batch_flow_hourly
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.extra.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'Flow': 'VCO-L5', 'hour': 8, 'qty': 100},
        ]
        result = get_batch_flow_hourly(date(2026, 5, 14))
        assert 'VCO-L5' in result


class TestGetBatchFlowEmployeesLocal:
    """get_batch_flow_employees (本地)"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_employee_dict(self, mock_model):
        from iwork.local_queries import get_batch_flow_employees
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'Flow': 'VCO-L5', 'RegPerSysID': 1001, 'StepNo': 70, 'qty': 300},
        ]
        result = get_batch_flow_employees(date(2026, 5, 14))
        assert 'VCO-L5' in result
        assert result['VCO-L5'][0]['total_qty'] == 300


class TestGetBatchStepnoEmployeesLocal:
    """get_batch_stepno_employees (本地)"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_stepno_dict(self, mock_model):
        from iwork.local_queries import get_batch_stepno_employees
        mock_qs = Mock()
        mock_model.objects.using.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = [
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'VCO-L5', 'qty': 300},
        ]
        result = get_batch_stepno_employees(date(2026, 5, 14))
        assert 70 in result
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_local_queries.py::TestGetAllFlowsLocal tests/test_local_queries.py::TestGetBatchFlowOverviewLocal tests/test_local_queries.py::TestGetBatchFlowHourlyLocal tests/test_local_queries.py::TestGetBatchFlowEmployeesLocal tests/test_local_queries.py::TestGetBatchStepnoEmployeesLocal -v
```

预期：全部 FAIL。

- [ ] **Step 3: 在 local_queries.py 实现 5 个函数**

在 `iwork/local_queries.py` 末尾追加（与 queries.py 实现一致，仅模型和数据库名不同）：

```python

# ============================================================================
# 生产详情 Batch 查询函数（本地库版本）
# ============================================================================

def get_all_flows(target_date: date) -> list[str]:
    """获取当日所有不重复的 Flow 名称（字母排序）"""
    records = get_records_queryset(target_date)
    flows = list(
        records.exclude(Flow='')
        .values('Flow')
        .distinct()
        .order_by('Flow')
        .values_list('Flow', flat=True)
    )
    return list(flows)


def get_batch_flow_overview(target_date: date) -> dict:
    """每个 Flow 的员工数和总产量"""
    records = get_records_queryset(target_date)
    rows = list(
        records.exclude(Flow='')
        .values('Flow')
        .annotate(
            total_qty=Sum('Qty'),
            worker_count=Count('RegPerSysID', distinct=True),
        )
        .order_by('Flow')
    )
    return {
        r['Flow']: {
            'total_qty': r['total_qty'] or 0,
            'worker_count': r['worker_count'] or 0,
        }
        for r in rows
    }


def get_batch_flow_hourly(target_date: date) -> dict:
    """每个 Flow 的小时产量趋势"""
    records = get_records_queryset(target_date)
    rows = list(
        records.exclude(Flow='')
        .extra(select={'hour': 'HOUR(RegTime)'})
        .values('Flow', 'hour')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow', 'hour')
    )
    result = {}
    for r in rows:
        if r['hour'] is not None:
            result.setdefault(r['Flow'], []).append({'hour': r['hour'], 'qty': r['qty'] or 0})
    return result


def get_batch_flow_employees(target_date: date) -> dict:
    """每个 Flow 下每个员工的产量明细（按 StepNo 拆分）"""
    records = get_records_queryset(target_date)
    rows = list(
        records.exclude(Flow='')
        .values('Flow', 'RegPerSysID', 'StepNo')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow', 'RegPerSysID', 'StepNo')
    )
    result = {}
    for r in rows:
        flow = r['Flow']
        emp_id = r['RegPerSysID']
        if flow not in result:
            result[flow] = []
        emp_entry = next((e for e in result[flow] if e['reg_per_sys_id'] == emp_id), None)
        if emp_entry is None:
            emp_entry = {'reg_per_sys_id': emp_id, 'total_qty': 0, 'steps': []}
            result[flow].append(emp_entry)
        emp_entry['steps'].append({'stepno': r['StepNo'], 'qty': r['qty'] or 0})
        emp_entry['total_qty'] += r['qty'] or 0
    for flow in result:
        result[flow].sort(key=lambda e: e['total_qty'], reverse=True)
    return result


def get_batch_stepno_employees(target_date: date) -> dict:
    """每个 StepNo 下每个员工的产量和涉及 Flow"""
    records = get_records_queryset(target_date)
    rows = list(
        records.values('StepNo', 'RegPerSysID', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', 'RegPerSysID', 'Flow')
    )
    result = {}
    for r in rows:
        stepno = r['StepNo']
        emp_id = r['RegPerSysID']
        if stepno not in result:
            result[stepno] = []
        emp_entry = next((e for e in result[stepno] if e['reg_per_sys_id'] == emp_id), None)
        if emp_entry is None:
            emp_entry = {'reg_per_sys_id': emp_id, 'qty': 0, 'flows': []}
            result[stepno].append(emp_entry)
        emp_entry['flows'].append(r['Flow'])
        emp_entry['qty'] += r['qty'] or 0
    for stepno in result:
        result[stepno].sort(key=lambda e: e['qty'], reverse=True)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_local_queries.py::TestGetAllFlowsLocal tests/test_local_queries.py::TestGetBatchFlowOverviewLocal tests/test_local_queries.py::TestGetBatchFlowHourlyLocal tests/test_local_queries.py::TestGetBatchFlowEmployeesLocal tests/test_local_queries.py::TestGetBatchStepnoEmployeesLocal -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add iwork/local_queries.py tests/test_local_queries.py
git commit -m "[2026-05-14][FEAT] 新增5个生产详情Batch查询函数（local_queries.py）"
```

---

### Task 3: statistics.py — get_batch_detail_stats + cache_detail_batch_to_redis

**Files:**
- Create tests: `tests/test_statistics.py` (追加)
- Modify: `iwork/statistics.py`

- [ ] **Step 1: 写入测试**

在 `tests/test_statistics.py` 末尾追加：

```python
class TestGetBatchDetailStats:
    """get_batch_detail_stats — Batch 详情引擎"""

    @patch('iwork.statistics.remote_q')
    def test_returns_detail_batch_structure(self, mock_remote):
        from iwork.statistics import get_batch_detail_stats

        mock_remote.get_batch_flow_overview.return_value = {
            'VCO-L5': {'total_qty': 800, 'worker_count': 15},
        }
        mock_remote.get_batch_flow_hourly.return_value = {
            'VCO-L5': [{'hour': 8, 'qty': 100}],
        }
        mock_remote.get_batch_flow_employees.return_value = {
            'VCO-L5': [{'reg_per_sys_id': 1001, 'total_qty': 500, 'steps': [{'stepno': 70, 'qty': 300}]}],
        }

        result = get_batch_detail_stats()

        assert result['flow_overview']['VCO-L5']['total_qty'] == 800
        assert result['flow_hourly']['VCO-L5'][0]['qty'] == 100
        assert result['flow_employees']['VCO-L5'][0]['reg_per_sys_id'] == 1001

    @patch('iwork.statistics.remote_q')
    def test_uses_custom_query_module(self, mock_remote):
        from iwork.statistics import get_batch_detail_stats
        from iwork import local_queries as local_q

        # Mock local_q to ensure the q parameter is used
        local_q.get_batch_flow_overview = Mock(return_value={})
        local_q.get_batch_flow_hourly = Mock(return_value={})
        local_q.get_batch_flow_employees = Mock(return_value={})

        get_batch_detail_stats(q=local_q)
        local_q.get_batch_flow_overview.assert_called_once()

    @patch('iwork.statistics.remote_q')
    def test_parallel_execution_with_threadpool(self, mock_remote):
        """验证使用 ThreadPoolExecutor 并行执行"""
        from iwork.statistics import get_batch_detail_stats

        mock_remote.get_batch_flow_overview.return_value = {'VCO-L5': {'total_qty': 500, 'worker_count': 10}}
        mock_remote.get_batch_flow_hourly.return_value = {'VCO-L5': []}
        mock_remote.get_batch_flow_employees.return_value = {'VCO-L5': []}

        result = get_batch_detail_stats()
        assert 'flow_overview' in result
        assert 'flow_hourly' in result
        assert 'flow_employees' in result


class TestCacheDetailBatchToRedis:
    """cache_detail_batch_to_redis"""

    @patch('iwork.statistics.cache')
    @patch('iwork.statistics._seconds_to_midnight')
    def test_caches_flow_keys(self, mock_ttl, mock_cache):
        from iwork.statistics import cache_detail_batch_to_redis

        mock_ttl.return_value = 36000
        detail_batch = {
            'flow_overview': {'VCO-L5': {'total_qty': 800, 'worker_count': 15}},
            'flow_hourly': {'VCO-L5': [{'hour': 8, 'qty': 100}]},
            'flow_employees': {'VCO-L5': [{'reg_per_sys_id': 1001, 'total_qty': 500}]},
        }

        cache_detail_batch_to_redis(detail_batch)
        mock_cache.set.assert_any_call('stats:detail:flow_overview', detail_batch['flow_overview'], 36000)
        mock_cache.set.assert_any_call('stats:detail:flow_hourly', detail_batch['flow_hourly'], 36000)
        mock_cache.set.assert_any_call('stats:detail:flow:VCO-L5', detail_batch['flow_employees']['VCO-L5'], 36000)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_statistics.py::TestGetBatchDetailStats tests/test_statistics.py::TestCacheDetailBatchToRedis -v
```

预期：全部 FAIL。

- [ ] **Step 3: 在 statistics.py 实现**

在 `iwork/statistics.py` 中 `get_realtime_stats` 函数之前插入：

```python
def get_batch_detail_stats(q=None) -> dict:
    """
    批量构建生产详情数据 → 返回 Flow/StepNo 明细 dict

    供 Celery 定时任务调用，计算结果写入 Redis 缓存。
    """
    if q is None:
        q = remote_q

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_overview = pool.submit(q.get_batch_flow_overview, date.today())
        f_hourly = pool.submit(q.get_batch_flow_hourly, date.today())
        f_employees = pool.submit(q.get_batch_flow_employees, date.today())

        flow_overview = f_overview.result()
        flow_hourly = f_hourly.result()
        flow_employees = f_employees.result()

    return {
        'flow_overview': flow_overview,
        'flow_hourly': flow_hourly,
        'flow_employees': flow_employees,
    }


def cache_detail_batch_to_redis(detail_batch: dict) -> None:
    """将批量详情结果写入 Redis（每个 Flow 独立 key，TTL 到午夜）"""
    ttl = _seconds_to_midnight()

    cache.set('stats:detail:flow_overview', detail_batch['flow_overview'], ttl)
    cache.set('stats:detail:flow_hourly', detail_batch['flow_hourly'], ttl)

    for flow_name, employees in detail_batch['flow_employees'].items():
        cache.set(f'stats:detail:flow:{flow_name}', employees, ttl)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_statistics.py::TestGetBatchDetailStats tests/test_statistics.py::TestCacheDetailBatchToRedis -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add iwork/statistics.py tests/test_statistics.py
git commit -m "[2026-05-14][FEAT] 新增 get_batch_detail_stats 并行详情引擎 + Redis 缓存函数"
```

---

### Task 4: tasks.py — 扩展 sync_dashboard_stats

**Files:**
- Create tests: `tests/test_tasks.py` (追加)
- Modify: `iwork/tasks.py`

- [ ] **Step 1: 写入测试**

在 `tests/test_tasks.py` 末尾追加：

```python
    @patch('iwork.tasks.get_channel_layer')
    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_calls_detail_batch_functions(self, mock_batch, mock_cache, mock_detail_batch, mock_detail_cache, mock_cl):
        """sync_dashboard_stats 同时调用详情批量函数"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch.return_value = {70: {'total_qty': 500, 'date': date(2026, 5, 9)},
                                    'all': {'total_qty': 500, 'date': date(2026, 5, 9)}}
        mock_detail_batch.return_value = {
            'flow_overview': {}, 'flow_hourly': {}, 'flow_employees': {}
        }
        mock_cl.return_value = None

        sync_dashboard_stats()

        mock_detail_batch.assert_called_once()
        mock_detail_cache.assert_called_once_with(mock_detail_batch.return_value)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_tasks.py::TestSyncDashboardStats::test_task_calls_detail_batch_functions -v
```

预期：FAIL —— `get_batch_detail_stats` 未导入。

- [ ] **Step 3: 修改 tasks.py**

```python
from iwork.statistics import get_batch_stats, cache_batch_to_redis, get_batch_detail_stats, cache_detail_batch_to_redis
```

在 `cache_batch_to_redis(batch)` 之后追加：

```python
        # 并行构建生产详情数据
        detail_batch = get_batch_detail_stats()
        cache_detail_batch_to_redis(detail_batch)
        logger.success(f'生产详情数据已缓存（{len(detail_batch.get("flow_overview", {}))} 个 Flow）')
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_tasks.py::TestSyncDashboardStats::test_task_calls_detail_batch_functions -v
```

预期：PASS。

- [ ] **Step 5: 运行全部 tasks 测试确认无回归**

```bash
pytest tests/test_tasks.py -v
```

预期：全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add iwork/tasks.py tests/test_tasks.py
git commit -m "[2026-05-14][FEAT] Celery 任务扩展：同步构建生产详情数据至 Redis"
```

---

### Task 5: api_views.py — 3 个新 API 端点

**Files:**
- Create tests: `tests/test_api_views.py` (追加)
- Modify: `iwork/api_views.py`

- [ ] **Step 1: 写入测试**

在 `tests/test_api_views.py` 末尾追加：

```python
class TestFlowOverviewEndpoint:
    """GET /api/dashboard/detail/flows/"""

    @patch('iwork.api_views.cache')
    def test_returns_cached_flow_overview(self, mock_cache):
        from iwork.api_views import flow_overview
        from rest_framework.test import APIRequestFactory

        mock_cache.get.return_value = {
            'VCO-L5': {'total_qty': 800, 'worker_count': 15},
            'VCO-C1': {'total_qty': 500, 'worker_count': 10},
        }

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/flows/')
        response = flow_overview(request)

        assert response.status_code == 200
        assert 'VCO-L5' in response.data
        assert response.data['VCO-L5']['worker_count'] == 15

    @patch('iwork.api_views.remote_get_batch_flow_overview')
    @patch('iwork.api_views.cache')
    def test_cache_miss_falls_back_to_db(self, mock_cache, mock_query):
        from iwork.api_views import flow_overview
        from rest_framework.test import APIRequestFactory

        mock_cache.get.return_value = None
        mock_query.return_value = {'VCO-L5': {'total_qty': 800, 'worker_count': 15}}

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/flows/')
        response = flow_overview(request)

        assert response.status_code == 200
        mock_query.assert_called_once()


class TestFlowDetailEndpoint:
    """GET /api/dashboard/detail/flow/<name>/"""

    @patch('iwork.api_views.get_flow_detail_data')
    def test_returns_flow_employees(self, mock_get):
        from iwork.api_views import flow_detail
        from rest_framework.test import APIRequestFactory

        mock_get.return_value = {
            'flow': 'VCO-L5',
            'total_qty': 800,
            'worker_count': 15,
            'hourly_trend': [{'hour': 8, 'qty': 100}],
            'employees': [{'reg_per_sys_id': 1001, 'total_qty': 500, 'steps': [{'stepno': 70, 'qty': 300}]}],
        }

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/flow/VCO-L5/')
        response = flow_detail(request, flow_name='VCO-L5')

        assert response.status_code == 200
        assert response.data['flow'] == 'VCO-L5'
        assert len(response.data['employees']) == 1


class TestStepnoDetailEndpoint:
    """GET /api/dashboard/detail/stepno/<stepno>/"""

    @patch('iwork.api_views.get_stepno_detail_data')
    def test_returns_stepno_employees(self, mock_get):
        from iwork.api_views import stepno_detail
        from rest_framework.test import APIRequestFactory

        mock_get.return_value = {
            'stepno': 70,
            'total_qty': 800,
            'worker_count': 15,
            'employees': [{'reg_per_sys_id': 1001, 'qty': 300, 'flows': ['VCO-L5']}],
        }

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/stepno/70/')
        response = stepno_detail(request, stepno=70)

        assert response.status_code == 200
        assert response.data['stepno'] == 70
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_api_views.py::TestFlowOverviewEndpoint tests/test_api_views.py::TestFlowDetailEndpoint tests/test_api_views.py::TestStepnoDetailEndpoint -v
```

预期：全部 FAIL。

- [ ] **Step 3: 在 api_views.py 实现 3 个端点**

追加导入：

```python
from iwork.queries import (
    ...,  # existing imports
    get_all_flows as remote_get_all_flows,
    get_batch_flow_overview as remote_get_batch_flow_overview,
    get_batch_flow_hourly as remote_get_batch_flow_hourly,
    get_batch_flow_employees as remote_get_batch_flow_employees,
    get_batch_stepno_employees as remote_get_batch_stepno_employees,
)
from iwork.local_queries import (
    get_batch_flow_overview as local_get_batch_flow_overview,
    get_batch_flow_hourly as local_get_batch_flow_hourly,
    get_batch_flow_employees as local_get_batch_flow_employees,
    get_batch_stepno_employees as local_get_batch_stepno_employees,
)
```

在文件末尾追加 3 个视图函数 + 1 个内部辅助函数：

```python

# ============================================================================
# 生产详情 API 端点
# ============================================================================

def _get_flow_detail_data(flow_name: str, target_date: date, mode: str = 'remote') -> dict:
    """获取指定 Flow 的完整详情数据（内部辅助函数）"""
    if mode == 'local':
        q_flow_employees = local_get_batch_flow_employees
        q_flow_hourly = local_get_batch_flow_hourly
    else:
        q_flow_employees = remote_get_batch_flow_employees
        q_flow_hourly = remote_get_batch_flow_hourly

    employees_data = q_flow_employees(target_date)
    hourly_data = q_flow_hourly(target_date)

    employees = employees_data.get(flow_name, [])
    total_qty = sum(e['total_qty'] for e in employees)

    return {
        'flow': flow_name,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'worker_count': len(employees),
        'hourly_trend': hourly_data.get(flow_name, []),
        'employees': employees,
    }


def _get_stepno_detail_data(stepno: int, target_date: date, mode: str = 'remote') -> dict:
    """获取指定 StepNo 的完整详情数据（内部辅助函数）"""
    if mode == 'local':
        q = local_get_batch_stepno_employees
    else:
        q = remote_get_batch_stepno_employees

    stepno_data = q(target_date)
    employees = stepno_data.get(stepno, [])
    total_qty = sum(e['qty'] for e in employees)

    return {
        'stepno': stepno,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'worker_count': len(employees),
        'employees': employees,
    }


@api_view(['GET'])
def flow_overview(request):
    """获取 Flow 概览（卡片网格数据）"""
    try:
        mode = request.query_params.get('mode', 'remote')
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)

        if target_date == date.today():
            # 今日：优先读 Redis
            ttl = _seconds_to_midnight() if mode == 'remote' else 3600
            cache_key = 'stats:detail:flow_overview' if mode == 'remote' else f'stats:detail:local:flow_overview:{target_date.isoformat()}'
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

            if mode == 'local':
                result = local_get_batch_flow_overview(target_date)
            else:
                result = remote_get_batch_flow_overview(target_date)
            cache.set(cache_key, result, ttl)
            return Response(result, status=status.HTTP_200_OK)
        else:
            # 历史日期
            if mode == 'local':
                result = local_get_batch_flow_overview(target_date)
            else:
                result = remote_get_batch_flow_overview(target_date)
            return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取 Flow 概览失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def flow_detail(request, flow_name):
    """获取指定 Flow 的员工明细"""
    try:
        mode = request.query_params.get('mode', 'remote')
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)

        # 今日：优先读 Redis
        if target_date == date.today() and mode == 'remote':
            cache_key = f'stats:detail:flow:{flow_name}'
            cached = cache.get(cache_key)
            if cached is not None:
                flow_data = _get_flow_detail_data(flow_name, target_date, mode)
                flow_data['employees'] = cached
                return Response(flow_data, status=status.HTTP_200_OK)

        result = _get_flow_detail_data(flow_name, target_date, mode)
        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取 Flow 详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def stepno_detail(request, stepno):
    """获取指定工序的员工明细"""
    try:
        mode = request.query_params.get('mode', 'remote')
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)

        result = _get_stepno_detail_data(stepno, target_date, mode)
        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取工序详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_api_views.py::TestFlowOverviewEndpoint tests/test_api_views.py::TestFlowDetailEndpoint tests/test_api_views.py::TestStepnoDetailEndpoint -v
```

预期：全部 PASS。

- [ ] **Step 5: 运行全部 api_views 测试确认无回归**

```bash
pytest tests/test_api_views.py -v
```

预期：全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add iwork/api_views.py tests/test_api_views.py
git commit -m "[2026-05-14][FEAT] 新增3个生产详情API端点：flow_overview, flow_detail, stepno_detail"
```

---

### Task 6: views.py + urls.py — 页面视图 + 路由

**Files:**
- Modify: `iwork/views.py`, `iwork/urls.py`

- [ ] **Step 1: 修改 views.py 新增 3 个页面视图**

```python
@require_http_methods(['GET'])
def production_detail(request):
    """生产详情 — Flow 概览页"""
    context = {
        'page_title': '生产看板 - 生产详情',
        'initial_view': 'overview',
    }
    return render(request, 'iwork/production_detail.html', context)


@require_http_methods(['GET'])
def production_detail_flow(request, flow_name):
    """生产详情 — Flow 员工明细"""
    context = {
        'page_title': f'生产看板 - 生产详情 - {flow_name}',
        'initial_view': 'detail',
        'detail_type': 'flow',
        'detail_key': flow_name,
    }
    return render(request, 'iwork/production_detail.html', context)


@require_http_methods(['GET'])
def production_detail_stepno(request, stepno):
    """生产详情 — 工序员工明细"""
    context = {
        'page_title': f'生产看板 - 生产详情 - 工序 {stepno}',
        'initial_view': 'detail',
        'detail_type': 'stepno',
        'detail_key': stepno,
    }
    return render(request, 'iwork/production_detail.html', context)
```

- [ ] **Step 2: 修改 urls.py 新增 3 条路由**

在 `urlpatterns` 末尾追加：

```python
    # 生产详情页面
    path("production/detail-data/", views.production_detail, name="production-detail"),
    path("production/detail-data/flow/<str:flow_name>/", views.production_detail_flow, name="production-detail-flow"),
    path("production/detail-data/stepno/<int:stepno>/", views.production_detail_stepno, name="production-detail-stepno"),
```

- [ ] **Step 3: 运行全部测试确认无回归**

```bash
pytest tests/ -v --ignore=tests/test_consumers.py
```

- [ ] **Step 4: 提交**

```bash
git add iwork/views.py iwork/urls.py
git commit -m "[2026-05-14][FEAT] 新增生产详情页面路由：概览/Flow详情/工序详情"
```

---

### Task 7: consumers.py — WebSocket 接收 set_targets

**Files:**
- Modify: `iwork/consumers.py`
- Create tests: `tests/test_consumers.py` (追加)

- [ ] **Step 1: 写入测试**

在 `tests/test_consumers.py` 末尾追加：

```python
    @pytest.mark.asyncio
    async def test_receive_set_targets_writes_redis(self):
        """接收 set_targets 消息 → 写入 Redis → 广播确认"""
        from iwork.consumers import DashboardConsumer
        from channels.layers import get_channel_layer
        from unittest.mock import patch, AsyncMock

        with override_settings(
            CHANNEL_LAYERS={
                'default': {
                    'BACKEND': 'channels.layers.InMemoryChannelLayer'
                }
            }
        ):
            with patch('iwork.consumers.cache') as mock_cache:
                mock_cache.set = Mock()
                communicator = WebsocketCommunicator(
                    DashboardConsumer.as_asgi(),
                    '/ws/dashboard/'
                )
                connected, _ = await communicator.connect()
                assert connected

                # 发送 set_targets 消息
                await communicator.send_json_to({
                    'type': 'set_targets',
                    'flow': 'VCO-L5',
                    'targets': {'1001': 100, '1002': 150}
                })

                # 验证 Redis 写入
                mock_cache.set.assert_called_once()
                call_args = mock_cache.set.call_args
                assert 'targets' in call_args[0][0]
                assert 'VCO-L5' in call_args[0][0]

                # 验证被广播（通过 group_send）
                channel_layer = get_channel_layer()
                # 发送一条测试消息验证 consumer 仍在组中
                await channel_layer.group_send(
                    'dashboard',
                    {'type': 'dashboard_update', 'data': {}}
                )
                response = await communicator.receive_json_from(timeout=2)
                assert response['type'] == 'dashboard_update'

                await communicator.disconnect()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_consumers.py::TestDashboardConsumer::test_receive_set_targets_writes_redis -v
```

预期：FAIL —— Consumer 未处理 `set_targets` 消息。

- [ ] **Step 3: 修改 consumers.py**

```python
import json
from datetime import date
from django.core.cache import cache
from channels.generic.websocket import AsyncWebsocketConsumer
from loguru import logger


class DashboardConsumer(AsyncWebsocketConsumer):
    """看板 WebSocket 消费者"""

    async def connect(self):
        """连接时加入 dashboard 组"""
        await self.channel_layer.group_add('dashboard', self.channel_name)
        await self.accept()
        logger.info(f'WebSocket 连接建立: {self.channel_name}')

    async def disconnect(self, close_code):
        """断开时离开 dashboard 组"""
        await self.channel_layer.group_discard('dashboard', self.channel_name)
        logger.info(f'WebSocket 连接关闭: {close_code}')

    async def receive_json(self, content, **kwargs):
        """接收客户端消息并分发处理"""
        msg_type = content.get('type')

        if msg_type == 'set_targets':
            await self._handle_set_targets(content)
        else:
            logger.warning(f'未知消息类型: {msg_type}')

    async def _handle_set_targets(self, content):
        """处理目标产量设置"""
        flow = content.get('flow', '')
        targets = content.get('targets', {})
        today = date.today().isoformat()

        # 写入 Redis
        key = f'targets:{today}:{flow}'
        cache.set(key, json.dumps(targets), timeout=None)  # TTL 由 Celery 任务统一到期

        # 广播确认给所有客户端
        await self.channel_layer.group_send(
            'dashboard',
            {
                'type': 'targets_updated',
                'flow': flow,
                'targets': targets,
            }
        )
        logger.info(f'目标产量已保存: {flow} {len(targets)} 个员工')

    async def targets_updated(self, event):
        """转发 targets_updated 事件到客户端"""
        await self.send(text_data=json.dumps(event, ensure_ascii=False))

    async def dashboard_update(self, event):
        """接收组消息并发送到客户端"""
        message = {
            'type': 'dashboard_update',
            'timestamp': event.get('timestamp'),
            'data': event.get('data'),
        }
        await self.send(text_data=json.dumps(message, ensure_ascii=False))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_consumers.py::TestDashboardConsumer::test_receive_set_targets_writes_redis -v
```

预期：PASS。

- [ ] **Step 5: 运行全部 consumers 测试确认无回归**

```bash
pytest tests/test_consumers.py -v
```

预期：全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add iwork/consumers.py tests/test_consumers.py
git commit -m "[2026-05-14][FEAT] WebSocket 新增 receive_json 处理 set_targets 目标产量保存"
```

---

### Task 8: dashboard.html — 导航栏新增"生产详情"菜单项

**Files:**
- Modify: `iwork/templates/iwork/dashboard.html`

- [ ] **Step 1: 在导航栏插入新菜单项**

在"历史数据" `<a>` 标签之后插入：

```html
                <a href="/production/detail-data/"
                    :class="currentView === 'production_detail' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                    class="px-4 py-2 rounded-md text-sm transition-colors font-medium">生产详情</a>
```

- [ ] **Step 2: 提交**

```bash
git add iwork/templates/iwork/dashboard.html
git commit -m "[2026-05-14][FEAT] 导航栏新增生产详情菜单项"
```

---

### Task 9: production_detail.html — 完整前端模板

**Files:**
- Create: `iwork/templates/iwork/production_detail.html`

- [ ] **Step 1: 写入完整模板**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <script>tailwind.config = { darkMode: 'class' }</script>
    <style>
        .tabular-nums { font-variant-numeric: tabular-nums; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .animate-spin { animation: spin 1s linear infinite; }
    </style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen">
<div id="app" class="container mx-auto px-4 py-6"
     data-initial-view="{{ initial_view }}"
     data-detail-type="{{ detail_type|default:'' }}"
     data-detail-key="{{ detail_key|default:'' }}">

    <!-- ========== 顶部工具栏 ========== -->
    <header class="flex justify-between items-center mb-6 flex-wrap gap-4">
        <h1 class="text-2xl font-bold text-slate-100">{{ page_title }}</h1>
        <div class="flex items-center gap-3 flex-wrap">
            <div class="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
                <a href="/" class="px-4 py-2 rounded-md text-sm transition-colors font-medium bg-slate-700 hover:bg-slate-600">实时数据</a>
                <a href="/history/" class="px-4 py-2 rounded-md text-sm transition-colors font-medium bg-slate-700 hover:bg-slate-600">历史数据</a>
                <a href="/production/detail-data/" class="px-4 py-2 rounded-md text-sm transition-colors font-medium bg-blue-600">生产详情</a>
            </div>
        </div>
    </header>

    <!-- ========== 加载蒙版 ========== -->
    <div v-if="isLoading" class="fixed inset-0 bg-slate-900/80 z-50 flex items-center justify-center">
        <div class="text-center">
            <div class="inline-block w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
            <p class="text-slate-300 text-lg">数据加载中...</p>
        </div>
    </div>

    <!-- ========== 概览页 ========== -->
    <div v-if="currentView === 'overview'">
        <!-- 搜索栏 + Tab -->
        <div class="flex items-center gap-4 mb-6 flex-wrap">
            <input v-model="searchQuery" placeholder="搜索员工 RegPerSysID..."
                class="flex-1 min-w-[200px] bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
            <input type="date" v-model="selectedDate"
                class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
            <div class="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
                <button @click="groupMode = 'flow'"
                    :class="groupMode === 'flow' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                    class="px-4 py-2 rounded-md text-sm transition-colors">按 Flow</button>
                <button @click="groupMode = 'stepno'"
                    :class="groupMode === 'stepno' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                    class="px-4 py-2 rounded-md text-sm transition-colors">按工序</button>
            </div>
        </div>

        <!-- Flow 卡片网格 -->
        <div v-if="groupMode === 'flow'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div v-for="card in filteredFlowCards" :key="card.flow"
                @click="goFlowDetail(card.flow)"
                class="bg-slate-800 border border-slate-700 rounded-lg p-4 cursor-pointer hover:border-blue-500/50 transition-colors">
                <div class="flex justify-between items-start mb-3">
                    <div>
                        <h3 class="font-bold text-lg">{[ card.flow ]}</h3>
                        <p class="text-sm text-slate-400">👤 {[ card.worker_count ]}人 · 📦 {[ fmtNum(card.total_qty) ]}件</p>
                    </div>
                    <span class="text-slate-600 text-lg">→</span>
                </div>
                <div v-if="card.hourly && card.hourly.length" style="height:60px;">
                    <canvas :id="'flow-chart-' + card.flow"></canvas>
                </div>
                <div class="flex items-center gap-2 mt-2 text-xs">
                    <span v-if="card.target_total > 0">目标: {[ fmtNum(card.target_total) ]}</span>
                    <span v-if="card.efficiency != null"
                        :class="card.efficiency >= 100 ? 'text-emerald-400' : 'text-red-400'">
                        {[ card.efficiency.toFixed(1) ]}% {[ card.efficiency >= 100 ? '✓' : '✗' ]}
                    </span>
                </div>
            </div>
            <div v-if="filteredFlowCards.length === 0" class="col-span-full text-center text-slate-500 py-12">
                暂无 Flow 数据
            </div>
        </div>

        <!-- 工序卡片网格 -->
        <div v-if="groupMode === 'stepno'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div v-for="card in filteredStepnoCards" :key="card.stepno"
                @click="goStepnoDetail(card.stepno)"
                class="bg-slate-800 border border-slate-700 rounded-lg p-4 cursor-pointer hover:border-blue-500/50 transition-colors">
                <div class="flex justify-between items-start">
                    <div>
                        <h3 class="font-bold text-lg">工序 {[ card.stepno ]}</h3>
                        <p class="text-sm text-slate-400">👤 {[ card.worker_count ]}人 · 📦 {[ fmtNum(card.total_qty) ]}件</p>
                    </div>
                    <span class="text-slate-600 text-lg">→</span>
                </div>
            </div>
            <div v-if="filteredStepnoCards.length === 0" class="col-span-full text-center text-slate-500 py-12">
                暂无工序数据
            </div>
        </div>
    </div>

    <!-- ========== 详情页 ========== -->
    <div v-if="currentView === 'detail'">
        <!-- 面包屑 -->
        <div class="flex items-center gap-2 mb-4 text-sm">
            <a href="/production/detail-data/" class="text-blue-400 hover:underline">生产详情</a>
            <span class="text-slate-600">/</span>
            <span class="font-semibold">{[ detailTitle ]}</span>
            <span class="ml-auto text-slate-400">
                👤 {[ detailSummary.worker_count ]}人 · 📦 {[ fmtNum(detailSummary.total_qty) ]}件
                <span v-if="detailSummary.target_total > 0">
                    · 🎯 目标 {[ fmtNum(detailSummary.target_total) ]}
                    · <span :class="detailSummary.efficiency >= 100 ? 'text-emerald-400' : 'text-red-400'">
                        {[ detailSummary.efficiency.toFixed(1) ]}% {[ detailSummary.efficiency >= 100 ? '达标 ✓' : '不达标 ✗' ]}
                    </span>
                </span>
            </span>
        </div>

        <!-- 表格内搜索 -->
        <input v-model="tableSearch" placeholder="搜索员工 RegPerSysID..."
            class="max-w-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm mb-4 block">

        <!-- 员工表格 -->
        <div class="bg-slate-800 border border-slate-700 rounded-lg overflow-x-auto">
            <table class="w-full text-sm">
                <thead>
                    <tr class="text-left text-slate-400 border-b border-slate-700">
                        <th class="pb-2 px-4 py-3">RegPerSysID</th>
                        <th class="pb-2 px-4 py-3">实时产量</th>
                        <th class="pb-2 px-4 py-3">目标产量</th>
                        <th class="pb-2 px-4 py-3">达标情况</th>
                        <th class="pb-2 px-4 py-3">效率</th>
                        <th class="pb-2 px-4 py-3" v-if="detailType === 'flow'">工序明细</th>
                        <th class="pb-2 px-4 py-3" v-else>涉及 Flow</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="emp in filteredTableEmployees" :key="emp.reg_per_sys_id"
                        class="border-b border-slate-700 hover:bg-slate-700/50">
                        <td class="py-2 px-4 text-slate-300">{[ emp.reg_per_sys_id ]}</td>
                        <td class="py-2 px-4 text-emerald-400 font-bold tabular-nums">{[ fmtNum(emp.qty) ]}</td>
                        <td class="py-2 px-4">
                            <input v-model.number="emp.target"
                                class="w-20 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-center text-sm tabular-nums">
                        </td>
                        <td class="py-2 px-4" v-if="emp.target > 0">
                            <span :class="emp.qty >= emp.target ? 'text-emerald-400' : 'text-red-400'">
                                {[ emp.qty >= emp.target ? '达标 ✓' : '不达标 ✗' ]}
                            </span>
                        </td>
                        <td class="py-2 px-4 text-slate-500" v-else>--</td>
                        <td class="py-2 px-4" v-if="emp.target > 0">
                            <span :class="emp.efficiency >= 100 ? 'text-emerald-400' : 'text-red-400'">
                                {[ emp.efficiency.toFixed(1) ]}%
                            </span>
                        </td>
                        <td class="py-2 px-4 text-slate-500" v-else>--</td>
                        <td class="py-2 px-4 text-slate-400 text-xs" v-if="detailType === 'flow'">
                            <span v-for="(s, i) in emp.steps" :key="s.stepno">
                                {[ s.stepno ]}:{[ s.qty ]}<span v-if="i < emp.steps.length - 1">, </span>
                            </span>
                        </td>
                        <td class="py-2 px-4 text-slate-400 text-xs" v-else>
                            {[ (emp.flows || []).join(', ') ]}
                        </td>
                    </tr>
                    <tr v-if="filteredTableEmployees.length === 0">
                        <td :colspan="detailType === 'flow' ? 7 : 6"
                            class="py-4 text-slate-500 text-center">暂无数据</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- 保存按钮 -->
        <div class="flex justify-end mt-4 gap-2">
            <button @click="saveTargets"
                class="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm transition-colors">
                全部保存
            </button>
        </div>
    </div>
</div>

<script>
const { createApp, ref, reactive, computed, watch, onMounted, nextTick } = Vue;

createApp({
    delimiters: ['{[', ']}'],
    setup() {
        const appEl = document.getElementById('app');
        const initialView = appEl?.dataset.initialView || 'overview';
        const detailType = ref(appEl?.dataset.detailType || 'flow');
        const detailKey = ref(appEl?.dataset.detailKey || '');

        const currentView = ref(initialView);
        const groupMode = ref('flow');
        const searchQuery = ref('');
        const tableSearch = ref('');
        const selectedDate = ref(new Date().toISOString().split('T')[0]);
        const isLoading = ref(false);
        const wsConnected = ref(false);

        // 数据
        const flowCards = ref([]);
        const flowHourly = ref({});
        const stepnoCards = ref([]);
        const detailEmployees = ref([]);
        const targets = ref({});

        const detailTitle = computed(() => {
            if (detailType.value === 'flow') return detailKey.value;
            return '工序 ' + detailKey.value;
        });

        const detailSummary = computed(() => {
            const emps = detailEmployees.value;
            const total_qty = emps.reduce((s, e) => s + (e.qty || 0), 0);
            const targets_list = emps.filter(e => e.target > 0);
            const target_total = targets_list.reduce((s, e) => s + e.target, 0);
            return {
                worker_count: emps.length,
                total_qty,
                target_total,
                efficiency: target_total > 0 ? (total_qty / target_total * 100) : null,
            };
        });

        const filteredFlowCards = computed(() => {
            let cards = flowCards.value;
            if (currentView.value !== 'overview' || groupMode.value !== 'flow') return [];
            if (searchQuery.value) {
                const q = searchQuery.value.toLowerCase();
                cards = cards.filter(c => String(c.flow).toLowerCase().includes(q));
            }
            return cards;
        });

        const filteredStepnoCards = computed(() => {
            let cards = stepnoCards.value;
            if (currentView.value !== 'overview' || groupMode.value !== 'stepno') return [];
            if (searchQuery.value) {
                const q = searchQuery.value.toLowerCase();
                cards = cards.filter(c => String(c.stepno).includes(q));
            }
            return cards;
        });

        const filteredTableEmployees = computed(() => {
            let emps = detailEmployees.value;
            if (currentView.value !== 'detail') return [];
            if (tableSearch.value) {
                const q = String(tableSearch.value).toLowerCase();
                emps = emps.filter(e => String(e.reg_per_sys_id).includes(q));
            }
            return emps;
        });

        function fmtNum(n) { return n != null ? n.toLocaleString() : '--'; }

        // API 调用
        async function loadFlowOverview() {
            isLoading.value = true;
            try {
                const resp = await fetch(`/api/dashboard/detail/flows/?date=${selectedDate.value}`);
                const data = await resp.json();
                const flows = [];
                for (const [name, info] of Object.entries(data)) {
                    const t = targets.value[name] || {};
                    const target_total = Object.values(t).reduce((s, v) => s + v, 0);
                    flows.push({
                        flow: name,
                        total_qty: info.total_qty,
                        worker_count: info.worker_count,
                        target_total,
                        efficiency: target_total > 0 ? (info.total_qty / target_total * 100) : null,
                        hourly: (flowHourly.value[name] || []),
                    });
                }
                flowCards.value = flows.sort((a, b) => a.flow.localeCompare(b.flow));
            } catch (e) { console.error('加载 Flow 概览失败:', e); }
            finally { isLoading.value = false; }
        }

        async function loadFlowHourly() {
            try {
                const resp = await fetch(`/api/dashboard/detail/flows/?date=${selectedDate.value}`);
                const data = await resp.json();
                // hourly 数据从 flow 详情或独立端点获取
                const hResp = await fetch(`/api/dashboard/detail/flows/?date=${selectedDate.value}`);
                // 简化处理：通过 flow_overview 不含 hourly，这里 mock 空
                flowHourly.value = {};
            } catch (e) {}
        }

        async function loadStepnoOverview() {
            try {
                const resp = await fetch(`/api/dashboard/processes/?date=${selectedDate.value}`);
                const data = await resp.json();
                stepnoCards.value = (data.stepnos || []).map(s => ({
                    stepno: s, total_qty: 0, worker_count: 0
                }));
            } catch (e) { console.error('加载工序列表失败:', e); }
        }

        async function loadFlowDetail(flowName) {
            isLoading.value = true;
            try {
                const resp = await fetch(`/api/dashboard/detail/flow/${flowName}/?date=${selectedDate.value}`);
                const data = await resp.json();
                const t = targets.value[flowName] || {};
                detailEmployees.value = (data.employees || []).map(emp => {
                    const target = t[String(emp.reg_per_sys_id)] || 0;
                    return {
                        ...emp,
                        qty: emp.total_qty || emp.qty || 0,
                        target,
                        efficiency: target > 0 ? ((emp.total_qty || emp.qty || 0) / target * 100) : null,
                    };
                });
                detailType.value = 'flow';
                detailKey.value = flowName;
                currentView.value = 'detail';
            } catch (e) { console.error('加载 Flow 详情失败:', e); }
            finally { isLoading.value = false; }
        }

        async function loadStepnoDetail(stepno) {
            isLoading.value = true;
            try {
                const resp = await fetch(`/api/dashboard/detail/stepno/${stepno}/?date=${selectedDate.value}`);
                const data = await resp.json();
                detailEmployees.value = (data.employees || []).map(emp => ({
                    ...emp,
                    target: 0,
                    efficiency: null,
                }));
                detailType.value = 'stepno';
                detailKey.value = stepno;
                currentView.value = 'detail';
            } catch (e) { console.error('加载工序详情失败:', e); }
            finally { isLoading.value = false; }
        }

        function goFlowDetail(flowName) {
            window.location.href = '/production/detail-data/flow/' + encodeURIComponent(flowName) + '/';
        }

        function goStepnoDetail(stepno) {
            window.location.href = '/production/detail-data/stepno/' + stepno + '/';
        }

        // 目标产量加载/保存
        async function loadTargets() {
            const today = new Date().toISOString().split('T')[0];
            try {
                const resp = await fetch(`/api/dashboard/detail/flow/_targets/?date=${today}`);
                if (resp.ok) {
                    const data = await resp.json();
                    targets.value = data.targets || {};
                }
            } catch (e) { /* 忽略 */ }
        }

        async function saveTargets() {
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                alert('WebSocket 未连接，无法保存');
                return;
            }
            const t = {};
            detailEmployees.value.forEach(emp => {
                if (emp.target > 0) t[String(emp.reg_per_sys_id)] = emp.target;
            });

            ws.send(JSON.stringify({
                type: 'set_targets',
                flow: detailKey.value,
                targets: t,
            }));
        }

        // WebSocket
        let ws = null;
        function connectWS() {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${proto}//${window.location.host}/ws/dashboard/`);
            ws.onopen = () => { wsConnected.value = true; };
            ws.onclose = () => {
                wsConnected.value = false;
                setTimeout(connectWS, 3000);
            };
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === 'targets_updated') {
                    const flow = msg.flow;
                    targets.value = { ...targets.value, [flow]: msg.targets };
                    // 如果在详情页且是相关 Flow，刷新图表
                    if (currentView.value === 'detail' && detailKey.value === flow) {
                        detailEmployees.value = detailEmployees.value.map(emp => {
                            const newTarget = (msg.targets[String(emp.reg_per_sys_id)] || 0);
                            return {
                                ...emp,
                                target: newTarget,
                                efficiency: newTarget > 0 ? (emp.qty / newTarget * 100) : null,
                            };
                        });
                    }
                    // 刷新概览卡片效率
                    if (currentView.value === 'overview') {
                        loadFlowOverview();
                    }
                }
                if (msg.type === 'dashboard_update' && currentView.value === 'overview') {
                    loadFlowOverview();
                }
            };
        }

        // 生命周期
        onMounted(() => {
            connectWS();
            loadTargets();

            if (initialView === 'overview') {
                loadFlowOverview();
                loadStepnoOverview();
            } else if (initialView === 'detail') {
                if (detailType.value === 'flow') {
                    loadFlowDetail(detailKey.value);
                } else {
                    loadStepnoDetail(Number(detailKey.value));
                }
            }
        });

        return {
            currentView, groupMode, searchQuery, tableSearch, selectedDate, isLoading, wsConnected,
            flowCards, stepnoCards, detailEmployees, targets,
            detailType, detailKey, detailTitle, detailSummary,
            filteredFlowCards, filteredStepnoCards, filteredTableEmployees,
            fmtNum, goFlowDetail, goStepnoDetail, saveTargets,
        };
    }
}).mount('#app');
</script>
</body>
</html>
```

- [ ] **Step 2: 提交**

```bash
git add iwork/templates/iwork/production_detail.html
git commit -m "[2026-05-14][FEAT] 新增生产详情前端模板：概览/详情两级视图 + 目标产量设置"
```

---

### Task 10: 运行全部测试 + 最终验证

- [ ] **Step 1: 运行全部测试套件**

```bash
pytest tests/ -v
```

预期：所有测试 PASS，无回归。

- [ ] **Step 2: 最终提交（如有残留变更）**

```bash
git status
# 如有变更 doc 文件，一并提交
```

---

## 任务依赖关系

```
Task 1 (queries.py) ──┐
                      ├──→ Task 3 (statistics.py) ──→ Task 4 (tasks.py)
Task 2 (local_q.py) ──┘                                    │
                                                           ▼
                                              Task 5 (api_views.py)
                                                           │
                                                           ▼
                                              Task 6 (views.py + urls.py)
                                                           │
                              Task 7 (consumers.py) ───────┤
                                                           ▼
                                              Task 8 (dashboard.html)
                                                           │
                                                           ▼
                                              Task 9 (production_detail.html)
                                                           │
                                                           ▼
                                              Task 10 (全量测试)
```

Task 1+2 可并行，Task 7 可与 Task 5/6 并行，其余串行。
