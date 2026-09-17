"""
查询函数测试（queries.py 远程库查询层）
"""
from unittest.mock import Mock, call, patch
from datetime import date
import pytest
from django.utils import timezone


class TestGetDateRange:
    """get_date_range 工具函数"""

    def test_returns_aware_datetimes(self):
        """返回 timezone-aware 范围"""
        from iwork.queries import get_date_range
        start, end = get_date_range(date(2026, 5, 12))
        assert timezone.is_aware(start)
        assert timezone.is_aware(end)

    def test_one_day_span(self):
        """跨度正好 24 小时"""
        from iwork.queries import get_date_range
        start, end = get_date_range(date(2026, 5, 12))
        assert (end - start).days == 1
        assert start.hour == 0 and start.minute == 0


@patch('iwork.models.Pywrkord')
def test_initial_style_numbers_are_loaded_in_one_normalized_batch(mock_model):
    """初版款号必须按完整工单批量读取，并规范化空白值。"""
    from iwork.queries import get_initial_style_numbers

    rows = mock_model.objects.using.return_value.filter.return_value.values.return_value
    rows.__iter__.return_value = iter([
        {'WrkOrder': 'BU1001', 'ExtField01': '  SAMPLE-01  '},
        {'WrkOrder': 'BU1002', 'ExtField01': None},
    ])

    result = get_initial_style_numbers(['BU1002', '', 'BU1001', 'BU1001', 'MISS'])

    assert result == {
        'BU1001': 'SAMPLE-01',
        'BU1002': '',
        'MISS': '',
    }
    mock_model.objects.using.assert_called_once_with('iwork')
    mock_model.objects.using.return_value.filter.assert_called_once_with(
        WrkOrder__in=['BU1001', 'BU1002', 'MISS'],
    )


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_igarment_creation_dates_use_earliest_day_per_workorder():
    """同一 WrkOrder 多个创建时间时应取最早日期，并忽略空编号。"""
    from iwork.local_models import IGarmentProductionOrder
    from iwork.queries import get_igarment_creation_dates

    IGarmentProductionOrder.objects.using('iwork_local').bulk_create([
        IGarmentProductionOrder(
            customer_order_no='BU1211',
            order_no='ORDER-2',
            quantity=20,
            created_date=timezone.make_aware(
                timezone.datetime(2026, 6, 12, 9, 0),
            ),
        ),
        IGarmentProductionOrder(
            customer_order_no='BU1211',
            order_no='ORDER-1',
            quantity=10,
            created_date=timezone.make_aware(
                timezone.datetime(2026, 6, 10, 15, 30),
            ),
        ),
        IGarmentProductionOrder(
            customer_order_no='',
            order_no='UNMATCHED',
            quantity=1,
            created_date=timezone.make_aware(
                timezone.datetime(2020, 1, 1, 0, 0),
            ),
        ),
    ])

    assert get_igarment_creation_dates(['BU1211', 'BU1211-01', 'MISSING', '']) == {
        'BU1211': date(2026, 6, 10),
        'BU1211-01': date(2026, 6, 10),
    }


@patch('iwork.models.Pytckreg3')
def test_cumulative_rows_use_all_non_null_regdates(mock_model):
    """累计查询应按完整工单一次汇总全部非空日期的 Flow 事实。"""
    from iwork.queries import get_read_model_cumulative_rows

    queryset = mock_model.objects.using.return_value.filter.return_value
    rows = (
        queryset.values.return_value.annotate.return_value.order_by.return_value
    )
    rows.__iter__.return_value = iter([
        {
            'RegPerSysID': 1001,
            'StepNo': 70,
            'WrkOrder': 'BU1211',
            'Flow': 'Sewing-A2',
            'cumulative_qty': 23152,
        },
        {
            'RegPerSysID': 1002,
            'StepNo': 80,
            'WrkOrder': 'BU1211',
            'Flow': 'Finishing-QC1',
            'cumulative_qty': 500,
        },
        {
            'RegPerSysID': 1003,
            'StepNo': 90,
            'WrkOrder': 'BU1211',
            'Flow': '',
            'cumulative_qty': 20,
        },
    ])

    result = get_read_model_cumulative_rows(['BU1211', 'BU1211', ''])

    query_filter = mock_model.objects.using.return_value.filter.call_args.kwargs
    assert query_filter['RegDate__isnull'] is False
    assert query_filter['WrkOrder__in'] == ['BU1211']
    assert 'RegDate__gte' not in query_filter
    assert result == [
        {
            'reg_per_sys_id': 1001,
            'stepno': 70,
            'wrk_order': 'BU1211',
            'flow': 'Sewing-A2',
            'cumulative_qty': 23152,
        },
        {
            'reg_per_sys_id': 1002,
            'stepno': 80,
            'wrk_order': 'BU1211',
            'flow': 'Finishing-QC1',
            'cumulative_qty': 500,
        },
        {
            'reg_per_sys_id': 1003,
            'stepno': 90,
            'wrk_order': 'BU1211',
            'flow': '',
            'cumulative_qty': 20,
        },
    ]
    queryset.exclude.assert_not_called()
    queryset.filter.assert_not_called()


@patch('iwork.models.Pytckreg3')
def test_cumulative_rows_use_one_query_for_multiple_workorders(mock_model):
    """多个工单必须通过一个 IN 聚合查询完成，不再按创建日期 UNION。"""
    from iwork.queries import get_read_model_cumulative_rows

    queryset = mock_model.objects.using.return_value
    rows = (
        queryset.filter.return_value.values.return_value
        .annotate.return_value.order_by.return_value
    )
    rows.__iter__.return_value = iter([])

    get_read_model_cumulative_rows(['BU1212', 'BU1211'])

    queryset.filter.assert_called_once_with(
        WrkOrder__in=['BU1211', 'BU1212'],
        RegDate__isnull=False,
    )
    queryset.filter.return_value.exclude.assert_not_called()
    queryset.filter.return_value.filter.assert_not_called()
    rows.union.assert_not_called()


@patch('iwork.models.Pytckreg3')
def test_cumulative_rows_keep_legacy_creation_date_mapping_interface(mock_model):
    """旧版创建日期映射参数仍可调用，但日期值不再参与累计过滤。"""
    from iwork.queries import get_read_model_cumulative_rows

    queryset = mock_model.objects.using.return_value
    rows = (
        queryset.filter.return_value.values.return_value
        .annotate.return_value.order_by.return_value
    )
    rows.__iter__.return_value = iter([])

    get_read_model_cumulative_rows({
        'BU1211': date(2026, 6, 10),
        'BU1212': date(2026, 6, 11),
    })

    queryset.filter.assert_called_once_with(
        WrkOrder__in=['BU1211', 'BU1212'],
        RegDate__isnull=False,
    )


@patch('iwork.queries.transaction.atomic')
@patch('iwork.queries.connections')
def test_read_model_snapshot_uses_repeatable_read(mock_connections, mock_atomic):
    """多条远程查询必须运行在同一个 MySQL 可重复读事务中，并设置语句执行上限。"""
    from iwork.queries import read_model_consistent_snapshot

    connection = mock_connections.__getitem__.return_value
    connection.vendor = 'mysql'
    connection.mysql_version = (5, 7, 8)
    cursor = connection.cursor.return_value.__enter__.return_value

    with read_model_consistent_snapshot():
        pass

    cursor.execute.assert_has_calls([
        call('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'),
        call('SET SESSION MAX_EXECUTION_TIME = 30000'),
        call('SET SESSION MAX_EXECUTION_TIME = 0'),
    ])
    mock_atomic.assert_called_once_with(using='iwork')


@patch('iwork.queries.transaction.atomic')
@patch('iwork.queries.connections')
def test_read_model_snapshot_skips_execution_limit_on_old_mysql(mock_connections, mock_atomic):
    """MySQL 5.6 不支持 MAX_EXECUTION_TIME，应跳过语句级执行上限。"""
    from iwork.queries import read_model_consistent_snapshot

    connection = mock_connections.__getitem__.return_value
    connection.vendor = 'mysql'
    connection.mysql_version = (5, 6, 29)
    cursor = connection.cursor.return_value.__enter__.return_value

    with read_model_consistent_snapshot():
        pass

    cursor.execute.assert_called_once_with(
        'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ',
    )
    mock_atomic.assert_called_once_with(using='iwork')


@patch('iwork.models.Pyperson')
@patch('iwork.models.Pytckreg3')
def test_employee_remark_map_prefers_dorm_no_with_worker_no_fallback(mock_pytckreg3, mock_pyperson):
    """员工映射必须 DormNo 优先、WorkerNo 回退，并排除双空员工。"""
    from iwork.queries import get_employee_remark_map

    mock_pyperson.objects.using.return_value.filter.return_value.values.return_value = [
        {'SysID': 1001, 'WorkerNo': '12', 'DormNo': 'S0012'},
        {'SysID': 1002, 'WorkerNo': 'SL001', 'DormNo': ''},
        {'SysID': 1003, 'WorkerNo': '18', 'DormNo': None},
        {'SysID': 1004, 'WorkerNo': '', 'DormNo': '   '},
    ]

    result = get_employee_remark_map()

    mock_pytckreg3.objects.using.assert_called_once_with('iwork')
    mock_pyperson.objects.using.assert_called_once_with('iwork')
    mock_pyperson.objects.using.return_value.filter.return_value.values.assert_called_once_with(
        'SysID',
        'WorkerNo',
        'DormNo',
    )
    assert result == {'1001': 'S0012', '1002': 'SL001', '1003': '18'}


class TestApplyStepnoFilter:
    """apply_stepno_filter"""

    def test_none_filter_returns_unchanged(self):
        """None 过滤器不修改 QuerySet"""
        from iwork.queries import apply_stepno_filter
        qs = Mock()
        result = apply_stepno_filter(qs, None)
        assert result is qs

    def test_empty_list_returns_unchanged(self):
        """空列表不过滤（falsey）"""
        from iwork.queries import apply_stepno_filter
        qs = Mock()
        result = apply_stepno_filter(qs, [])
        assert result is qs

    def test_single_stepno_applies_filter(self):
        """单个工序号 → Q(StepNo__in=[70])"""
        from iwork.queries import apply_stepno_filter
        qs = Mock()
        apply_stepno_filter(qs, [70])
        qs.filter.assert_called_once_with(StepNo__in=[70])


class TestGetFlowDetail:
    """get_flow_detail"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_flow_summary(self, mock_model):
        """返回 Flow 汇总信息"""
        from iwork.queries import get_flow_detail

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.aggregate.return_value = {'total': 500}
        mock_qs.values.return_value.distinct.return_value.count.return_value = 10

        result = get_flow_detail(date(2026, 5, 12), 'FlowA')

        assert result['flow'] == 'FlowA'
        assert result['total_qty'] == 500
        assert result['worker_count'] == 10

    @patch('iwork.models.Pytckreg3')
    def test_none_total_qty_defaults_to_zero(self, mock_model):
        """aggregate 返回 None → total_qty=0"""
        from iwork.queries import get_flow_detail

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.aggregate.return_value = {'total': None}

        result = get_flow_detail(date(2026, 5, 12), 'FlowA')
        assert result['total_qty'] == 0


class TestGetWorkorderDetail:
    """get_workorder_detail"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_workorder_detail_with_steps(self, mock_model):
        """返回工单详情含工序明细"""
        from iwork.queries import get_workorder_detail

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.aggregate.return_value = {'total': 300}
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'StepNo': 70, 'qty': 200, 'count': 10},
            {'StepNo': 69, 'qty': 100, 'count': 5},
        ]

        result = get_workorder_detail('W001', date(2026, 5, 12))

        assert result['wrk_order'] == 'W001'
        assert result['total_qty'] == 300
        assert len(result['steps']) == 2
        assert result['steps'][0]['StepNo'] == 70


class TestGetWorkordersPaginated:
    """get_workorders_paginated 分页逻辑"""

    @patch('iwork.models.Pytckreg3')
    def test_first_page_returns_correct_slice(self, mock_model):
        """第一页返回前 page_size 条"""
        from iwork.queries import get_workorders_paginated

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.distinct.return_value.count.return_value = 50
        items = [{'WrkOrder': f'W{i:03d}', 'total_qty': 100, 'worker_count': 3} for i in range(20)]
        mock_qs.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = items

        result = get_workorders_paginated(date(2026, 5, 12), page=1, page_size=20)

        assert result['page'] == 1
        assert result['total'] == 50
        assert result['total_pages'] == 3
        assert len(result['items']) == 20

    @patch('iwork.models.Pytckreg3')
    def test_empty_result_returns_one_page(self, mock_model):
        """空结果 total_pages 至少为 1"""
        from iwork.queries import get_workorders_paginated

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.distinct.return_value.count.return_value = 0
        mock_qs.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []

        result = get_workorders_paginated(date(2026, 5, 12))

        assert result['total_pages'] == 1
        assert result['items'] == []

    @patch('iwork.models.Pytckreg3')
    def test_stepno_filter_applied(self, mock_model):
        """工单查询传入 stepno_filter"""
        from iwork.queries import get_workorders_paginated

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.distinct.return_value.count.return_value = 0
        mock_qs.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []

        get_workorders_paginated(date(2026, 5, 12), stepno_filter=[70])

        # 验证 filter 被调用了至少一次（基础日期过滤 + StepNo 过滤）
        assert mock_model.objects.using.return_value.filter.called


class TestGetStationStats:
    """get_station_stats"""

    @patch('iwork.models.Pytckreg3')
    def test_excludes_empty_station(self, mock_model):
        """排除 StationID 为空的记录"""
        from iwork.queries import get_station_stats

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []

        get_station_stats(date(2026, 5, 12))

        mock_qs.exclude.assert_called_with(StationID='')

    @patch('iwork.models.Pytckreg3')
    def test_returns_station_label_and_qty(self, mock_model):
        """返回 station 标签和 qty"""
        from iwork.queries import get_station_stats

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = [
            {'StationID': 'S01', 'qty': 500},
            {'StationID': 'S02', 'qty': 300},
        ]

        result = get_station_stats(date(2026, 5, 12), limit=2)
        assert result[0] == {'station': 'S01', 'qty': 500}
        assert result[1] == {'station': 'S02', 'qty': 300}


class TestGetWorkerRanking:
    """get_worker_ranking"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_name_and_qty(self, mock_model):
        """返回员工名称和产量"""
        from iwork.queries import get_worker_ranking

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = [
            {'RegPerSysID': 1001, 'qty': 200},
        ]

        result = get_worker_ranking(date(2026, 5, 12), limit=1)
        assert result[0]['name'] == '1001'
        assert result[0]['qty'] == 200


class TestGetHeatmapData:
    """get_heatmap_data 热力图矩阵"""

    @patch('iwork.models.Pytckreg3')
    def test_builds_correct_matrix_shape(self, mock_model):
        """矩阵维度：len(hours) × len(flows)"""
        from iwork.queries import get_heatmap_data

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value.extra.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {'hour': 8, 'Flow': 'A1', 'qty': 100},
            {'hour': 9, 'Flow': 'A1', 'qty': 200},
            {'hour': 8, 'Flow': 'B1', 'qty': 50},
        ]

        result = get_heatmap_data(date(2026, 5, 12))

        assert len(result['hours']) == 2  # 8, 9
        assert len(result['flows']) == 2  # A1, B1
        assert len(result['data']) == 2   # 2 hours
        assert len(result['data'][0]) == 2  # 2 flows per hour

    @patch('iwork.models.Pytckreg3')
    def test_none_hour_filtered_out(self, mock_model):
        """hour 为 None 的记录被过滤"""
        from iwork.queries import get_heatmap_data

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value.extra.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {'hour': None, 'Flow': 'A1', 'qty': s}
            for s in [100, None, 50]
        ]

        result = get_heatmap_data(date(2026, 5, 12))
        assert len(result['hours']) == 0  # None hours are filtered

    @patch('iwork.models.Pytckreg3')
    def test_empty_data_returns_empty_structure(self, mock_model):
        """无数据返回空结构"""
        from iwork.queries import get_heatmap_data

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value.extra.return_value.values.return_value.annotate.return_value.order_by.return_value = []

        result = get_heatmap_data(date(2026, 5, 12))
        assert result['hours'] == []
        assert result['flows'] == []
        assert result['data'] == []


class TestGroupBy:
    """_groupby 分组迭代器"""

    def test_groups_sorted_rows(self):
        """按 key 正确分组已排序的行"""
        from iwork.queries import _groupby

        rows = [
            {'StepNo': 70, 'qty': 100},
            {'StepNo': 70, 'qty': 200},
            {'StepNo': 69, 'qty': 50},
            {'StepNo': 69, 'qty': 30},
        ]

        groups = list(_groupby(rows, 'StepNo'))
        assert len(groups) == 2
        assert groups[0][0] == 70
        assert len(groups[0][1]) == 2
        assert groups[1][0] == 69

    def test_single_group(self):
        """单组数据"""
        from iwork.queries import _groupby

        rows = [{'StepNo': 70, 'qty': 100}]
        groups = list(_groupby(rows, 'StepNo'))
        assert len(groups) == 1

    def test_empty_list(self):
        """空列表不产出任何组"""
        from iwork.queries import _groupby

        groups = list(_groupby([], 'StepNo'))
        assert len(groups) == 0

    def test_all_same_key(self):
        """所有行同一 key → 一个组"""
        from iwork.queries import _groupby

        rows = [{'k': 1, 'v': 'a'}, {'k': 1, 'v': 'b'}, {'k': 1, 'v': 'c'}]
        groups = list(_groupby(rows, 'k'))
        assert len(groups) == 1
        assert len(groups[0][1]) == 3


class TestGetAllStepnos:
    """get_all_stepnos"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_descending_stepnos_with_qty(self, mock_model):
        """返回有产量的工序号，降序"""
        from iwork.queries import get_all_stepnos

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'StepNo': 70, 'qty': 500},
            {'StepNo': 69, 'qty': 0},   # qty=0 → 过滤
            {'StepNo': 68, 'qty': 300},
        ]

        result = get_all_stepnos(date(2026, 5, 12))
        assert result == [70, 68]  # 69 excluded, descending

    @patch('iwork.models.Pytckreg3')
    def test_empty_result(self, mock_model):
        """无数据返回空列表"""
        from iwork.queries import get_all_stepnos

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = []

        result = get_all_stepnos(date(2026, 5, 12))
        assert result == []


class TestGetBatchBasicStats:
    """get_batch_basic_stats（修复后包含 workorder_count）"""

    @patch('iwork.models.Pytckreg3')
    def test_includes_workorder_count(self, mock_model):
        """返回中包含 workorder_count 字段"""
        from iwork.queries import get_batch_basic_stats

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value = [
            {'StepNo': 70, 'total_qty': 500, 'workorder_count': 12},
        ]

        result = get_batch_basic_stats(date(2026, 5, 12))
        assert result[70]['total_qty'] == 500
        assert result[70]['workorder_count'] == 12

    @patch('iwork.models.Pytckreg3')
    def test_none_values_default_to_zero(self, mock_model):
        """None 值默认为 0"""
        from iwork.queries import get_batch_basic_stats

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value = [
            {'StepNo': 70, 'total_qty': None, 'workorder_count': None},
        ]

        result = get_batch_basic_stats(date(2026, 5, 12))
        assert result[70]['total_qty'] == 0
        assert result[70]['workorder_count'] == 0


# ============================================================================
# 新增 Batch 查询函数测试（Flow 分组 + 员工明细）


class TestGetAllFlows:
    """get_all_flows — 不重复 Flow 列表，按字母排序"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_sorted_flows_with_qty(self, mock_model):
        """返回有产量的 Flow 名，字母升序，过滤 qty=0"""
        from iwork.queries import get_all_flows

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'Flow': 'VCO-C1', 'qty': 300},
            {'Flow': 'VCO-L5', 'qty': 500},
            {'Flow': 'VCO-X9', 'qty': 0},
        ]

        result = get_all_flows(date(2026, 5, 12))
        assert result == ['VCO-C1', 'VCO-L5']  # 字母排序, qty=0 过滤

    @patch('iwork.models.Pytckreg3')
    def test_empty_result(self, mock_model):
        """无数据返回空列表"""
        from iwork.queries import get_all_flows

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = []

        result = get_all_flows(date(2026, 5, 12))
        assert result == []


class TestGetBatchFlowOverview:
    """get_batch_flow_overview — 每个 Flow 的总产量和员工数"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_flow_summary_dict(self, mock_model):
        """返回以 Flow 为键的汇总字典"""
        from django.conf import settings

        from iwork.queries import get_batch_flow_overview

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        step_query = Mock()
        step_query.annotate.return_value.order_by.return_value = [
            {'Flow': 'VCO-L5', 'StepNo': 70, 'qty': 500, 'workers': 12},
            {'Flow': 'VCO-C1', 'StepNo': 69, 'qty': 300, 'workers': 8},
        ]
        worker_query = Mock()
        worker_query.annotate.return_value = [
            {'Flow': 'VCO-L5', 'total_workers': 12},
            {'Flow': 'VCO-C1', 'total_workers': 8},
        ]
        mock_qs.values.side_effect = lambda *fields: (
            step_query if fields == ('Flow', 'StepNo') else worker_query
        )

        result = get_batch_flow_overview(date(2026, 5, 12))
        assert result['VCO-L5'] == {
            'stepnos': {'70': {'qty': 500, 'workers': 12}},
            'total_workers': 12,
        }
        assert result['VCO-C1'] == {
            'stepnos': {'69': {'qty': 300, 'workers': 8}},
            'total_workers': 8,
        }
        mock_qs.exclude.assert_called_once_with(Flow='')
        mock_qs.filter.assert_called_once_with(Flow__in=settings.ALLOWED_FLOWS)


class TestGetBatchFlowHourly:
    """get_batch_flow_hourly — 每个 Flow 的小时产量趋势"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_flow_hourly_trends(self, mock_model):
        """按 Flow 分组返回每小时产量列表"""
        from iwork.queries import get_batch_flow_hourly

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.extra.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {'Flow': 'VCO-L5', 'hour': 8, 'qty': 100},
            {'Flow': 'VCO-L5', 'hour': 9, 'qty': 200},
            {'Flow': 'VCO-C1', 'hour': 8, 'qty': 50},
        ]

        result = get_batch_flow_hourly(date(2026, 5, 12))
        assert 'VCO-L5' in result
        assert len(result['VCO-L5']) == 2
        assert result['VCO-L5'][0] == {'hour': 8, 'qty': 100}
        assert result['VCO-L5'][1] == {'hour': 9, 'qty': 200}
        assert 'VCO-C1' in result
        assert len(result['VCO-C1']) == 1
        assert result['VCO-C1'][0] == {'hour': 8, 'qty': 50}


class TestGetBatchFlowEmployees:
    """get_batch_flow_employees — 每个 Flow 的员工明细，按产量降序"""

    @patch('iwork.queries.get_initial_style_numbers')
    @patch('iwork.queries.get_batch_step_metadata')
    @patch('iwork.models.Pytckreg3')
    def test_returns_employee_details_grouped_by_flow(
        self,
        mock_model,
        mock_metadata,
        mock_initial_styles,
    ):
        """工序组合键元数据与产值随员工明细返回。"""
        from iwork.queries import get_batch_flow_employees

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'Flow': 'VCO-L5', 'RegPerSysID': 1001, 'StepNo': 70, 'WrkOrder': 'SO001', 'qty': 200},
            {'Flow': 'VCO-L5', 'RegPerSysID': 1001, 'StepNo': 69, 'WrkOrder': 'SO001', 'qty': 100},
            {'Flow': 'VCO-L5', 'RegPerSysID': 1002, 'StepNo': 70, 'WrkOrder': 'SO002', 'qty': 50},
            {'Flow': 'VCO-C1', 'RegPerSysID': 1003, 'StepNo': 70, 'WrkOrder': 'SO003', 'qty': 300},
        ]
        mock_metadata.return_value = {
            ('SO001', 70): {'description': '后整', 'step_time': 0.25},
            ('SO001', 69): {'description': '包装', 'step_time': 0.0},
            ('SO003', 70): {'description': '车缝', 'step_time': 0.5},
        }
        mock_initial_styles.return_value = {
            'SO001': 'SAMPLE-01',
            'SO002': '',
            'SO003': 'SAMPLE-03',
        }

        result = get_batch_flow_employees(date(2026, 5, 12))

        # VCO-L5: 1001 total_qty=300, 1002 total_qty=50 → 降序排列
        assert len(result['VCO-L5']) == 2
        assert result['VCO-L5'][0]['reg_per_sys_id'] == 1001
        assert result['VCO-L5'][0]['total_qty'] == 300
        assert len(result['VCO-L5'][0]['steps']) == 2
        assert {
            'stepno': 70, 'qty': 200, 'workorder': 'SO001',
            'initial_style_no': 'SAMPLE-01',
            'description': '后整', 'step_time': 0.25, 'output_value': 50.0,
        } in result['VCO-L5'][0]['steps']
        assert {
            'stepno': 69, 'qty': 100, 'workorder': 'SO001',
            'initial_style_no': 'SAMPLE-01',
            'description': '包装', 'step_time': 0.0, 'output_value': 0.0,
        } in result['VCO-L5'][0]['steps']
        assert result['VCO-L5'][0]['output_value'] == 50.0
        assert result['VCO-L5'][0]['workorders'] == ['SO001']
        assert result['VCO-L5'][1]['reg_per_sys_id'] == 1002
        assert result['VCO-L5'][1]['total_qty'] == 50
        assert result['VCO-L5'][1]['output_value'] is None
        assert len(result['VCO-L5'][1]['steps']) == 1
        assert result['VCO-L5'][1]['workorders'] == ['SO002']

        # VCO-C1: 1003
        assert len(result['VCO-C1']) == 1
        assert result['VCO-C1'][0]['reg_per_sys_id'] == 1003
        assert result['VCO-C1'][0]['total_qty'] == 300
        assert result['VCO-C1'][0]['output_value'] == 150.0
        mock_metadata.assert_called_once_with(['SO001', 'SO002', 'SO003'])
        mock_initial_styles.assert_called_once_with(['SO001', 'SO002', 'SO003'])


class TestGetBatchStepnoEmployees:
    """get_batch_stepno_employees — 每个工序的员工明细，按产量降序"""

    @patch('iwork.models.Pytckreg3')
    def test_returns_employee_details_grouped_by_stepno(self, mock_model):
        """返回 {stepno: [{reg_per_sys_id, qty, flows}], ...}，组内按 qty 降序"""
        from iwork.queries import get_batch_stepno_employees

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'VCO-L5', 'qty': 200},
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'VCO-C1', 'qty': 100},
            {'StepNo': 70, 'RegPerSysID': 1002, 'Flow': 'VCO-L5', 'qty': 50},
            {'StepNo': 69, 'RegPerSysID': 1001, 'Flow': 'VCO-L5', 'qty': 300},
        ]

        result = get_batch_stepno_employees(date(2026, 5, 12))

        # StepNo 70: 1001 total_qty=300, 1002 total_qty=50 → 降序排列
        assert len(result[70]) == 2
        assert result[70][0]['reg_per_sys_id'] == 1001
        assert result[70][0]['qty'] == 300
        assert set(result[70][0]['flows']) == {'VCO-L5', 'VCO-C1'}
        assert result[70][1]['reg_per_sys_id'] == 1002
        assert result[70][1]['qty'] == 50
        assert result[70][1]['flows'] == ['VCO-L5']

        # StepNo 69: 1001
        assert len(result[69]) == 1
        assert result[69][0]['reg_per_sys_id'] == 1001
        assert result[69][0]['qty'] == 300
        assert result[69][0]['flows'] == ['VCO-L5']


class TestGetBatchProductOverview:
    """按产品名称概览包含工序字典与标准工时。"""

    @patch('iwork.queries.get_batch_step_metadata')
    @patch('iwork.queries.ProductionOrder')
    @patch('iwork.queries.get_records_queryset')
    def test_includes_description_and_step_time(
        self, mock_records, mock_order, mock_metadata,
    ):
        """查询结果应包含工序描述和标准工时。"""
        from iwork.queries import get_batch_product_overview

        queryset = mock_records.return_value
        queryset.values.return_value.annotate.return_value.order_by.return_value = [
            {'WrkOrder': 'BU0724', 'StepNo': 70, 'Flow': 'Sewing-A1', 'qty': 100, 'workers': 2},
            {'WrkOrder': 'BU0724', 'StepNo': 71, 'Flow': 'Sewing-A1', 'qty': 50, 'workers': 1},
            {'WrkOrder': 'BU0724', 'StepNo': 72, 'Flow': 'Sewing-A1', 'qty': 20, 'workers': 1},
            {
                'WrkOrder': 'BU0724', 'StepNo': 80,
                'Flow': 'Finishing-QC1', 'qty': 30, 'workers': 1,
            },
        ]
        order_query = mock_order.objects.using.return_value.filter.return_value
        order_query.values.return_value.distinct.return_value = [
            {'style_no': 'BU0724', 'product_name': 'OLLIE TEE', 'order_no': 'PO-1'},
        ]
        mock_metadata.return_value = {
            ('BU0724', 70): {'description': '后整', 'step_time': 0.331},
            ('BU0724', 72): {'description': '包装', 'step_time': 0.0},
        }

        result = get_batch_product_overview(date(2026, 7, 15))

        steps = result['products'][0]['wrk_orders'][0]['stepnos']
        assert steps[0]['description'] == '后整'
        assert steps[0]['step_time'] == 0.331
        assert steps[0]['output_value'] == 33.1
        assert steps[1]['description'] == ''
        assert steps[1]['step_time'] is None
        assert steps[1]['output_value'] is None
        assert steps[2]['step_time'] == 0.0
        assert steps[2]['output_value'] == 0.0
        assert result['products'][0]['total_qty'] == 200
        assert 'Sewing-A1' in result['normal_flows']
        assert 'Finishing-QC1' not in result['normal_flows']
        queryset.exclude.assert_not_called()
        queryset.filter.assert_not_called()
        mock_metadata.assert_called_once_with(['BU0724'])


class TestStepMetadataQueries:
    """pywrkstp 描述和工时使用同一组合键。"""

    @patch('iwork.models.Pywrkstp')
    def test_batch_metadata_uses_wrkorder_and_stepno(self, mock_model):
        """批量元数据应使用工单和工序号复合键。"""
        from iwork.queries import get_batch_step_metadata

        query = mock_model.objects.using.return_value.filter.return_value
        query.values.return_value = [{
            'WrkOrder': 'BU0724',
            'StepNo': 70,
            'Description': '后整',
            'StepTime': 0.331,
        }]

        result = get_batch_step_metadata(['BU0724'])

        assert result == {
            ('BU0724', 70): {'description': '后整', 'step_time': 0.331},
        }
        query.values.assert_called_once_with('WrkOrder', 'StepNo', 'Description', 'StepTime')

    @patch('iwork.models.Pywrkstp')
    def test_single_description_filters_full_composite_key(self, mock_model):
        """单条描述查询应按完整复合键过滤。"""
        from iwork.queries import get_step_description

        mock_model.objects.using.return_value.get.return_value.Description = '后整'

        assert get_step_description('BU0724', 70) == '后整'
        mock_model.objects.using.return_value.get.assert_called_once_with(
            WrkOrder='BU0724', StepNo=70,
        )
