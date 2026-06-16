"""
产量看板查询函数测试
"""
import pytest
from unittest.mock import Mock, patch, call
from datetime import date


class TestApplyKanbanFilters:
    """_apply_kanban_filters 单元测试"""

    def test_no_filters_returns_unchanged(self):
        """无筛选条件时返回原 QuerySet"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        result = _apply_kanban_filters(qs)
        assert result is qs
        qs.filter.assert_not_called()

    def test_none_values_not_filtered(self):
        """None 和空字符串不触发过滤"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        result = _apply_kanban_filters(qs, stepno=None, wrk_order='', flows=[], reg_per_sys_id=None)
        assert result is qs
        qs.filter.assert_not_called()

    def test_stepno_filter_applied(self):
        """工序筛选正确添加 WHERE 条件"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        _apply_kanban_filters(qs, stepno='70')
        qs.filter.assert_called_once_with(StepNo='70')

    def test_wrk_order_filter_applied(self):
        """款号筛选"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        _apply_kanban_filters(qs, wrk_order='SO3-001')
        qs.filter.assert_called_once_with(WrkOrder='SO3-001')

    def test_flows_filter_applied(self):
        """分组多选筛选"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        _apply_kanban_filters(qs, flows=['SO3', 'SO5'])
        qs.filter.assert_called_once_with(Flow__in=['SO3', 'SO5'])

    def test_reg_per_sys_id_filter_applied(self):
        """员工筛选"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        _apply_kanban_filters(qs, reg_per_sys_id='12345')
        qs.filter.assert_called_once_with(RegPerSysID='12345')

    def test_all_filters_chained(self):
        """组合筛选全部生效（链式调用）"""
        from iwork.queries import _apply_kanban_filters
        qs = Mock()
        qs.filter.return_value = qs  # 链式调用
        _apply_kanban_filters(
            qs, stepno='70', wrk_order='SO3-001',
            flows=['SO3'], reg_per_sys_id='12345'
        )
        assert qs.filter.call_count == 4


class TestMergeWorkerRows:
    """_merge_worker_rows 单元测试"""

    def test_single_worker_single_row(self):
        """单工人单条记录直接返回"""
        from iwork.queries import _merge_worker_rows
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
        from iwork.queries import _merge_worker_rows
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
        from iwork.queries import _merge_worker_rows
        rows = [
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W1', 'Flow': 'F1', 'qty': 100},
            {'RegPerSysID': 'B', 'StepNo': '70', 'WrkOrder': 'W2', 'Flow': 'F2', 'qty': 200},
        ]
        result = _merge_worker_rows(rows)
        assert len(result) == 2

    def test_empty_rows_returns_empty(self):
        """空输入返回空列表"""
        from iwork.queries import _merge_worker_rows
        assert _merge_worker_rows([]) == []

    def test_worker_name_is_string_of_id(self):
        """worker_name 为 reg_per_sys_id 的字符串形式"""
        from iwork.queries import _merge_worker_rows
        rows = [{'RegPerSysID': 12345, 'StepNo': '70', 'WrkOrder': 'W1', 'Flow': 'F1', 'qty': 100}]
        result = _merge_worker_rows(rows)
        assert result[0]['worker_name'] == '12345'

    def test_production_accumulates_all_qty(self):
        """产量汇总所有记录的 Qty（包括 None）"""
        from iwork.queries import _merge_worker_rows
        rows = [
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W1', 'Flow': 'F1', 'qty': 10},
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W2', 'Flow': 'F2', 'qty': None},
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'W3', 'Flow': 'F3', 'qty': 20},
        ]
        result = _merge_worker_rows(rows)
        assert result[0]['production'] == 30

    def test_best_qty_selects_max(self):
        """主字段来自 Qty 最大的记录"""
        from iwork.queries import _merge_worker_rows
        rows = [
            {'RegPerSysID': 'A', 'StepNo': '70', 'WrkOrder': 'SMALL', 'Flow': 'F1', 'qty': 10},
            {'RegPerSysID': 'A', 'StepNo': '80', 'WrkOrder': 'BIG', 'Flow': 'F2', 'qty': 200},
        ]
        result = _merge_worker_rows(rows)
        assert result[0]['wrk_order'] == 'BIG'
        assert result[0]['stepno'] == '80'
        assert result[0]['flow'] == 'F2'


class TestKanbanStats:
    """get_kanban_stats 单元测试（Mock DB）"""

    @patch('iwork.queries.get_records_queryset')
    def test_stats_returns_correct_structure(self, mock_get_records):
        """返回值包含所有必需字段"""
        from iwork.queries import get_kanban_stats
        from django.db.models import QuerySet
        from unittest.mock import MagicMock

        # 构造 Mock QuerySet 链
        mock_qs = MagicMock(spec=QuerySet)
        mock_get_records.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs

        # values().annotate() 返回的 QuerySet
        mock_worker_qs = MagicMock(spec=QuerySet)
        mock_qs.values.return_value = mock_worker_qs
        mock_worker_qs.annotate.return_value = mock_worker_qs

        # aggregate() 返回
        mock_worker_qs.aggregate.return_value = {
            'worker_count': 5,
            'total_production': 500,
            'max_production': 150,
        }
        # order_by().first() 返回
        mock_worker_qs.order_by.return_value = mock_worker_qs
        mock_worker_qs.first.return_value = {'RegPerSysID': '99999'}

        result = get_kanban_stats(date(2026, 6, 16), stepno='70')

        assert result['worker_count'] == 5
        assert result['total_production'] == 500
        assert result['avg_production'] == 100  # 500/5
        assert result['max_production'] == 150
        assert result['max_worker_name'] == '99999'

    @patch('iwork.queries.get_records_queryset')
    def test_stats_no_results_returns_zeros(self, mock_get_records):
        """无匹配数据时返回零值"""
        from iwork.queries import get_kanban_stats
        from django.db.models import QuerySet
        from unittest.mock import MagicMock

        mock_qs = MagicMock(spec=QuerySet)
        mock_get_records.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_worker_qs = MagicMock(spec=QuerySet)
        mock_qs.values.return_value = mock_worker_qs
        mock_worker_qs.annotate.return_value = mock_worker_qs
        mock_worker_qs.aggregate.return_value = {
            'worker_count': 0,
            'total_production': 0,
            'max_production': 0,
        }
        mock_worker_qs.order_by.return_value = mock_worker_qs
        mock_worker_qs.first.return_value = None

        result = get_kanban_stats(date(2026, 6, 16), stepno='99999')

        assert result['worker_count'] == 0
        assert result['total_production'] == 0
        assert result['avg_production'] == 0
        assert result['max_production'] == 0
        assert result['max_worker_name'] == ''


class TestKanbanRanking:
    """get_kanban_ranking 单元测试（Mock DB）"""

    @patch('iwork.queries.get_records_queryset')
    @patch('iwork.queries._merge_worker_rows')
    def test_ranking_returns_correct_structure(self, mock_merge, mock_get_records):
        """返回值包含 pagination 和 workers"""
        from iwork.queries import get_kanban_ranking
        from unittest.mock import MagicMock

        mock_qs = MagicMock()
        mock_get_records.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.__iter__.return_value = iter([])  # 空结果
        mock_merge.return_value = []

        result = get_kanban_ranking(date(2026, 6, 16), stepno='70')

        assert 'pagination' in result
        assert 'workers' in result
        assert result['pagination']['page'] == 1
        assert result['pagination']['page_size'] == 50
        assert result['pagination']['total_count'] == 0
        assert result['pagination']['total_pages'] == 1
        assert result['workers'] == []

    @patch('iwork.queries.get_records_queryset')
    @patch('iwork.queries._merge_worker_rows')
    def test_ranking_workers_have_rank(self, mock_merge, mock_get_records):
        """workers 被注入 rank 字段"""
        from iwork.queries import get_kanban_ranking
        from unittest.mock import MagicMock

        mock_qs = MagicMock()
        mock_get_records.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.__iter__.return_value = iter([])
        mock_merge.return_value = [
            {'reg_per_sys_id': 'A', 'worker_name': 'A', 'stepno': '70',
             'wrk_order': 'W1', 'flow': 'F1', 'production': 100},
            {'reg_per_sys_id': 'B', 'worker_name': 'B', 'stepno': '70',
             'wrk_order': 'W2', 'flow': 'F2', 'production': 80},
        ]

        result = get_kanban_ranking(date(2026, 6, 16), stepno='70')

        assert result['workers'][0]['rank'] == 1
        assert result['workers'][1]['rank'] == 2
        assert result['pagination']['total_count'] == 2

    @patch('iwork.queries.get_records_queryset')
    @patch('iwork.queries._merge_worker_rows')
    def test_ranking_pagination_page_size(self, mock_merge, mock_get_records):
        """分页大小生效，第二页 offset 正确"""
        from iwork.queries import get_kanban_ranking
        from unittest.mock import MagicMock

        mock_qs = MagicMock()
        mock_get_records.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.__iter__.return_value = iter([])

        # 模拟 55 个工人
        workers = [{'reg_per_sys_id': str(i), 'worker_name': str(i),
                     'stepno': '70', 'wrk_order': 'W', 'flow': 'F',
                     'production': 100 - i} for i in range(55)]
        mock_merge.return_value = workers

        # 第一页
        result_p1 = get_kanban_ranking(date(2026, 6, 16), stepno='70', page=1, page_size=50)
        assert len(result_p1['workers']) == 50
        assert result_p1['pagination']['total_pages'] == 2
        assert result_p1['pagination']['total_count'] == 55

        # 第二页
        result_p2 = get_kanban_ranking(date(2026, 6, 16), stepno='70', page=2, page_size=50)
        assert len(result_p2['workers']) == 5
        assert result_p2['workers'][0]['rank'] == 51


class TestKanbanFilterOptions:
    """get_kanban_filter_options 单元测试（Mock DB）"""

    @patch('iwork.queries.get_records_queryset')
    def test_filter_options_returns_required_keys(self, mock_get_records):
        """返回值包含所有筛选项键（空数据情况）"""
        from iwork.queries import get_kanban_filter_options
        from unittest.mock import MagicMock

        mock_qs = MagicMock()
        mock_get_records.return_value = mock_qs
        # 链式调用都返回自身，list() 遍历空列表
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.__iter__.return_value = iter([])

        result = get_kanban_filter_options(date(2026, 6, 16))

        assert 'stepnos' in result
        assert 'wrk_orders' in result
        assert 'flows' in result
        assert 'employees' in result
        assert result['stepnos'] == []
        assert result['employees'] == []

    @patch('iwork.queries.get_records_queryset')
    def test_employees_have_id_and_name(self, mock_get_records):
        """员工列表包含 id 和 name"""
        from iwork.queries import get_kanban_filter_options
        from unittest.mock import MagicMock

        mock_qs = MagicMock()
        mock_get_records.return_value = mock_qs
        mock_qs.values_list.return_value = mock_qs
        mock_qs.distinct.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs

        mock_qs.__iter__.side_effect = [
            iter([]),  # stepnos
            iter([]),  # wrk_orders
            iter([]),  # flows
            iter([{'RegPerSysID': 12345, 'qty': 100}]),  # employees
        ]

        result = get_kanban_filter_options(date(2026, 6, 16))

        if result['employees']:
            emp = result['employees'][0]
            assert 'reg_per_sys_id' in emp
            assert 'name' in emp
            assert emp['name'] == '12345'
