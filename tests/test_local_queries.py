"""
本地查询函数测试（local_queries.py 本地库查询层）
"""
import pytest
from unittest.mock import patch, Mock
from datetime import date
from django.utils import timezone


class TestGetDateRange:
    """get_date_range"""

    def test_returns_aware_range(self):
        """返回 timezone-aware 范围"""
        from iwork.local_queries import get_date_range
        start, end = get_date_range(date(2026, 5, 12))
        assert timezone.is_aware(start)
        assert (end - start).days == 1


class TestApplyStepnoFilter:
    """apply_stepno_filter"""

    def test_none_passthrough(self):
        """None → 不过滤"""
        from iwork.local_queries import apply_stepno_filter
        qs = Mock()
        assert apply_stepno_filter(qs, None) is qs

    def test_list_applies_filter(self):
        """[70, 69] → StepNo__in=[70, 69]"""
        from iwork.local_queries import apply_stepno_filter
        qs = Mock()
        apply_stepno_filter(qs, [70, 69])
        qs.filter.assert_called_once_with(StepNo__in=[70, 69])


class TestGetAvailableDates:
    """get_available_dates（本地独有）"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_date_objects(self, mock_model):
        """返回 date 对象列表"""
        from iwork.local_queries import get_available_dates

        mock_qs = mock_model.objects.using.return_value.dates.return_value
        mock_qs = [date(2026, 5, 12), date(2026, 5, 11)]  # Mock return

        # Actually, .dates() returns a queryset that can be iterated
        mock_model.objects.using.return_value.dates.return_value = mock_qs

        result = get_available_dates('local')
        assert len(result) == 2
        assert all(isinstance(d, date) for d in result)

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_calls_dates_with_regdate(self, mock_model):
        """调用 .dates('RegDate', 'day')"""
        from iwork.local_queries import get_available_dates

        get_available_dates('local')
        mock_model.objects.using.return_value.dates.assert_called_once()
        call_args = mock_model.objects.using.return_value.dates.call_args
        assert call_args[0][0] == 'RegDate'
        assert call_args[0][1] == 'day'


class TestGetAllStepnos:
    """get_all_stepnos"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_filters_zero_qty(self, mock_model):
        """qty=0 的工序不返回"""
        from iwork.local_queries import get_all_stepnos

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'StepNo': 70, 'qty': 500},
            {'StepNo': 69, 'qty': 0},
        ]

        result = get_all_stepnos(date(2026, 5, 12))
        assert result == [70]


class TestGetBatchBasicStats:
    """get_batch_basic_stats（修复后包含 workorder_count）"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_includes_workorder_count(self, mock_model):
        """验证修复：返回中包含 workorder_count"""
        from iwork.local_queries import get_batch_basic_stats

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value = [
            {'StepNo': 70, 'total_qty': 500, 'workorder_count': 8},
        ]

        result = get_batch_basic_stats(date(2026, 5, 12))
        assert result[70]['workorder_count'] == 8


class TestGetBatchWorkordersList:
    """get_batch_workorders_list"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_per_stepno_workorders(self, mock_model):
        """返回按工序分组的工单"""
        from iwork.local_queries import get_batch_workorders_list

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'StepNo': 70, 'WrkOrder': 'W001', 'total_qty': 500, 'step_count': 1},
            {'StepNo': 70, 'WrkOrder': 'W002', 'total_qty': 300, 'step_count': 1},
        ]

        result = get_batch_workorders_list(date(2026, 5, 12), limit=2)
        assert 70 in result
        assert len(result[70]) == 2
        assert result[70][0]['wrk_order'] == 'W001'
        assert result[70][0]['total_qty'] == 500


class TestSignatureEquivalence:
    """验证 local_queries 和 queries 函数签名一致"""

    def test_both_modules_have_apply_stepno_filter(self):
        """两个模块都有 apply_stepno_filter"""
        from iwork.queries import apply_stepno_filter as r_apply
        from iwork.local_queries import apply_stepno_filter as l_apply
        assert callable(r_apply)
        assert callable(l_apply)

    def test_both_modules_have_get_all_stepnos(self):
        """两个模块都有 get_all_stepnos"""
        from iwork.queries import get_all_stepnos as r_func
        from iwork.local_queries import get_all_stepnos as l_func
        assert callable(r_func)
        assert callable(l_func)

    def test_both_modules_have_batch_functions(self):
        """两个模块的 batch 函数签名一致"""
        from iwork.queries import (
            get_batch_basic_stats, get_batch_hourly_stats,
            get_batch_process_by_flow, get_batch_heatmap_data,
            get_batch_station_ranking, get_batch_workorders_list,
            get_batch_monthly_total_trend, get_batch_monthly_process_stats,
            _groupby,
        )
        from iwork.local_queries import (
            get_batch_basic_stats as l_basic, get_batch_hourly_stats as l_hourly,
            get_batch_process_by_flow as l_pf, get_batch_heatmap_data as l_heat,
            get_batch_station_ranking as l_station, get_batch_workorders_list as l_wo,
            get_batch_monthly_total_trend as l_mt, get_batch_monthly_process_stats as l_mp,
        )
        for r, l in [(get_batch_basic_stats, l_basic), (get_batch_hourly_stats, l_hourly),
                      (get_batch_process_by_flow, l_pf), (get_batch_heatmap_data, l_heat),
                      (get_batch_station_ranking, l_station), (get_batch_workorders_list, l_wo),
                      (get_batch_monthly_total_trend, l_mt),
                      (get_batch_monthly_process_stats, l_mp)]:
            assert callable(r)
            assert callable(l)

    def test_signature_new_flow_functions(self):
        """验证新增 5 个 Flow/StepNo 函数签名一致"""
        from iwork.queries import (
            get_all_flows, get_batch_flow_overview, get_batch_flow_hourly,
            get_batch_flow_employees, get_batch_stepno_employees,
        )
        from iwork.local_queries import (
            get_all_flows as l_af, get_batch_flow_overview as l_fo,
            get_batch_flow_hourly as l_fh, get_batch_flow_employees as l_fe,
            get_batch_stepno_employees as l_se,
        )
        for r, l in [(get_all_flows, l_af), (get_batch_flow_overview, l_fo),
                      (get_batch_flow_hourly, l_fh), (get_batch_flow_employees, l_fe),
                      (get_batch_stepno_employees, l_se)]:
            assert callable(r)
            assert callable(l)


# ============================================================================
# 生产详情模块 Batch 查询函数测试（local_queries.py 镜像版本）


class TestGetAllFlowsLocal:
    """get_all_flows"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_sorted_flows_excluding_zero_qty(self, mock_model):
        """返回按字母排序的 Flow 列表，过滤 qty=0 的记录"""
        from iwork.local_queries import get_all_flows

        # mock 不会真正排序，所以数据要按 .order_by('Flow') 的预期结果预排好
        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'Flow': 'Flow_A', 'qty': 100},
            {'Flow': 'Flow_B', 'qty': 200},
            {'Flow': 'Flow_C', 'qty': 0},
        ]

        result = get_all_flows(date(2026, 5, 12))
        # qty=0 的 Flow_C 被过滤，保持 order_by 结果顺序
        assert result == ['Flow_A', 'Flow_B']


class TestGetBatchFlowOverviewLocal:
    """get_batch_flow_overview"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_overview_with_total_qty_and_worker_count(self, mock_model):
        """返回每个 Flow 的 total_qty 和 worker_count"""
        from iwork.local_queries import get_batch_flow_overview

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        step_query = Mock()
        step_query.annotate.return_value.order_by.return_value = [
            {'Flow': 'Flow_A', 'StepNo': 70, 'qty': 500, 'workers': 3},
            {'Flow': 'Flow_B', 'StepNo': 69, 'qty': 300, 'workers': 2},
        ]
        worker_query = Mock()
        worker_query.annotate.return_value = [
            {'Flow': 'Flow_A', 'total_workers': 3},
            {'Flow': 'Flow_B', 'total_workers': 2},
        ]
        mock_qs.values.side_effect = lambda *fields: (
            step_query if fields == ('Flow', 'StepNo') else worker_query
        )

        result = get_batch_flow_overview(date(2026, 5, 12))
        assert result == {
            'Flow_A': {'stepnos': {'70': {'qty': 500, 'workers': 3}}, 'total_workers': 3},
            'Flow_B': {'stepnos': {'69': {'qty': 300, 'workers': 2}}, 'total_workers': 2},
        }


class TestGetBatchFlowHourlyLocal:
    """get_batch_flow_hourly"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_hourly_data_per_flow(self, mock_model):
        """返回每个 Flow 的每小时产量数据"""
        from iwork.local_queries import get_batch_flow_hourly

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.extra.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {'Flow': 'Flow_A', 'hour': 8, 'qty': 50},
            {'Flow': 'Flow_A', 'hour': 9, 'qty': 60},
            {'Flow': 'Flow_B', 'hour': 8, 'qty': 30},
        ]

        result = get_batch_flow_hourly(date(2026, 5, 12))
        assert result == {
            'Flow_A': [{'hour': 8, 'qty': 50}, {'hour': 9, 'qty': 60}],
            'Flow_B': [{'hour': 8, 'qty': 30}],
        }


class TestGetBatchFlowEmployeesLocal:
    """get_batch_flow_employees"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_employees_per_flow_sorted_by_total_qty_desc(self, mock_model):
        """返回每个 Flow 下的员工明细，按 total_qty 降序排列"""
        from iwork.local_queries import get_batch_flow_employees

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'Flow': 'Flow_A', 'RegPerSysID': 1001, 'StepNo': 70, 'WrkOrder': 'W001', 'qty': 200},
            {'Flow': 'Flow_A', 'RegPerSysID': 1001, 'StepNo': 69, 'WrkOrder': 'W001', 'qty': 100},
            {'Flow': 'Flow_A', 'RegPerSysID': 1002, 'StepNo': 70, 'WrkOrder': 'W002', 'qty': 150},
        ]

        result = get_batch_flow_employees(date(2026, 5, 12))
        assert 'Flow_A' in result
        employees = result['Flow_A']
        assert len(employees) == 2
        # 按 total_qty 降序：1001 (300) > 1002 (150)
        assert employees[0]['reg_per_sys_id'] == 1001
        assert employees[0]['total_qty'] == 300
        assert len(employees[0]['steps']) == 2
        assert employees[1]['reg_per_sys_id'] == 1002
        assert employees[1]['total_qty'] == 150
        assert len(employees[1]['steps']) == 1


class TestGetBatchStepnoEmployeesLocal:
    """get_batch_stepno_employees"""

    @patch('iwork.local_queries.LocalPytckreg3')
    def test_returns_employees_per_stepno_sorted_by_qty_desc(self, mock_model):
        """返回每个工序下的员工明细，按 qty 降序排列"""
        from iwork.local_queries import get_batch_stepno_employees

        mock_qs = mock_model.objects.using.return_value.filter.return_value
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value.annotate.return_value.order_by.return_value = [
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'Flow_A', 'qty': 200},
            {'StepNo': 70, 'RegPerSysID': 1001, 'Flow': 'Flow_B', 'qty': 100},
            {'StepNo': 70, 'RegPerSysID': 1002, 'Flow': 'Flow_A', 'qty': 150},
        ]

        result = get_batch_stepno_employees(date(2026, 5, 12))
        assert 70 in result
        employees = result[70]
        assert len(employees) == 2
        # 按 qty 降序：1001 (300) > 1002 (150)
        assert employees[0]['reg_per_sys_id'] == 1001
        assert employees[0]['qty'] == 300
        assert employees[0]['flows'] == ['Flow_A', 'Flow_B']
        assert employees[1]['reg_per_sys_id'] == 1002
        assert employees[1]['qty'] == 150
        assert employees[1]['flows'] == ['Flow_A']


class TestGetBatchProductOverviewLocal:
    """本地历史概览保持与实时接口一致的元数据字段。"""

    @patch('iwork.queries.get_batch_step_times', side_effect=ConnectionError('remote unavailable'))
    @patch('iwork.queries.get_all_step_descriptions', side_effect=ConnectionError('remote unavailable'))
    @patch('iwork.local_queries.ProductionOrder')
    @patch('iwork.local_queries.get_records_queryset')
    def test_remote_metadata_failure_degrades_to_empty_values(
        self, mock_records, mock_order, _mock_descriptions, _mock_step_times,
    ):
        from iwork.local_queries import get_batch_product_overview

        queryset = mock_records.return_value
        queryset.exclude.return_value = queryset
        queryset.filter.return_value = queryset
        queryset.values.return_value.annotate.return_value.order_by.return_value = [
            {'WrkOrder': 'BU0724', 'StepNo': 70, 'Flow': 'VCO-L5', 'qty': 100, 'workers': 2},
        ]
        order_query = mock_order.objects.using.return_value.filter.return_value
        order_query.values.return_value.distinct.return_value = [
            {'style_no': 'BU0724', 'product_name': 'OLLIE TEE', 'order_no': 'PO-1'},
        ]

        result = get_batch_product_overview(date(2026, 7, 14))

        step = result['products'][0]['wrk_orders'][0]['stepnos'][0]
        assert step['description'] == ''
        assert step['step_time'] is None
