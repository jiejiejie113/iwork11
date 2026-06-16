# 产量看板模块 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 iwork 项目中新增产量看板标签页，提供工人产量排行榜（分页）、统计卡片、产量分布柱状图，支持多维筛选（工序/款号/Flow多选/员工）+ 日期切换。

**Architecture:** 后端新增 3 个 DRF API 端点 → 3+1 个查询函数（queries.py + local_queries.py 镜像）→ 前端新增 1 个 Django 模板（Vue 3 + Tailwind CSS CDN），与现有 iwork 架构完全一致。

**Tech Stack:** Django 5.2, DRF 3.15, Vue 3 CDN, Tailwind CSS CDN, MySQL (iwork/iwork_local 双库)

**Spec:** `docs/superpowers/specs/2026-06-16-kanban-module-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `iwork/queries.py` | 修改 | 新增 4 个查询函数（远程库） |
| `iwork/local_queries.py` | 修改 | 镜像 4 个查询函数（本地库） |
| `iwork/api_views.py` | 修改 | 新增 3 个 API 视图 |
| `iwork/urls.py` | 修改 | 新增 4 条路由 |
| `iwork/views.py` | 修改 | 新增 kanban_page 视图 |
| `iwork/templates/iwork/kanban.html` | 新建 | 产量看板页面 |
| `iwork/templates/iwork/_header.html` | 修改 | 添加"产量看板"标签 |
| `iwork/settings.py` | 修改 | 添加看板配置项 |
| `tests/test_kanban_queries.py` | 新建 | 查询函数测试 |
| `tests/test_kanban_api.py` | 新建 | API 端点测试 |

---

### Task 1: 查询函数测试（TDD）

**Files:**
- Create: `tests/test_kanban_queries.py`

- [ ] **Step 1: 编写失败测试 — 验证函数签名和返回结构**

```python
"""
产量看板查询函数测试
"""
import pytest
from datetime import date
from django.test import TestCase
from iwork.queries import (
    get_kanban_stats,
    get_kanban_ranking,
    get_kanban_filter_options,
    _apply_kanban_filters,
    _merge_worker_rows,
)
from iwork.models import Pytckreg3


class TestApplyKanbanFilters(TestCase):
    """_apply_kanban_filters 单元测试"""

    def test_no_filters_returns_unchanged(self):
        """无筛选条件时返回原 QuerySet"""
        qs = Pytckreg3.objects.using('iwork').all()
        result = _apply_kanban_filters(qs)
        assert result.query == qs.query

    def test_stepno_filter_applied(self):
        """工序筛选正确添加 WHERE 条件"""
        qs = Pytckreg3.objects.using('iwork').all()
        result = _apply_kanban_filters(qs, stepno='70')
        sql = str(result.query)
        assert 'StepNo' in sql

    def test_wrk_order_filter_applied(self):
        """款号筛选正确添加 WHERE 条件"""
        qs = Pytckreg3.objects.using('iwork').all()
        result = _apply_kanban_filters(qs, wrk_order='SO3-001')
        sql = str(result.query)
        assert 'WrkOrder' in sql

    def test_flows_filter_applied(self):
        """分组多选筛选正确添加 WHERE IN 条件"""
        qs = Pytckreg3.objects.using('iwork').all()
        result = _apply_kanban_filters(qs, flows=['SO3', 'SO5'])
        sql = str(result.query)
        assert 'Flow' in sql

    def test_reg_per_sys_id_filter_applied(self):
        """员工筛选正确添加 WHERE 条件"""
        qs = Pytckreg3.objects.using('iwork').all()
        result = _apply_kanban_filters(qs, reg_per_sys_id='12345')
        sql = str(result.query)
        assert 'RegPerSysID' in sql

    def test_all_filters_combined(self):
        """组合筛选全部生效"""
        qs = Pytckreg3.objects.using('iwork').all()
        result = _apply_kanban_filters(
            qs, stepno='70', wrk_order='SO3-001',
            flows=['SO3'], reg_per_sys_id='12345'
        )
        sql = str(result.query)
        assert all(k in sql for k in ['StepNo', 'WrkOrder', 'Flow', 'RegPerSysID'])


class TestMergeWorkerRows(TestCase):
    """_merge_worker_rows 单元测试"""

    def test_single_worker_single_row(self):
        """单工人单条记录直接返回"""
        rows = [{'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W1', 'Flow': 'F1', 'qty': 100}]
        result = _merge_worker_rows(rows)
        assert len(result) == 1
        assert result[0]['reg_per_sys_id'] == 'A'
        assert result[0]['production'] == 100
        assert result[0]['stepno'] == '70'
        assert result[0]['wrk_order'] == 'W1'
        assert result[0]['flow'] == 'F1'

    def test_single_worker_multiple_rows_merged(self):
        """同一工人多条记录合并为一条，产量求和"""
        rows = [
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W1', 'Flow': 'F1', 'qty': 100},
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W2', 'Flow': 'F2', 'qty': 50},
        ]
        result = _merge_worker_rows(rows)
        assert len(result) == 1
        assert result[0]['production'] == 150
        # 取产量最大的那条的主字段
        assert result[0]['wrk_order'] == 'W1'
        assert result[0]['flow'] == 'F1'

    def test_multiple_workers_separated(self):
        """不同工人不合并"""
        rows = [
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W1', 'Flow': 'F1', 'qty': 100},
            {'RegPerSysID': 'B', 'StepNo': '70', 'WrkOrder': 'W2', 'Flow': 'F2', 'qty': 200},
        ]
        result = _merge_worker_rows(rows)
        assert len(result) == 2

    def test_empty_rows_returns_empty(self):
        """空输入返回空列表"""
        assert _merge_worker_rows([]) == []


class TestKanbanStats(TestCase):
    """get_kanban_stats 集成测试（需要数据库有数据）"""

    def test_stats_returns_correct_structure(self):
        """返回值包含所有必需字段"""
        result = get_kanban_stats(date.today(), stepno='70')
        assert 'worker_count' in result
        assert 'total_production' in result
        assert 'avg_production' in result
        assert 'max_production' in result
        assert 'max_worker_name' in result
        assert isinstance(result['worker_count'], int)
        assert isinstance(result['total_production'], int)
        assert isinstance(result['avg_production'], int)
        assert isinstance(result['max_production'], int)
        assert isinstance(result['max_worker_name'], str)

    def test_stats_no_results_returns_zeros(self):
        """无匹配数据时返回零值"""
        # 使用不存在的筛选条件
        result = get_kanban_stats(date.today(), stepno='99999')
        assert result['worker_count'] == 0
        assert result['total_production'] == 0
        assert result['avg_production'] == 0
        assert result['max_production'] == 0
        assert result['max_worker_name'] == ''


class TestKanbanRanking(TestCase):
    """get_kanban_ranking 集成测试"""

    def test_ranking_returns_correct_structure(self):
        """返回值包含 pagination 和 workers"""
        result = get_kanban_ranking(date.today(), stepno='70', page=1, page_size=50)
        assert 'pagination' in result
        assert 'workers' in result
        pagination = result['pagination']
        assert 'page' in pagination
        assert 'page_size' in pagination
        assert 'total_pages' in pagination
        assert 'total_count' in pagination
        assert pagination['page'] == 1
        assert pagination['page_size'] == 50

    def test_ranking_workers_have_required_fields(self):
        """每个 worker 包含所有必需字段"""
        result = get_kanban_ranking(date.today(), stepno='70', page=1, page_size=10)
        if result['workers']:
            w = result['workers'][0]
            assert 'rank' in w
            assert 'reg_per_sys_id' in w
            assert 'worker_name' in w
            assert 'stepno' in w
            assert 'wrk_order' in w
            assert 'flow' in w
            assert 'production' in w
            assert w['rank'] >= 1

    def test_ranking_respects_page_size(self):
        """分页大小生效"""
        result = get_kanban_ranking(date.today(), stepno='70', page=1, page_size=5)
        assert len(result['workers']) <= 5

    def test_ranking_page_2_offset(self):
        """第二页数据与第一页不重复"""
        page1 = get_kanban_ranking(date.today(), stepno='70', page=1, page_size=10)
        page2 = get_kanban_ranking(date.today(), stepno='70', page=2, page_size=10)
        if page1['workers'] and page2['workers']:
            ids1 = {w['reg_per_sys_id'] for w in page1['workers']}
            ids2 = {w['reg_per_sys_id'] for w in page2['workers']}
            assert ids1.isdisjoint(ids2)

    def test_ranking_empty_result(self):
        """无数据时返回空列表"""
        result = get_kanban_ranking(date.today(), stepno='99999')
        assert result['workers'] == []
        assert result['pagination']['total_count'] == 0
        assert result['pagination']['total_pages'] == 1


class TestKanbanFilterOptions(TestCase):
    """get_kanban_filter_options 集成测试"""

    def test_filter_options_returns_required_keys(self):
        """返回值包含所有筛选项键"""
        result = get_kanban_filter_options(date.today())
        assert 'stepnos' in result
        assert 'wrk_orders' in result
        assert 'flows' in result
        assert 'employees' in result
        assert isinstance(result['stepnos'], list)
        assert isinstance(result['wrk_orders'], list)
        assert isinstance(result['flows'], list)
        assert isinstance(result['employees'], list)

    def test_employees_have_id_and_name(self):
        """员工列表包含 id 和 name"""
        result = get_kanban_filter_options(date.today())
        if result['employees']:
            emp = result['employees'][0]
            assert 'reg_per_sys_id' in emp
            assert 'name' in emp

    def test_flows_filter_cascades_employees(self):
        """传入 flow 参数时员工列表受限"""
        all_result = get_kanban_filter_options(date.today())
        if all_result['flows']:
            filtered = get_kanban_filter_options(
                date.today(), flows=[all_result['flows'][0]]
            )
            assert len(filtered['employees']) <= len(all_result['employees'])
```

- [ ] **Step 2: 运行测试确认全部失败**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/test_kanban_queries.py -v
```

预期：所有测试 FAIL（函数不存在）

- [ ] **Step 3: 提交**

```bash
git add tests/test_kanban_queries.py
git commit -m "[2026-06-16][TEST] 添加产量看板查询函数测试"
```

---

### Task 2: 实现查询函数（queries.py）

**Files:**
- Modify: `iwork/queries.py` — 在文件末尾追加

- [ ] **Step 1: 实现 `_apply_kanban_filters` 函数**

在 `iwork/queries.py` 末尾追加：

```python
# ============================================================================
# 产量看板模块查询函数
# ============================================================================

def _apply_kanban_filters(queryset, stepno=None, wrk_order=None,
                          flows=None, reg_per_sys_id=None):
    """产量看板通用筛选器（内部工具函数）

    对 QuerySet 依次应用工序、款号、分组、员工筛选。
    筛选逻辑：传入 None 或空值表示不过滤该维度。

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

- [ ] **Step 2: 实现 `_merge_worker_rows` 函数**

```python
def _merge_worker_rows(rows):
    """合并同一工人在不同 WrkOrder/Flow 下的记录

    输入来自 ORM 四级分组查询：
        [(RegPerSysID, StepNo, WrkOrder, Flow, qty), ...]
    输出按工人合并后的列表。

    合并逻辑：
        - production = SUM(所有 qty)
        - stepno/wrk_order/flow = 取 qty 最大的那条记录的值
        - worker_name = str(reg_per_sys_id)

    Args:
        rows (list[dict]): ORM values() 返回的行列表

    Returns:
        list[dict]: 合并后的工人列表
    """
    from collections import OrderedDict

    worker_map = OrderedDict()
    for r in rows:
        eid = r['RegPerSysID']
        qty = r['qty'] or 0
        if eid not in worker_map:
            worker_map[eid] = {
                'reg_per_sys_id': eid,
                'worker_name': str(eid),
                'production': 0,
                'best_qty': 0,
                'stepno': r['StepNo'],
                'wrk_order': r['WrkOrder'] or '',
                'flow': r['Flow'] or '',
            }
        entry = worker_map[eid]
        entry['production'] += qty
        # 取产量最大的那条记录的主字段
        if qty > entry['best_qty']:
            entry['best_qty'] = qty
            entry['stepno'] = r['StepNo']
            entry['wrk_order'] = r['WrkOrder'] or ''
            entry['flow'] = r['Flow'] or ''

    result = []
    for eid, entry in worker_map.items():
        result.append({
            'reg_per_sys_id': entry['reg_per_sys_id'],
            'worker_name': entry['worker_name'],
            'stepno': entry['stepno'],
            'wrk_order': entry['wrk_order'],
            'flow': entry['flow'],
            'production': entry['production'],
        })
    return result
```

- [ ] **Step 3: 实现 `get_kanban_stats` 函数**

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
    from django.db.models import Sum, Count, Max

    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepno, wrk_order, flows, reg_per_sys_id)

    # 按工人聚合产量
    worker_qs = records.values('RegPerSysID').annotate(production=Sum('Qty'))

    # 二次聚合
    agg = worker_qs.aggregate(
        worker_count=Count('RegPerSysID'),
        total_production=Sum('production'),
        max_production=Max('production'),
    )

    count = agg['worker_count'] or 0
    total = agg['total_production'] or 0
    max_qty = agg['max_production'] or 0

    # 找最高产工人
    max_worker = worker_qs.order_by('-production').first()
    max_name = str(max_worker['RegPerSysID']) if max_worker else ''

    return {
        'worker_count': count,
        'total_production': total,
        'avg_production': round(total / count) if count else 0,
        'max_production': max_qty,
        'max_worker_name': max_name,
    }
```

- [ ] **Step 4: 实现 `get_kanban_ranking` 函数**

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
    from django.db.models import Sum

    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepno, wrk_order, flows, reg_per_sys_id)

    # 四级分组：按工人+工序+款号+Flow
    rows = list(
        records.values('RegPerSysID', 'StepNo', 'WrkOrder', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )

    # Python 层合并同一工人多条记录
    workers = _merge_worker_rows(rows)
    # 按产量降序
    workers.sort(key=lambda x: x['production'], reverse=True)

    total = len(workers)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_data = workers[start:start + page_size]

    # 注入全局排名
    for i, w in enumerate(page_data):
        w['rank'] = start + i + 1

    return {
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_count': total,
        },
        'workers': page_data,
    }
```

- [ ] **Step 5: 实现 `get_kanban_filter_options` 函数**

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
    from django.db.models import Sum

    records = get_records_queryset(target_date)

    # 工序列表（按值升序）
    stepnos = list(
        records.values_list('StepNo', flat=True)
        .distinct()
        .order_by('StepNo')
    )

    # 款号列表（按值升序）
    wrk_orders = list(
        records.values_list('WrkOrder', flat=True)
        .distinct()
        .order_by('WrkOrder')
    )

    # 分组列表（非空，按值升序）
    all_flows = list(
        records.exclude(Flow='')
        .values_list('Flow', flat=True)
        .distinct()
        .order_by('Flow')
    )

    # 员工列表（按 RegPerSysID 聚合，若传入 flows 则先筛选）
    if flows:
        records = records.filter(Flow__in=flows)
    employee_qs = (
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )
    employees = [
        {'reg_per_sys_id': r['RegPerSysID'], 'name': str(r['RegPerSysID'])}
        for r in employee_qs
    ]

    return {
        'stepnos': stepnos,
        'wrk_orders': wrk_orders,
        'flows': all_flows,
        'employees': employees,
    }
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/test_kanban_queries.py -v
```

预期：所有测试 PASS

- [ ] **Step 7: 提交**

```bash
git add iwork/queries.py
git commit -m "[2026-06-16][FEAT] 添加产量看板查询函数（queries.py）"
```

---

### Task 3: 镜像查询函数到 local_queries.py

**Files:**
- Modify: `iwork/local_queries.py` — 在文件末尾追加相同函数

- [ ] **Step 1: 复制 4 个函数到 local_queries.py**

在 `iwork/local_queries.py` 末尾追加与 queries.py 完全相同的 4 个函数。唯一区别：`_merge_worker_rows` 中的 `from collections import OrderedDict` 已在本地导入。

```python
# ============================================================================
# 产量看板模块查询函数（本地库版本）
# ============================================================================

def _apply_kanban_filters(queryset, stepno=None, wrk_order=None,
                          flows=None, reg_per_sys_id=None):
    """产量看板通用筛选器（内部工具函数）"""
    if stepno:
        queryset = queryset.filter(StepNo=stepno)
    if wrk_order:
        queryset = queryset.filter(WrkOrder=wrk_order)
    if flows:
        queryset = queryset.filter(Flow__in=flows)
    if reg_per_sys_id:
        queryset = queryset.filter(RegPerSysID=reg_per_sys_id)
    return queryset


def _merge_worker_rows(rows):
    """合并同一工人在不同 WrkOrder/Flow 下的记录"""
    from collections import OrderedDict
    worker_map = OrderedDict()
    for r in rows:
        eid = r['RegPerSysID']
        qty = r['qty'] or 0
        if eid not in worker_map:
            worker_map[eid] = {
                'reg_per_sys_id': eid, 'worker_name': str(eid),
                'production': 0, 'best_qty': 0,
                'stepno': r['StepNo'], 'wrk_order': r['WrkOrder'] or '',
                'flow': r['Flow'] or '',
            }
        entry = worker_map[eid]
        entry['production'] += qty
        if qty > entry['best_qty']:
            entry['best_qty'] = qty
            entry['stepno'] = r['StepNo']
            entry['wrk_order'] = r['WrkOrder'] or ''
            entry['flow'] = r['Flow'] or ''
    result = []
    for eid, entry in worker_map.items():
        result.append({
            'reg_per_sys_id': entry['reg_per_sys_id'],
            'worker_name': entry['worker_name'],
            'stepno': entry['stepno'],
            'wrk_order': entry['wrk_order'],
            'flow': entry['flow'],
            'production': entry['production'],
        })
    return result


def get_kanban_stats(target_date, stepno=None, wrk_order=None,
                     flows=None, reg_per_sys_id=None):
    """产量看板统计汇总（本地库）"""
    from django.db.models import Sum, Count, Max
    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepno, wrk_order, flows, reg_per_sys_id)
    worker_qs = records.values('RegPerSysID').annotate(production=Sum('Qty'))
    agg = worker_qs.aggregate(
        worker_count=Count('RegPerSysID'),
        total_production=Sum('production'),
        max_production=Max('production'),
    )
    count = agg['worker_count'] or 0
    total = agg['total_production'] or 0
    max_qty = agg['max_production'] or 0
    max_worker = worker_qs.order_by('-production').first()
    max_name = str(max_worker['RegPerSysID']) if max_worker else ''
    return {
        'worker_count': count,
        'total_production': total,
        'avg_production': round(total / count) if count else 0,
        'max_production': max_qty,
        'max_worker_name': max_name,
    }


def get_kanban_ranking(target_date, stepno=None, wrk_order=None,
                       flows=None, reg_per_sys_id=None,
                       page=1, page_size=50):
    """产量看板排行榜（本地库）"""
    from django.db.models import Sum
    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepno, wrk_order, flows, reg_per_sys_id)
    rows = list(
        records.values('RegPerSysID', 'StepNo', 'WrkOrder', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )
    workers = _merge_worker_rows(rows)
    workers.sort(key=lambda x: x['production'], reverse=True)
    total = len(workers)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_data = workers[start:start + page_size]
    for i, w in enumerate(page_data):
        w['rank'] = start + i + 1
    return {
        'pagination': {
            'page': page, 'page_size': page_size,
            'total_pages': total_pages, 'total_count': total,
        },
        'workers': page_data,
    }


def get_kanban_filter_options(target_date, flows=None):
    """产量看板筛选项（本地库）"""
    from django.db.models import Sum
    records = get_records_queryset(target_date)
    stepnos = list(records.values_list('StepNo', flat=True).distinct().order_by('StepNo'))
    wrk_orders = list(records.values_list('WrkOrder', flat=True).distinct().order_by('WrkOrder'))
    all_flows = list(records.exclude(Flow='').values_list('Flow', flat=True).distinct().order_by('Flow'))
    if flows:
        records = records.filter(Flow__in=flows)
    employee_qs = (
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )
    employees = [
        {'reg_per_sys_id': r['RegPerSysID'], 'name': str(r['RegPerSysID'])}
        for r in employee_qs
    ]
    return {
        'stepnos': stepnos,
        'wrk_orders': wrk_orders,
        'flows': all_flows,
        'employees': employees,
    }
```

- [ ] **Step 2: 运行现有测试确认无回归**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/ -v -k "kanban" --timeout=30
```

- [ ] **Step 3: 提交**

```bash
git add iwork/local_queries.py
git commit -m "[2026-06-16][FEAT] 镜像产量看板查询函数到 local_queries.py"
```

---

### Task 4: API 端点测试（TDD）

**Files:**
- Create: `tests/test_kanban_api.py`

- [ ] **Step 1: 编写 API 测试**

```python
"""
产量看板 API 端点测试
"""
import pytest
from datetime import date
from django.test import TestCase, Client
from django.urls import reverse


class TestKanbanStatsAPI(TestCase):
    """GET /api/kanban/stats/"""

    def setUp(self):
        self.client = Client()

    def test_stats_returns_200(self):
        """正常请求返回 200"""
        response = self.client.get('/api/kanban/stats/', {
            'date': date.today().isoformat(),
            'stepno': '70',
        })
        assert response.status_code == 200
        data = response.json()
        assert 'worker_count' in data
        assert 'total_production' in data
        assert 'avg_production' in data
        assert 'max_production' in data
        assert 'max_worker_name' in data

    def test_stats_missing_date_returns_400(self):
        """缺少日期参数返回 400"""
        response = self.client.get('/api/kanban/stats/')
        assert response.status_code == 400

    def test_stats_invalid_date_returns_400(self):
        """非法日期格式返回 400"""
        response = self.client.get('/api/kanban/stats/', {
            'date': 'not-a-date',
        })
        assert response.status_code == 400

    def test_stats_no_stepno_uses_default(self):
        """不传 stepno 时使用默认值，正常返回"""
        response = self.client.get('/api/kanban/stats/', {
            'date': date.today().isoformat(),
        })
        assert response.status_code == 200


class TestKanbanRankingAPI(TestCase):
    """GET /api/kanban/ranking/"""

    def setUp(self):
        self.client = Client()

    def test_ranking_returns_200(self):
        """正常请求返回 200"""
        response = self.client.get('/api/kanban/ranking/', {
            'date': date.today().isoformat(),
            'stepno': '70',
            'page': 1,
            'page_size': 50,
        })
        assert response.status_code == 200
        data = response.json()
        assert 'pagination' in data
        assert 'workers' in data

    def test_ranking_default_page_size(self):
        """默认 page_size 为 50"""
        response = self.client.get('/api/kanban/ranking/', {
            'date': date.today().isoformat(),
            'stepno': '70',
        })
        assert response.status_code == 200
        assert response.json()['pagination']['page_size'] == 50

    def test_ranking_invalid_page_returns_empty(self):
        """越界页码返回空数据而非报错"""
        response = self.client.get('/api/kanban/ranking/', {
            'date': date.today().isoformat(),
            'stepno': '70',
            'page': 99999,
        })
        assert response.status_code == 200
        assert response.json()['workers'] == []


class TestKanbanFilterOptionsAPI(TestCase):
    """GET /api/kanban/filter-options/"""

    def setUp(self):
        self.client = Client()

    def test_filter_options_returns_200(self):
        """正常请求返回 200"""
        response = self.client.get('/api/kanban/filter-options/', {
            'date': date.today().isoformat(),
        })
        assert response.status_code == 200
        data = response.json()
        assert 'stepnos' in data
        assert 'wrk_orders' in data
        assert 'flows' in data
        assert 'employees' in data

    def test_filter_options_with_flows(self):
        """传入 flow 参数正常返回"""
        response = self.client.get('/api/kanban/filter-options/', {
            'date': date.today().isoformat(),
            'flow': ['SO3-L3A', 'SO5-L5B'],
        })
        assert response.status_code == 200
```

- [ ] **Step 2: 运行测试确认全部失败**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/test_kanban_api.py -v
```

预期：FAIL（路由/视图不存在）

- [ ] **Step 3: 提交**

```bash
git add tests/test_kanban_api.py
git commit -m "[2026-06-16][TEST] 添加产量看板 API 端点测试"
```

---

### Task 5: 实现 API 视图

**Files:**
- Modify: `iwork/api_views.py` — 在文件末尾追加

- [ ] **Step 1: 添加导入**

在 `iwork/api_views.py` 顶部现有 import 块中追加 kanban 查询函数的导入：

```python
from iwork.queries import (
    # ... 现有导入保持不变 ...
    get_kanban_stats as remote_get_kanban_stats,
    get_kanban_ranking as remote_get_kanban_ranking,
    get_kanban_filter_options as remote_get_kanban_filter_options,
)
from iwork.local_queries import (
    # ... 现有导入保持不变 ...
    get_kanban_stats as local_get_kanban_stats,
    get_kanban_ranking as local_get_kanban_ranking,
    get_kanban_filter_options as local_get_kanban_filter_options,
)
```

- [ ] **Step 2: 添加日期解析辅助函数**

```python
def _parse_kanban_date(request):
    """解析产量看板日期参数，返回 date 对象或错误 Response"""
    params = getattr(request, 'query_params', request.GET)
    date_str = params.get('date', '')
    if not date_str:
        return None, Response(
            {'error': '缺少日期参数，格式为 YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        from datetime import datetime as dt
        return dt.strptime(date_str, '%Y-%m-%d').date(), None
    except ValueError:
        return None, Response(
            {'error': '日期格式错误，需为 YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST
        )
```

- [ ] **Step 3: 实现 3 个 API 视图函数**

在 `iwork/api_views.py` 末尾追加：

```python
# ============================================================================
# 产量看板 API
# ============================================================================

@api_view(['GET'])
def kanban_stats(request):
    """产量看板统计汇总 API

    Query params:
        date (str): YYYY-MM-DD（必填）
        stepno (str): 工序号（选填，默认 '70'）
        wrk_order (str): 款号（选填，不传=全部）
        flow (str): 分组（选填，可多传）
        reg_per_sys_id (str): 员工（选填）
    """
    target_date, err = _parse_kanban_date(request)
    if err:
        return err

    params = request.query_params
    stepno = params.get('stepno', '70') or None
    wrk_order = params.get('wrk_order', '') or None
    flows = params.getlist('flow') or None
    reg_per_sys_id = params.get('reg_per_sys_id', '') or None

    try:
        stats = remote_get_kanban_stats(
            target_date, stepno=stepno, wrk_order=wrk_order,
            flows=flows, reg_per_sys_id=reg_per_sys_id,
        )
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/kanban/stats/ 失败: {}', e)
        return Response(
            {'error': '获取统计数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def kanban_ranking(request):
    """产量看板排行榜 API

    Query params:
        date (str): YYYY-MM-DD（必填）
        stepno (str): 工序号（选填，默认 '70'）
        wrk_order (str): 款号（选填）
        flow (str): 分组（选填，可多传）
        reg_per_sys_id (str): 员工（选填）
        page (int): 页码（选填，默认 1）
        page_size (int): 每页条数（选填，默认 50）
    """
    target_date, err = _parse_kanban_date(request)
    if err:
        return err

    params = request.query_params
    stepno = params.get('stepno', '70') or None
    wrk_order = params.get('wrk_order', '') or None
    flows = params.getlist('flow') or None
    reg_per_sys_id = params.get('reg_per_sys_id', '') or None

    try:
        page = int(params.get('page', 1))
        page_size = int(params.get('page_size', 50))
    except ValueError:
        return Response(
            {'error': 'page 和 page_size 需为整数'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        result = remote_get_kanban_ranking(
            target_date, stepno=stepno, wrk_order=wrk_order,
            flows=flows, reg_per_sys_id=reg_per_sys_id,
            page=page, page_size=page_size,
        )
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/kanban/ranking/ 失败: {}', e)
        return Response(
            {'error': '获取排行榜数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def kanban_filter_options(request):
    """产量看板筛选项 API

    Query params:
        date (str): YYYY-MM-DD（必填）
        flow (str): 分组（选填，多传时员工列表仅返回这些 Flow 下的员工）
    """
    target_date, err = _parse_kanban_date(request)
    if err:
        return err

    params = request.query_params
    flows = params.getlist('flow') or None

    try:
        options = remote_get_kanban_filter_options(target_date, flows=flows)
        return Response(options, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/kanban/filter-options/ 失败: {}', e)
        return Response(
            {'error': '获取筛选项失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/test_kanban_api.py -v
```

预期：所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add iwork/api_views.py
git commit -m "[2026-06-16][FEAT] 添加产量看板 API 视图（stats/ranking/filter-options）"
```

---

### Task 6: 添加 URL 路由 + 页面视图 + 配置

**Files:**
- Modify: `iwork/urls.py`
- Modify: `iwork/views.py`
- Modify: `iwork/settings.py`

- [ ] **Step 1: 在 settings.py 添加配置**

在 `iwork/settings.py` 业务配置区块末尾追加：

```python
# 产量看板默认配置
KANBAN_DEFAULT_STEPNO = '70'       # 默认工序筛选值
KANBAN_DEFAULT_PAGE_SIZE = 50      # 排行榜每页条数
```

- [ ] **Step 2: 在 views.py 添加页面视图**

在 `iwork/views.py` 末尾追加：

```python
@require_http_methods(['GET'])
def kanban_page(request):
    """产量看板页面"""
    context = {
        'page_title': 'Eastex生产看板 - 产量看板',
    }
    return render(request, 'iwork/kanban.html', context)
```

- [ ] **Step 3: 在 urls.py 添加路由**

在 `iwork/urls.py` 的 `urlpatterns` 末尾（`]` 之前）追加：

```python
    # 产量看板
    path("kanban/", views.kanban_page, name="kanban-page"),
    path("api/kanban/stats/", api_views.kanban_stats, name="kanban-stats"),
    path("api/kanban/ranking/", api_views.kanban_ranking, name="kanban-ranking"),
    path("api/kanban/filter-options/", api_views.kanban_filter_options, name="kanban-filter-options"),
```

- [ ] **Step 4: 运行测试确认路由生效**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/test_kanban_api.py -v
```

预期：全部 PASS（路由已存在，视图返回 200）

- [ ] **Step 5: 提交**

```bash
git add iwork/urls.py iwork/views.py iwork/settings.py
git commit -m "[2026-06-16][FEAT] 添加产量看板路由、页面视图和默认配置"
```

---

### Task 7: 更新头部标签页导航

**Files:**
- Modify: `iwork/templates/iwork/_header.html`

- [ ] **Step 1: 添加"产量看板"标签**

在 `_header.html` 的标签按钮组中，在"历史数据"之前插入：

```html
        <a :href="basePath + 'kanban/'"
            :class="currentView === 'kanban' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
            class="px-4 py-2 rounded-md text-sm transition-colors font-medium">产量看板</a>
```

完整修改后的标签组为：`实时数据 | 生产详情 | 产量看板 | 历史数据`

- [ ] **Step 2: 提交**

```bash
git add iwork/templates/iwork/_header.html
git commit -m "[2026-06-16][FEAT] 头部导航添加产量看板标签"
```

---

### Task 8: 创建产量看板页面模板

**Files:**
- Create: `iwork/templates/iwork/kanban.html`

- [ ] **Step 1: 创建完整模板**

模板结构：Django 模板继承 + Vue 3 CDN + Tailwind CDN + 内联 CSS/JS。

注意使用 `{[` `]}` 作为 Vue 分隔符（与现有 iwork 模板一致），`[[` `]]` 留给 Django 模板。

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eastex生产看板 - 产量看板</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {
    darkMode: 'class',
    theme: {
        extend: {
            fontSize: {
                '2xs': '0.65rem',
            }
        }
    }
}
</script>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>

<div id="kanbanApp" class="min-h-screen bg-slate-900 text-slate-100">
  <!-- 背景光晕 -->
  <div class="fixed top-[-30%] left-[-10%] w-[60%] h-[60%] pointer-events-none z-0"
       style="background: radial-gradient(ellipse, rgba(59,130,246,0.08) 0%, transparent 70%);"></div>

  <div class="relative z-10 max-w-[1320px] mx-auto px-7 py-10 pb-20">

    <!-- Header -->
    <div class="flex items-end gap-5 mb-11 pb-7 border-b border-slate-700">
      <div class="w-[52px] h-[52px] bg-blue-600 rounded-xl flex items-center justify-center flex-shrink-0 shadow-[0_0_30px_rgba(59,130,246,0.3)]">
        <svg class="w-7 h-7 fill-slate-900" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10h-4v4h-2v-4H7v-2h4V7h2v4h4v2z"/></svg>
      </div>
      <div>
        <h1 class="text-[28px] font-black tracking-wider leading-tight">
          流水线车间 · <span class="text-blue-400">产量看板</span>
        </h1>
      </div>
      <div class="ml-auto text-right font-mono text-xs text-slate-400 leading-relaxed">
        <div class="inline-flex items-center gap-1.5 text-emerald-400">
          <span class="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse"></span>实时数据
        </div>
        <div id="kanbanClock">{[ clock ]}</div>
      </div>
    </div>

    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4 mb-8 max-md:grid-cols-2 max-sm:grid-cols-1">
      <div class="bg-slate-800 border border-slate-700 rounded-lg p-5 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-blue-500 to-transparent"></div>
        <div class="text-xs text-slate-400 uppercase tracking-widest mb-2">在岗工人数</div>
        <div class="font-mono text-[28px] font-medium text-slate-100">{[ animatedStats.worker_count ]}</div>
      </div>
      <div class="bg-slate-800 border border-slate-700 rounded-lg p-5 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-blue-500 to-transparent"></div>
        <div class="text-xs text-slate-400 uppercase tracking-widest mb-2">总产量</div>
        <div class="font-mono text-[28px] font-medium text-slate-100">{[ animatedStats.total_production ]}<span class="text-sm text-slate-400 ml-1">件</span></div>
      </div>
      <div class="bg-slate-800 border border-slate-700 rounded-lg p-5 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-blue-500 to-transparent"></div>
        <div class="text-xs text-slate-400 uppercase tracking-widest mb-2">人均产量</div>
        <div class="font-mono text-[28px] font-medium text-slate-100">{[ animatedStats.avg_production ]}<span class="text-sm text-slate-400 ml-1">件</span></div>
      </div>
      <div class="bg-slate-800 border border-slate-700 rounded-lg p-5 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-blue-500 to-transparent"></div>
        <div class="text-xs text-slate-400 uppercase tracking-widest mb-2">最高产量</div>
        <div class="font-mono text-[28px] font-medium text-slate-100">{[ animatedStats.max_production ]}<span class="text-sm text-slate-400 ml-1">件</span></div>
        <div class="text-xs text-slate-400 mt-1">{[ stats.max_worker_name ? '最高: ' + stats.max_worker_name : '' ]}</div>
      </div>
    </div>

    <!-- Filters -->
    <div class="flex items-center gap-4 mb-7 flex-wrap max-md:flex-col max-md:items-stretch">
      <!-- 日期 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-2xs text-slate-400 uppercase tracking-widest font-medium">日期</label>
        <input type="date" v-model="date" @change="onFilterChange"
               class="bg-slate-700 border border-slate-600 text-slate-100 text-sm px-3.5 py-2.5 rounded-lg
                      focus:outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20 min-w-[160px]">
      </div>

      <!-- 工序 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-2xs text-slate-400 uppercase tracking-widest font-medium">工序筛选</label>
        <select v-model="filters.stepno" @change="onFilterChange"
                class="bg-slate-700 border border-slate-600 text-slate-100 text-sm px-3.5 py-2.5 rounded-lg
                       focus:outline-none focus:border-blue-500 min-w-[140px] appearance-none
                       bg-[url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22%3E%3Cpath d=%22M2 4l4 4 4-4%22 fill=%22none%22 stroke=%22%2394a3b8%22 stroke-width=%221.5%22 stroke-linecap=%22round%22/%3E%3C/svg%3E')] bg-[right_14px_center] bg-no-repeat pr-10">
          <option value="">全部工序</option>
          <option v-for="s in filterOptions.stepnos" :key="s" :value="s">{[ s ]}</option>
        </select>
      </div>

      <!-- 款号 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-2xs text-slate-400 uppercase tracking-widest font-medium">款号筛选</label>
        <select v-model="filters.wrk_order" @change="onFilterChange"
                class="bg-slate-700 border border-slate-600 text-slate-100 text-sm px-3.5 py-2.5 rounded-lg
                       focus:outline-none focus:border-blue-500 min-w-[160px] appearance-none
                       bg-[url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22%3E%3Cpath d=%22M2 4l4 4 4-4%22 fill=%22none%22 stroke=%22%2394a3b8%22 stroke-width=%221.5%22 stroke-linecap=%22round%22/%3E%3C/svg%3E')] bg-[right_14px_center] bg-no-repeat pr-10">
          <option value="">全部款号</option>
          <option v-for="w in filterOptions.wrk_orders" :key="w" :value="w">{[ w ]}</option>
        </select>
      </div>

      <!-- 分组（多选） -->
      <div class="flex flex-col gap-1.5">
        <label class="text-2xs text-slate-400 uppercase tracking-widest font-medium">分组筛选</label>
        <div class="relative" @click="flowsOpen = !flowsOpen">
          <div class="bg-slate-700 border border-slate-600 text-slate-100 text-sm px-3.5 py-2.5 rounded-lg
                      cursor-pointer min-w-[180px] flex items-center justify-between gap-2"
               :class="{'border-blue-500': flowsOpen}">
            <span class="truncate" :class="{'text-slate-400': filters.flows.length === 0}">
              {[ filters.flows.length ? filters.flows.length + ' 个分组' : '全部分组' ]}
            </span>
            <svg class="w-3 h-3 fill-slate-400 flex-shrink-0" viewBox="0 0 12 12"><path d="M2 4l4 4 4-4"/></svg>
          </div>
          <!-- 下拉多选面板 -->
          <div v-if="flowsOpen" class="absolute top-full mt-1 left-0 right-0 bg-slate-700 border border-slate-600
                        rounded-lg shadow-xl z-50 max-h-60 overflow-y-auto" @click.stop>
            <div v-for="f in filterOptions.flows" :key="f"
                 @click="toggleFlow(f)"
                 class="flex items-center gap-2 px-3.5 py-2 hover:bg-slate-600 cursor-pointer text-sm">
              <input type="checkbox" :checked="filters.flows.includes(f)"
                     class="accent-blue-500 w-4 h-4 rounded pointer-events-none">
              <span>{[ f ]}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 员工 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-2xs text-slate-400 uppercase tracking-widest font-medium">员工筛选</label>
        <select v-model="filters.reg_per_sys_id" @change="onFilterChange"
                class="bg-slate-700 border border-slate-600 text-slate-100 text-sm px-3.5 py-2.5 rounded-lg
                       focus:outline-none focus:border-blue-500 min-w-[160px] appearance-none
                       bg-[url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22%3E%3Cpath d=%22M2 4l4 4 4-4%22 fill=%22none%22 stroke=%22%2394a3b8%22 stroke-width=%221.5%22 stroke-linecap=%22round%22/%3E%3C/svg%3E')] bg-[right_14px_center] bg-no-repeat pr-10">
          <option value="">全部员工</option>
          <option v-for="e in filterOptions.employees" :key="e.reg_per_sys_id" :value="e.reg_per_sys_id">{[ e.name ]}</option>
        </select>
      </div>

      <!-- 清空按钮 -->
      <button @click="clearFilters"
              class="self-end px-5 py-2.5 border border-slate-600 text-slate-400 text-sm rounded-lg
                     hover:border-red-500 hover:text-red-400 transition-colors">
        清空筛选
      </button>

      <!-- 筛选状态徽章 -->
      <div class="self-end ml-auto max-md:ml-0 inline-flex items-center gap-1.5 bg-blue-600/10 border border-blue-500/50
                  text-blue-400 text-xs font-medium px-3.5 py-1.5 rounded-full">
        <svg class="w-3.5 h-3.5 fill-blue-400" viewBox="0 0 24 24"><path d="M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z"/></svg>
        <span>{[ filterBadgeText ]}</span>
      </div>
    </div>

    <!-- Content Grid -->
    <div class="grid grid-cols-1 gap-6">

      <!-- 产量排行榜 -->
      <div class="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <div class="flex items-center justify-between px-5 py-4 border-b border-slate-700">
          <h2 class="text-[15px] font-bold flex items-center gap-2.5">
            <span class="w-2 h-2 bg-blue-500 rounded-full"></span>产量排行榜
          </h2>
          <span class="font-mono text-xs text-slate-400 bg-slate-700 px-2.5 py-1 rounded-full">
            {[ ranking.pagination.total_count ]} 条记录
          </span>
        </div>

        <div class="overflow-x-auto max-h-[520px] overflow-y-auto
                    scrollbar-thin scrollbar-thumb-slate-600 scrollbar-track-transparent">
          <table class="w-full border-collapse">
            <thead>
              <tr>
                <th class="sticky top-0 bg-slate-700 text-2xs font-medium text-slate-400 uppercase tracking-widest
                           px-4 py-3 text-left border-b border-slate-600 z-10 whitespace-nowrap w-[70px]">排名</th>
                <th class="sticky top-0 bg-slate-700 text-2xs font-medium text-slate-400 uppercase tracking-widest
                           px-4 py-3 text-left border-b border-slate-600 z-10 whitespace-nowrap">工人姓名</th>
                <th class="sticky top-0 bg-slate-700 text-2xs font-medium text-slate-400 uppercase tracking-widest
                           px-4 py-3 text-left border-b border-slate-600 z-10 whitespace-nowrap">工序</th>
                <th class="sticky top-0 bg-slate-700 text-2xs font-medium text-slate-400 uppercase tracking-widest
                           px-4 py-3 text-left border-b border-slate-600 z-10 whitespace-nowrap">款号</th>
                <th class="sticky top-0 bg-slate-700 text-2xs font-medium text-slate-400 uppercase tracking-widest
                           px-4 py-3 text-left border-b border-slate-600 z-10 whitespace-nowrap">日产量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="ranking.workers.length === 0">
                <td colspan="5">
                  <div class="flex flex-col items-center justify-center py-16 text-slate-500 gap-3">
                    <svg class="w-12 h-12 fill-slate-600" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                    <p class="text-sm">没有匹配的工人数据</p>
                  </div>
                </td>
              </tr>
              <tr v-for="(w, i) in ranking.workers" :key="w.reg_per_sys_id"
                  class="transition-colors hover:bg-slate-700"
                  :style="{ animation: `rowIn 0.35s ease ${i * 0.04}s both` }">
                <td class="px-4 py-3.5 border-b border-slate-700">
                  <span class="inline-flex items-center justify-center w-[30px] h-[30px] rounded-lg font-mono text-[13px] font-medium"
                        :class="getRankClass(w.rank)">
                    {[ w.rank ]}
                  </span>
                </td>
                <td class="px-4 py-3.5 border-b border-slate-700">
                  <div class="flex items-center gap-2.5">
                    <div class="w-8 h-8 rounded-lg flex items-center justify-center text-[13px] font-bold
                                bg-slate-600 text-blue-400 border border-slate-500"
                         :style="{ color: getColor(i), borderColor: getColor(i) + '33' }">
                      {[ getInitial(w.worker_name) ]}
                    </div>
                    <span class="font-medium text-sm">{[ w.worker_name ]}</span>
                  </div>
                </td>
                <td class="px-4 py-3.5 border-b border-slate-700">
                  <span class="inline-block text-xs px-2.5 py-0.5 rounded-full bg-slate-700 text-slate-400 border border-slate-600">{[ w.stepno ]}</span>
                </td>
                <td class="px-4 py-3.5 border-b border-slate-700">
                  <span class="inline-block font-mono text-xs text-blue-400 bg-blue-600/10 px-2.5 py-0.5 rounded-full font-medium">{[ w.wrk_order ]}</span>
                </td>
                <td class="px-4 py-3.5 border-b border-slate-700">
                  <div class="flex items-center gap-3 min-w-[200px]">
                    <div class="flex-1 h-2 bg-slate-700 rounded overflow-hidden min-w-[80px]">
                      <div class="h-full rounded transition-[width] duration-600 ease-in-out"
                           :style="{ width: (w.production / maxProduction * 100).toFixed(1) + '%',
                                     background: `linear-gradient(90deg, ${getColor(i)}, ${getColor(i)}88)` }"></div>
                    </div>
                    <span class="font-mono text-sm font-medium min-w-[48px] text-right">{[ w.production ]}</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 分页 -->
        <div v-if="ranking.pagination.total_pages > 1"
             class="flex items-center justify-center gap-4 px-5 py-3 border-t border-slate-700">
          <button @click="onPageChange(ranking.pagination.page - 1)"
                  :disabled="ranking.pagination.page <= 1"
                  class="px-4 py-2 rounded-lg text-sm transition-colors"
                  :class="ranking.pagination.page <= 1
                    ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'">
            &#9664; 上一页
          </button>
          <span class="text-sm text-slate-400 font-mono">
            第 {[ ranking.pagination.page ]}/{[ ranking.pagination.total_pages ]} 页
          </span>
          <button @click="onPageChange(ranking.pagination.page + 1)"
                  :disabled="ranking.pagination.page >= ranking.pagination.total_pages"
                  class="px-4 py-2 rounded-lg text-sm transition-colors"
                  :class="ranking.pagination.page >= ranking.pagination.total_pages
                    ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'">
            下一页 &#9654;
          </button>
        </div>
      </div>

      <!-- 产量分布图 -->
      <div class="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <div class="flex items-center justify-between px-5 py-4 border-b border-slate-700">
          <h2 class="text-[15px] font-bold flex items-center gap-2.5">
            <span class="w-2 h-2 bg-blue-500 rounded-full"></span>产量分布图
          </h2>
          <span class="font-mono text-xs text-slate-400 bg-slate-700 px-2.5 py-1 rounded-full">
            当前页 {[ ranking.workers.length ]} 人
          </span>
        </div>

        <div class="p-5 min-h-[400px]">
          <div v-if="ranking.workers.length === 0"
               class="flex flex-col items-center justify-center py-16 text-slate-500 gap-3">
            <svg class="w-12 h-12 fill-slate-600" viewBox="0 0 24 24"><path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/></svg>
            <p class="text-sm">暂无数据</p>
          </div>
          <div v-else class="flex flex-col gap-2">
            <div v-for="(w, i) in ranking.workers" :key="'bar-' + w.reg_per_sys_id"
                 class="flex items-center gap-3"
                 :style="{ animation: `barIn 0.5s ease ${i * 0.06}s both` }">
              <span class="w-[60px] text-[13px] text-right text-slate-400 flex-shrink-0 truncate">{[ w.worker_name ]}</span>
              <div class="flex-1 h-8 bg-slate-700 rounded-md overflow-hidden relative">
                <div class="h-full rounded-md flex items-center pl-3 transition-[width] duration-800 ease-in-out"
                     :style="{ width: (w.production / maxProduction * 100).toFixed(1) + '%',
                               background: `linear-gradient(90deg, ${getColor(i)}, ${getColor(i)}88)` }">
                  <span class="font-mono text-xs font-medium text-slate-900 whitespace-nowrap
                               opacity-0 hover:opacity-100 transition-opacity duration-300">
                    {[ w.production ]}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</div>

<style>
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
@keyframes rowIn {
  from { opacity: 0; transform: translateX(-10px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes barIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 排名徽章 */
.rank-1 { background: linear-gradient(135deg, #f0a500, #e08e00); color: #0a0b0e; box-shadow: 0 2px 12px rgba(240,165,0,0.27); }
.rank-2 { background: linear-gradient(135deg, #8a8d96, #6b6d75); color: #0a0b0e; }
.rank-3 { background: linear-gradient(135deg, #b87333, #a06228); color: #0a0b0e; }
.rank-other { background: #334155; color: #94a3b8; }

/* 自定义滚动条 */
.scrollbar-thin::-webkit-scrollbar { width: 6px; height: 6px; }
.scrollbar-thin::-webkit-scrollbar-track { background: transparent; }
.scrollbar-thin::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }

/* 过渡 */
.duration-600 { transition-duration: 600ms; }
.duration-800 { transition-duration: 800ms; }
</style>

<script>
const { createApp, ref, reactive, computed, watch, onMounted } = Vue;

createApp({
  delimiters: ['{[', ']}'],
  setup() {
    // ========== 颜色 ==========
    const colors = [
      '#3b82f6','#22c55e','#ef4444','#8b5cf6','#ec4899',
      '#06b6d4','#84cc16','#f59e0b','#f97316','#6366f1',
      '#14b8a6','#e11d48','#7c3aed','#ea580c','#0891b2',
      '#65a30d','#d946ef','#2563eb','#c026d3','#0d9488'
    ];

    function getColor(i) { return colors[i % colors.length]; }
    function getInitial(name) { return name ? String(name).charAt(0) : '?'; }
    function getRankClass(rank) {
      if (rank === 1) return 'rank-1';
      if (rank === 2) return 'rank-2';
      if (rank === 3) return 'rank-3';
      return 'rank-other';
    }

    // ========== 状态 ==========
    const clock = ref('');
    const date = ref(new Date().toISOString().slice(0, 10));

    const filters = reactive({
      stepno: '70',
      wrk_order: '',
      flows: [],
      reg_per_sys_id: '',
    });

    const filterOptions = reactive({
      stepnos: [],
      wrk_orders: [],
      flows: [],
      employees: [],
    });

    const stats = reactive({
      worker_count: 0,
      total_production: 0,
      avg_production: 0,
      max_production: 0,
      max_worker_name: '',
    });

    const animatedStats = reactive({
      worker_count: 0,
      total_production: 0,
      avg_production: 0,
      max_production: 0,
    });

    const ranking = reactive({
      workers: [],
      pagination: { page: 1, page_size: 50, total_pages: 1, total_count: 0 },
    });

    const flowsOpen = ref(false);

    // ========== 计算属性 ==========
    const maxProduction = computed(() => {
      if (ranking.workers.length === 0) return 1;
      return Math.max(...ranking.workers.map(w => w.production));
    });

    const filterBadgeText = computed(() => {
      const parts = [];
      if (filters.stepno) parts.push('工序: ' + filters.stepno);
      if (filters.wrk_order) parts.push('款号: ' + filters.wrk_order);
      if (filters.flows.length) parts.push(filters.flows.length + '个分组');
      if (filters.reg_per_sys_id) parts.push('员工: ' + filters.reg_per_sys_id);
      return parts.length ? parts.join(' · ') + ' — ' + ranking.pagination.total_count + ' 人'
                          : '全部流水线车间 — ' + ranking.pagination.total_count + ' 人';
    });

    // ========== 方法 ==========
    async function fetchStats() {
      const params = new URLSearchParams({ date: date.value });
      if (filters.stepno) params.set('stepno', filters.stepno);
      if (filters.wrk_order) params.set('wrk_order', filters.wrk_order);
      filters.flows.forEach(f => params.append('flow', f));
      if (filters.reg_per_sys_id) params.set('reg_per_sys_id', filters.reg_per_sys_id);

      try {
        const res = await fetch('/api/kanban/stats/?' + params.toString());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        Object.assign(stats, data);
        animateStats(data);
      } catch (e) {
        console.error('fetchStats 失败:', e);
      }
    }

    async function fetchRanking(pageNum = 1) {
      const params = new URLSearchParams({ date: date.value, page: pageNum, page_size: 50 });
      if (filters.stepno) params.set('stepno', filters.stepno);
      if (filters.wrk_order) params.set('wrk_order', filters.wrk_order);
      filters.flows.forEach(f => params.append('flow', f));
      if (filters.reg_per_sys_id) params.set('reg_per_sys_id', filters.reg_per_sys_id);

      try {
        const res = await fetch('/api/kanban/ranking/?' + params.toString());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        ranking.workers = data.workers;
        ranking.pagination = data.pagination;
      } catch (e) {
        console.error('fetchRanking 失败:', e);
      }
    }

    async function fetchFilterOptions() {
      const params = new URLSearchParams({ date: date.value });
      filters.flows.forEach(f => params.append('flow', f));

      try {
        const res = await fetch('/api/kanban/filter-options/?' + params.toString());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        filterOptions.stepnos = data.stepnos;
        filterOptions.wrk_orders = data.wrk_orders;
        filterOptions.flows = data.flows;
        filterOptions.employees = data.employees;
      } catch (e) {
        console.error('fetchFilterOptions 失败:', e);
      }
    }

    function onFilterChange() {
      ranking.pagination.page = 1;
      fetchStats();
      fetchRanking(1);
    }

    function onPageChange(pageNum) {
      if (pageNum < 1 || pageNum > ranking.pagination.total_pages) return;
      fetchRanking(pageNum);
    }

    function toggleFlow(flowName) {
      const idx = filters.flows.indexOf(flowName);
      if (idx >= 0) {
        filters.flows.splice(idx, 1);
      } else {
        filters.flows.push(flowName);
      }
      // Flow 变化后更新员工列表，级联清除不在范围内的员工
      fetchFilterOptions().then(() => {
        const validIds = new Set(filterOptions.employees.map(e => e.reg_per_sys_id));
        if (filters.reg_per_sys_id && !validIds.has(filters.reg_per_sys_id)) {
          filters.reg_per_sys_id = '';
        }
      });
      onFilterChange();
    }

    function clearFilters() {
      filters.stepno = '70';
      filters.wrk_order = '';
      filters.flows = [];
      filters.reg_per_sys_id = '';
      fetchFilterOptions();
      onFilterChange();
    }

    function animateStats(target) {
      const keys = ['worker_count', 'total_production', 'avg_production', 'max_production'];
      keys.forEach(key => {
        const current = animatedStats[key] || 0;
        const diff = target[key] - current;
        const steps = 20;
        let step = 0;
        const timer = setInterval(() => {
          step++;
          animatedStats[key] = Math.round(current + (diff * step / steps));
          if (step >= steps) clearInterval(timer);
        }, 20);
      });
    }

    function updateClock() {
      const now = new Date();
      clock.value = now.toLocaleString('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
    }

    // 关闭 Flow 下拉
    function handleClickOutside(e) {
      if (!e.target.closest('.relative')) flowsOpen.value = false;
    }

    // ========== 初始化 ==========
    onMounted(() => {
      updateClock();
      setInterval(updateClock, 1000);
      document.addEventListener('click', handleClickOutside);
      fetchFilterOptions();
      fetchStats();
      fetchRanking(1);
    });

    return {
      clock, date, filters, filterOptions, stats, animatedStats, ranking,
      flowsOpen, maxProduction, filterBadgeText,
      getColor, getInitial, getRankClass,
      fetchStats, fetchRanking, fetchFilterOptions,
      onFilterChange, onPageChange, toggleFlow, clearFilters,
    };
  }
}).mount('#kanbanApp');
</script>

</body>
</html>
```

- [ ] **Step 2: 验证模板基本结构**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python manage.py check
```

预期：无错误输出

- [ ] **Step 3: 提交**

```bash
git add iwork/templates/iwork/kanban.html
git commit -m "[2026-06-16][FEAT] 创建产量看板页面模板（Vue 3 + Tailwind）"
```

---

### Task 9: 集成验证与最终检查

**Files:** 无新建，验证所有已修改文件

- [ ] **Step 1: 运行全部测试**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python -m pytest tests/test_kanban_queries.py tests/test_kanban_api.py -v
```

预期：全部 PASS

- [ ] **Step 2: Django 系统检查**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python manage.py check --deploy
```

- [ ] **Step 3: 确认 URL 路由正确加载**

```bash
cd C:/Users/lipengfei/ZCodeProject/iwork && chcp 65001 && python manage.py show_urls 2>/dev/null || python -c "from django.urls import get_resolver; resolver = get_resolver(); [print(p.pattern, p.name) for p in resolver.url_patterns if 'kanban' in (p.name or '')]"
```

预期：输出 4 条 kanban 相关路由

- [ ] **Step 4: 更新规范手册**

在 `docs/开发文档/iwork规范手册.md` 追加产量看板模块相关条目：

```markdown
### 产量看板模块

- **页面路由**: `/kanban/` → `views.kanban_page` → `kanban.html`
- **API 端点**: `/api/kanban/stats/`, `/api/kanban/ranking/`, `/api/kanban/filter-options/`
- **查询函数**: `get_kanban_stats`, `get_kanban_ranking`, `get_kanban_filter_options`, `_apply_kanban_filters`
- **默认配置**: `KANBAN_DEFAULT_STEPNO='70'`, `KANBAN_DEFAULT_PAGE_SIZE=50`
- **筛选器**: 工序(单选)/款号(单选)/Flow(多选)/员工(单选，级联Flow)/清空按钮
- **分页**: 50条/页，表格与柱状图消费同一数据源
- **模板**: Vue 3 CDN + Tailwind CSS CDN，动效保留 CSS animation
```

- [ ] **Step 5: 最终提交**

```bash
git add docs/开发文档/iwork规范手册.md
git commit -m "[2026-06-16][DOCS] 更新规范手册，记录产量看板模块"
```

---

## 依赖关系

```
Task 1 (query tests) → Task 2 (query impl) → Task 3 (local mirror)
                                               ↘
Task 4 (api tests)   → Task 5 (api impl)      → Task 6 (routes + view + config)
                                                                  ↓
                                                            Task 7 (header)
                                                                  ↓
                                                            Task 8 (template)
                                                                  ↓
                                                            Task 9 (integration)
```

Task 2 和 Task 3 可合并，Task 6/7/8 可在 Task 5 之后并行。
