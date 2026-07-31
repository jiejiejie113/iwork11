"""
统一查询引擎 _get_date_stats 测试

验证：
  1. 返回 dict 包含全部 12 个字段
  2. 远程/本地双路径均能正常返回
  3. stepno_filter 透传正确
  4. stepno_list 为空时不崩溃
"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch, MagicMock


def _make_mock_stats():
    """构造模拟的查询函数返回数据"""
    return {
        'basic': {'workorder_count': 42, 'total_qty': 5280},
        'process': [
            {'step': 70, 'qty': 1000}, {'step': 69, 'qty': 800},
            {'step': 68, 'qty': 600}, {'step': 67, 'qty': 500},
            {'step': 66, 'qty': 400}, {'step': 65, 'qty': 300},
            {'step': 64, 'qty': 200}, {'step': 63, 'qty': 100},
        ],
        'hourly': [{'hour': 8, 'qty': 500}, {'hour': 9, 'qty': 800}],
        'process_flow': [
            {'step': 70, 'flow': 'A', 'qty': 600},
            {'step': 70, 'flow': 'B', 'qty': 400},
        ],
        'monthly_total': [{'date': '2026-05-01', 'qty': 5000}, {'date': '2026-05-09', 'qty': 5280}],
        'monthly_process': [
            {'date': '2026-05-01', 'step': 70, 'qty': 800},
            {'date': '2026-05-09', 'step': 70, 'qty': 1000},
        ],
        'heatmap': {'hours': [8, 9], 'flows': ['A', 'B'], 'data': [[100, 200], [300, 400]]},
        'station': [{'station': 'S01', 'qty': 2000}, {'station': 'S02', 'qty': 1500}],
        'workorders': [{'wrk_order': 'WO001', 'total_qty': 500, 'step_count': 3}],
    }


class TestUnifiedEngine:
    """_get_date_stats 核心逻辑测试"""

    def setup_method(self):
        """每个批量构建测试前清空缓存。"""
        """每个测试前清理缓存，避免跨测试缓存污染"""
        from django.core.cache import cache
        cache.clear()

    def test_all_fields_present(self):
        """验证返回 dict 包含全部 12 个字段"""
        from iwork.statistics import _get_date_stats

        mock_q = MagicMock()
        mock_q.get_basic_stats.return_value = _make_mock_stats()['basic']
        mock_q.get_process_stats.return_value = _make_mock_stats()['process']
        mock_q.get_hourly_stats.return_value = _make_mock_stats()['hourly']
        mock_q.get_process_by_flow.return_value = _make_mock_stats()['process_flow']
        mock_q.get_monthly_total_trend.return_value = _make_mock_stats()['monthly_total']
        mock_q.get_monthly_process_stats.return_value = _make_mock_stats()['monthly_process']
        mock_q.get_heatmap_data.return_value = _make_mock_stats()['heatmap']
        mock_q.get_station_ranking.return_value = _make_mock_stats()['station']
        mock_q.get_workorders_list.return_value = _make_mock_stats()['workorders']

        result = _get_date_stats(date(2026, 5, 9), [70], mock_q)

        required_keys = [
            'workorder_count', 'total_qty', 'date',
            'hourly_stats', 'process_flow_stats',
            'monthly_process_stats', 'monthly_total_trend',
            'station_stats', 'heatmap_matrix', 'station_ranking',
            'top_processes', 'workorders',
        ]
        for key in required_keys:
            assert key in result, f"缺少字段: {key}"

    def test_station_merge(self):
        """验证工站分布 slice[:10] 和工站排行共用一次查询"""
        from iwork.statistics import _get_date_stats

        mock_q = MagicMock()
        mock_q.get_basic_stats.return_value = {'workorder_count': 10, 'total_qty': 100}
        mock_q.get_process_stats.return_value = _make_mock_stats()['process']
        mock_q.get_hourly_stats.return_value = []
        mock_q.get_process_by_flow.return_value = []
        mock_q.get_monthly_total_trend.return_value = []
        mock_q.get_monthly_process_stats.return_value = []
        mock_q.get_heatmap_data.return_value = {'hours': [], 'flows': [], 'data': []}
        mock_q.get_workorders_list.return_value = []

        station_full = [{'station': f'S{i:02d}', 'qty': 1000 - i * 50} for i in range(15)]
        mock_q.get_station_ranking.return_value = station_full

        result = _get_date_stats(date(2026, 5, 9), None, mock_q)

        # 主题4 工站分布用前10
        assert len(result['station_stats']) == 10
        # 主题6 工站排行用全部15
        assert len(result['station_ranking']) == 15
        # 确认是同一个查询（只调用一次）
        assert mock_q.get_station_ranking.call_count == 1

    def test_empty_process_list(self):
        """验证 stepno_list 为空时，依赖它的查询被跳过，不崩溃"""
        from iwork.statistics import _get_date_stats

        mock_q = MagicMock()
        mock_q.get_basic_stats.return_value = {'workorder_count': 0, 'total_qty': 0}
        mock_q.get_process_stats.return_value = []  # 无工序数据
        mock_q.get_hourly_stats.return_value = []
        mock_q.get_monthly_total_trend.return_value = []
        mock_q.get_heatmap_data.return_value = {'hours': [], 'flows': [], 'data': []}
        mock_q.get_station_ranking.return_value = []
        mock_q.get_workorders_list.return_value = []

        result = _get_date_stats(date(2026, 5, 9), None, mock_q)

        assert result['process_flow_stats'] == []
        assert result['monthly_process_stats'] == []
        assert result['workorder_count'] == 0
        # 确认依赖 stepno_list 的函数没有被调用
        mock_q.get_process_by_flow.assert_not_called()
        mock_q.get_monthly_process_stats.assert_not_called()

    def test_stepno_filter_transmitted(self):
        """验证 stepno_filter 透传到每个查询函数"""
        from iwork.statistics import _get_date_stats

        mock_q = MagicMock()
        mock_q.get_basic_stats.return_value = {'workorder_count': 5, 'total_qty': 200}
        mock_q.get_process_stats.return_value = [{'step': 70, 'qty': 200}]
        mock_q.get_hourly_stats.return_value = []
        mock_q.get_process_by_flow.return_value = []
        mock_q.get_monthly_total_trend.return_value = []
        mock_q.get_monthly_process_stats.return_value = []
        mock_q.get_heatmap_data.return_value = {'hours': [], 'flows': [], 'data': []}
        mock_q.get_station_ranking.return_value = []
        mock_q.get_workorders_list.return_value = []

        _get_date_stats(date(2026, 5, 9), [70, 69], mock_q)

        # 确认各查询函数被调用时传入了 stepno_filter
        mock_q.get_basic_stats.assert_called_with(date(2026, 5, 9), stepno_filter=[70, 69])
        mock_q.get_process_stats.assert_called_with(date(2026, 5, 9), limit=9999, stepno_filter=[70, 69])
        mock_q.get_hourly_stats.assert_called_with(date(2026, 5, 9), stepno_filter=[70, 69])
        mock_q.get_process_by_flow.assert_called_with(date(2026, 5, 9), [70])
        mock_q.get_station_ranking.assert_called_with(date(2026, 5, 9), stepno_filter=[70, 69])

    def test_date_passed_correctly(self):
        """验证 target_date 正确传递给查询函数（而非 today()）"""
        from iwork.statistics import _get_date_stats

        mock_q = MagicMock()
        mock_q.get_basic_stats.return_value = {'workorder_count': 1, 'total_qty': 10}
        mock_q.get_process_stats.return_value = [{'step': 70, 'qty': 10}]
        mock_q.get_hourly_stats.return_value = []
        mock_q.get_process_by_flow.return_value = []
        mock_q.get_monthly_total_trend.return_value = []
        mock_q.get_monthly_process_stats.return_value = []
        mock_q.get_heatmap_data.return_value = {'hours': [], 'flows': [], 'data': []}
        mock_q.get_station_ranking.return_value = []
        mock_q.get_workorders_list.return_value = []

        target = date(2026, 4, 24)
        result = _get_date_stats(target, None, mock_q)

        # 确认 date 字段是传入的日期
        assert result['date'] == target
        # 确认查询函数收到的是指定日期
        mock_q.get_basic_stats.assert_called_with(target, stepno_filter=None)

    def test_monthly_keys_unique_per_date_and_filter(self):
        """验证月查询缓存键按日期和工序过滤区分，不同参数不串数据"""
        from iwork.statistics import _get_date_stats
        from django.core.cache import cache

        # 清理缓存确保测试隔离
        cache.clear()

        mock_q = MagicMock()
        mock_q.get_basic_stats.return_value = {'workorder_count': 1, 'total_qty': 10}
        mock_q.get_process_stats.return_value = [{'step': 70, 'qty': 10}]
        mock_q.get_hourly_stats.return_value = []
        mock_q.get_process_by_flow.return_value = []
        mock_q.get_monthly_total_trend.return_value = []
        mock_q.get_monthly_process_stats.return_value = []
        mock_q.get_heatmap_data.return_value = {'hours': [], 'flows': [], 'data': []}
        mock_q.get_station_ranking.return_value = []
        mock_q.get_workorders_list.return_value = []

        # 用不同 stepno_filter 调用同一日期
        # 第一次：[70] → 缓存键 monthly_trend:20265_70
        _get_date_stats(date(2026, 5, 9), [70], mock_q)
        # 第二次：[69] → 缓存键 monthly_trend:20265_69（不同键，应再次触发查询）
        _get_date_stats(date(2026, 5, 9), [69], mock_q)

        assert mock_q.get_monthly_total_trend.call_count == 2, (
            f"期望调用2次，实际{ mock_q.get_monthly_total_trend.call_count}次"
        )
        assert mock_q.get_monthly_process_stats.call_count == 2


class TestPublicAPI:
    """公开 API 入口测试"""

    def test_get_today_stats_delegates(self):
        """get_today_stats 委托给版本化实时读模型入口。"""
        from iwork.statistics import get_today_stats
        from unittest.mock import patch

        mock_result = {'workorder_count': 1, 'total_qty': 10}
        with patch('iwork.statistics.get_realtime_stats', return_value=mock_result) as mock_fn:
            result = get_today_stats([70])

        mock_fn.assert_called_once_with([70])
        assert result is mock_result

    def test_get_date_stats_uses_remote_module(self):
        """get_date_stats 使用 remote_q 模块"""
        from iwork.statistics import get_date_stats
        from django.core.cache import cache
        from unittest.mock import patch

        cache.clear()
        mock_result = {'total_qty': 100, 'date': date(2026, 5, 9)}

        with patch('iwork.statistics._get_date_stats', return_value=mock_result) as mock_engine:
            result = get_date_stats(date(2026, 5, 9), [70])

        mock_engine.assert_called_once()
        call_args = mock_engine.call_args
        assert call_args[0][0] == date(2026, 5, 9)
        assert call_args[0][1] == [70]
        assert call_args[0][2].__name__ == 'iwork.queries'
        assert result == mock_result

    def test_get_local_date_stats_uses_local_module(self):
        """get_local_date_stats 使用 local_q 模块"""
        from iwork.statistics import get_local_date_stats
        from django.core.cache import cache
        from unittest.mock import patch

        cache.clear()
        mock_result = {'total_qty': 100, 'date': date(2026, 5, 9)}

        with patch('iwork.statistics._get_date_stats', return_value=mock_result) as mock_engine:
            result = get_local_date_stats(date(2026, 5, 9), [70])

        mock_engine.assert_called_once()
        call_args = mock_engine.call_args
        assert call_args[0][2].__name__ == 'iwork.local_queries'
        assert result == mock_result

    def test_local_module_has_all_required_functions(self):
        """验证 local_queries 模块包含 _get_date_stats 所需的全部函数"""
        import iwork.local_queries as local_q

        required = [
            'get_basic_stats', 'get_process_stats', 'get_hourly_stats',
            'get_process_by_flow', 'get_monthly_total_trend',
            'get_monthly_process_stats', 'get_heatmap_data',
            'get_station_ranking', 'get_workorders_list',
        ]
        for name in required:
            assert hasattr(local_q, name), f"local_queries 缺少函数: {name}"
            assert callable(getattr(local_q, name)), f"local_queries.{name} 不可调用"

    def test_remote_module_has_all_required_functions(self):
        """验证 queries 模块包含 _get_date_stats 所需的全部函数"""
        import iwork.queries as remote_q

        required = [
            'get_basic_stats', 'get_process_stats', 'get_hourly_stats',
            'get_process_by_flow', 'get_monthly_total_trend',
            'get_monthly_process_stats', 'get_heatmap_data',
            'get_station_ranking', 'get_workorders_list',
        ]
        for name in required:
            assert hasattr(remote_q, name), f"queries 缺少函数: {name}"
            assert callable(getattr(remote_q, name)), f"queries.{name} 不可调用"

    def test_both_modules_have_matching_signatures(self):
        """验证两个模块的对应函数签名一致（参数名相同）"""
        import iwork.queries as remote_q
        import iwork.local_queries as local_q
        import inspect

        functions_to_check = [
            'get_basic_stats', 'get_process_stats', 'get_hourly_stats',
            'get_process_by_flow', 'get_monthly_total_trend',
            'get_monthly_process_stats', 'get_heatmap_data',
            'get_station_ranking', 'get_workorders_list',
        ]
        for name in functions_to_check:
            r_fn = getattr(remote_q, name)
            l_fn = getattr(local_q, name)
            r_params = list(inspect.signature(r_fn).parameters.keys())
            l_params = list(inspect.signature(l_fn).parameters.keys())
            assert r_params == l_params, (
                f"{name}: 远程参数 {r_params} != 本地参数 {l_params}"
            )


class TestHistoryAPIResponse:
    """历史 API 响应结构测试 —— 模拟真实 HTTP 请求"""

    def test_legacy_remote_mode_still_returns_local_snapshot_fields(self):
        """旧 mode=remote 参数不会绕过本地快照，且字段保持完整。"""
        from iwork.api_views_local import local_date_stats
        from rest_framework.test import APIRequestFactory
        from unittest.mock import patch

        mock_full = {
            'workorder_count': 30, 'total_qty': 4000,
            'date': date(2026, 5, 9),
            'hourly_stats': [{'hour': 8, 'qty': 500}],
            'station_stats': [{'station': 'S01', 'qty': 1000}],
            'workorders': [{'wrk_order': 'WO001', 'total_qty': 500, 'step_count': 3}],
            'process_flow_stats': [{'step': 70, 'flow': 'A', 'qty': 600}],
            'monthly_process_stats': [{'date': '2026-05-09', 'step': 70, 'qty': 1000}],
            'monthly_total_trend': [{'date': '2026-05-01', 'qty': 5000}],
            'heatmap_matrix': {'hours': [8], 'flows': ['A'], 'data': [[100]]},
            'station_ranking': [{'station': 'S01', 'qty': 1000}],
            'top_processes': [{'step': 70, 'qty': 1000}],
        }

        factory = APIRequestFactory()
        request = factory.get('/api/history/date/2026-05-09/?mode=remote&stepno=70')

        with patch(
            'iwork.api_views_local._snapshot_state',
            return_value=SimpleNamespace(snapshot_version=1, completed_at=None),
        ), patch('iwork.api_views_local.get_local_date_stats', return_value=mock_full):
            response = local_date_stats(request, '2026-05-09')

        assert response.status_code == 200
        data = response.data
        assert data['source'] == 'local_snapshot'

        chart_fields = [
            'hourly_stats', 'station_stats', 'workorders',
            'process_flow_stats', 'monthly_process_stats',
            'monthly_total_trend', 'heatmap_matrix', 'station_ranking',
        ]
        for field in chart_fields:
            assert field in data, f"历史快照响应缺少字段: {field}"
            val = data[field]
            # 确保不是 None（热力图除外）
            if field != 'heatmap_matrix':
                assert val is not None, f"字段 {field} 为 None"

    def test_history_snapshot_returns_all_chart_fields(self):
        """历史快照返回全部图表字段。"""
        from iwork.api_views_local import local_date_stats
        from rest_framework.test import APIRequestFactory
        from unittest.mock import patch

        mock_full = {
            'workorder_count': 20, 'total_qty': 3000,
            'date': date(2026, 5, 9),
            'hourly_stats': [{'hour': 9, 'qty': 400}],
            'station_stats': [{'station': 'S02', 'qty': 800}],
            'workorders': [{'wrk_order': 'WO002', 'total_qty': 400, 'step_count': 2}],
            'process_flow_stats': [{'step': 69, 'flow': 'B', 'qty': 300}],
            'monthly_process_stats': [{'date': '2026-05-09', 'step': 69, 'qty': 800}],
            'monthly_total_trend': [{'date': '2026-05-01', 'qty': 4000}],
            'heatmap_matrix': {'hours': [9], 'flows': ['B'], 'data': [[200]]},
            'station_ranking': [{'station': 'S02', 'qty': 800}],
            'top_processes': [{'step': 69, 'qty': 800}],
        }

        factory = APIRequestFactory()
        request = factory.get('/api/history/date/2026-05-09/?mode=local')

        with patch(
            'iwork.api_views_local._snapshot_state',
            return_value=SimpleNamespace(snapshot_version=1, completed_at=None),
        ), patch('iwork.api_views_local.get_local_date_stats', return_value=mock_full):
            response = local_date_stats(request, '2026-05-09')

        assert response.status_code == 200
        data = response.data
        assert data['source'] == 'local_snapshot'

        chart_fields = [
            'hourly_stats', 'station_stats', 'workorders',
            'process_flow_stats', 'monthly_process_stats',
            'monthly_total_trend', 'heatmap_matrix', 'station_ranking',
        ]
        for field in chart_fields:
            assert field in data, f"local 响应缺少字段: {field}"


class TestRealDatabase:
    """真实数据库查询 —— 通过独立脚本运行，绕过 Django 测试框架的 test DB 创建限制

    运行方式（终端）：
      cd d:\\DM\\Python代码\\Seamus\\iwork
      python -X utf8 tests/test_unified_engine.py
    """

    TEST_DATE = date(2026, 5, 8)

    def test_real_db_placeholder(self):
        """占位：真实 DB 测试请运行独立脚本 `python tests/test_unified_engine.py`"""
        pass


# ====================================================================
# Batch 引擎 + 缓存层测试
# ====================================================================

def _make_batch_mock():
    """构造模拟的 batch 查询返回数据"""
    return {
        'basic': {
            70: {'total_qty': 5000, 'workorder_count': 3},
            69: {'total_qty': 3000, 'workorder_count': 2},
            68: {'total_qty': 2000, 'workorder_count': 1},
        },
        'hourly': {
            70: [{'hour': 8, 'qty': 2000}, {'hour': 9, 'qty': 3000}],
            69: [{'hour': 8, 'qty': 1000}],
        },
        'pf': {},
        'heatmap': {
            70: {'hours': [8, 9], 'flows': ['A'], 'data': [[100, 200]]},
        },
        'station': {
            70: [{'station': 'S01', 'qty': 3000}, {'station': 'S02', 'qty': 2000}],
            69: [{'station': 'S01', 'qty': 1000}],
        },
        'wo': {
            70: [{'wrk_order': 'WO001', 'total_qty': 3000, 'step_count': 3}],
        },
        'monthly_total': {70: [{'date': '2026-05-01', 'qty': 5000}]},
        'monthly_proc': {70: [{'date': '2026-05-01', 'step': 70, 'qty': 5000}]},
    }


class TestBatchEngine:
    """get_batch_stats 批量构建测试"""

    def setup_method(self):
        """每个批量构建测试前清空缓存。"""
        from django.core.cache import cache
        cache.clear()

    def test_batch_produces_per_stepno_dicts(self):
        """批量构建为每个工序生成独立 stats dict"""
        from iwork.statistics import get_batch_stats
        from unittest.mock import MagicMock

        bm = _make_batch_mock()
        mock_q = MagicMock()
        mock_q.get_batch_basic_stats.return_value = bm['basic']
        mock_q.get_batch_hourly_stats.return_value = bm['hourly']
        mock_q.get_batch_process_by_flow.return_value = bm['pf']
        mock_q.get_batch_heatmap_data.return_value = bm['heatmap']
        mock_q.get_batch_station_ranking.return_value = bm['station']
        mock_q.get_batch_workorders_list.return_value = bm['wo']
        mock_q.get_batch_monthly_total_trend.return_value = bm['monthly_total']
        mock_q.get_batch_monthly_process_stats.return_value = bm['monthly_proc']
        mock_q.get_batch_monthly_hourly_stats.return_value = {}

        batch = get_batch_stats(q=mock_q)

        # 每个工序都有独立 dict
        for stepno in [70, 69, 68]:
            assert stepno in batch, f"缺少工序 {stepno}"
            s = batch[stepno]
            assert s['total_qty'] > 0
            assert 'hourly_stats' in s
            assert 'heatmap_matrix' in s
            assert 'station_ranking' in s

        # 'all' 合并视图
        assert 'all' in batch
        assert batch['all']['total_qty'] == 5000 + 3000 + 2000

    def test_batch_all_merge_correct(self):
        """'all' 视图的 total_qty 是所有工序之和"""
        from iwork.statistics import get_batch_stats
        from unittest.mock import MagicMock

        bm = _make_batch_mock()
        mock_q = MagicMock()
        mock_q.get_batch_basic_stats.return_value = bm['basic']
        mock_q.get_batch_hourly_stats.return_value = bm['hourly']
        mock_q.get_batch_process_by_flow.return_value = bm['pf']
        mock_q.get_batch_heatmap_data.return_value = bm['heatmap']
        mock_q.get_batch_station_ranking.return_value = bm['station']
        mock_q.get_batch_workorders_list.return_value = bm['wo']
        mock_q.get_batch_monthly_total_trend.return_value = bm['monthly_total']
        mock_q.get_batch_monthly_process_stats.return_value = bm['monthly_proc']
        mock_q.get_batch_monthly_hourly_stats.return_value = {}

        batch = get_batch_stats(q=mock_q)

        assert batch['all']['total_qty'] == 10000
        assert len(batch['all']['station_ranking']) > 0
        assert len(batch['all']['hourly_stats']) > 0

    def test_empty_batch(self):
        """空数据不崩溃"""
        from iwork.statistics import get_batch_stats
        from unittest.mock import MagicMock

        mock_q = MagicMock()
        mock_q.get_batch_basic_stats.return_value = {}
        mock_q.get_batch_hourly_stats.return_value = {}
        mock_q.get_batch_process_by_flow.return_value = {}
        mock_q.get_batch_heatmap_data.return_value = {}
        mock_q.get_batch_station_ranking.return_value = {}
        mock_q.get_batch_workorders_list.return_value = {}
        mock_q.get_batch_monthly_total_trend.return_value = {}
        mock_q.get_batch_monthly_process_stats.return_value = {}
        mock_q.get_batch_monthly_hourly_stats.return_value = {}

        batch = get_batch_stats(q=mock_q)

        assert 'all' in batch
        assert batch['all']['total_qty'] == 0


class TestCacheLayer:
    """缓存读写 + 过期 + 清空测试"""

    def setup_method(self):
        """每个缓存层测试前清空缓存。"""
        from django.core.cache import cache
        cache.clear()

    def test_cache_batch_to_redis_sets_keys(self):
        """cache_batch_to_redis 为每个工序写入独立 key"""
        from iwork.statistics import cache_batch_to_redis
        from django.core.cache import cache

        batch = {
            70: {'total_qty': 100, 'date': date(2026, 5, 9)},
            69: {'total_qty': 50, 'date': date(2026, 5, 9)},
            'all': {'total_qty': 150, 'date': date(2026, 5, 9)},
        }

        cache_batch_to_redis(batch)

        assert cache.get('stats:realtime:70') is not None
        assert cache.get('stats:realtime:69') is not None
        assert cache.get('stats:realtime:all') is not None
        assert cache.get('stats:realtime:70')['total_qty'] == 100

    def test_get_realtime_stats_cache_hit(self):
        """get_realtime_stats 委托版本化读模型。"""
        from iwork.read_model.store import SnapshotReadResult
        from iwork.statistics import get_realtime_stats

        read_result = SnapshotReadResult(
            data={'total_qty': 999},
            metadata={},
            stale=False,
        )
        with patch(
            'iwork.read_model.queries.ReadModelQueries.realtime',
            return_value=read_result,
        ):
            result = get_realtime_stats([70])
        assert result['total_qty'] == 999

    def test_get_date_stats_queries_remote_without_history_cache(self):
        """远程历史查询每次实时执行，不读取旧历史缓存键。"""
        from iwork.statistics import get_date_stats
        from django.core.cache import cache

        cache.set('stats:date:2026-05-09:all', {'total_qty': 888, 'date': date(2026, 5, 9)}, 1800)

        expected = {'total_qty': 100, 'date': date(2026, 5, 9)}
        with patch('iwork.statistics._get_date_stats', return_value=expected) as engine:
            result = get_date_stats(date(2026, 5, 9), None)

        assert result is expected
        assert engine.call_args.kwargs['use_cache'] is False

    def test_get_local_date_stats_queries_local_without_history_cache(self):
        """本地历史查询每次实时执行，不读取旧历史缓存键。"""
        from iwork.statistics import get_local_date_stats
        from django.core.cache import cache

        cache.set('stats:local:date:2026-05-09:all', {'total_qty': 777, 'date': date(2026, 5, 9)}, 3600)

        expected = {'total_qty': 100, 'date': date(2026, 5, 9)}
        with patch('iwork.statistics._get_date_stats', return_value=expected) as engine:
            result = get_local_date_stats(date(2026, 5, 9), None)

        assert result is expected
        assert engine.call_args.kwargs['use_cache'] is False

    def test_invalidate_local_cache(self):
        """invalidate_local_cache 删除对应日期的本地缓存"""
        from iwork.statistics import invalidate_local_cache
        from django.core.cache import cache

        td = date(2026, 5, 9)
        cache.set(f'stats:local:date:{td.isoformat()}:all', {'data': 1}, 60)
        cache.set(f'stats:local:date:{td.isoformat()}:70', {'data': 2}, 60)
        cache.set(f'stats:local:date:{td.isoformat()}:69', {'data': 3}, 60)
        # 其他日期不应受影响
        cache.set('stats:local:date:2026-05-08:all', {'data': 4}, 60)

        invalidate_local_cache(td)

        assert cache.get(f'stats:local:date:{td.isoformat()}:all') is None
        assert cache.get(f'stats:local:date:{td.isoformat()}:70') is None
        assert cache.get(f'stats:local:date:{td.isoformat()}:69') is None
        # 其他日期保留
        assert cache.get('stats:local:date:2026-05-08:all') is not None

    def test_stepno_key_format(self):
        """工序缓存键后缀生成正确"""
        from iwork.statistics import _stepno_key

        assert _stepno_key(None) == 'all'
        assert _stepno_key([70]) == '70'
        assert _stepno_key([70, 69]) == '69_70'
        assert _stepno_key([69, 70]) == '69_70'  # 排序


class TestTasksNewFlow:
    """tasks.py 改用 batch 后的行为测试"""

    def test_snapshot_recent_history_skips_build_in_progress(self):
        """定时快照遇到同日期构建时应跳过并返回空结果。"""
        from unittest.mock import patch

        from iwork.history_store import SnapshotBuildInProgressError
        from iwork.tasks import snapshot_recent_history

        with patch(
            'iwork.tasks.get_business_date',
            return_value=date(2026, 7, 24),
        ), patch(
            'iwork.tasks.snapshot_history_date',
            side_effect=SnapshotBuildInProgressError('正在构建'),
        ) as build_snapshot:
            result = snapshot_recent_history(days=1)

        assert result == []
        build_snapshot.assert_called_once_with(date(2026, 7, 23))

# ============================================================
# 独立运行：真实数据库查询验证（绕过 pytest 的 test DB 限制）
# 用法: cd d:\DM\Python代码\Seamus\iwork && python -X utf8 tests\test_unified_engine.py
# ============================================================
if __name__ == "__main__":
    import os
    import sys

    from loguru import logger

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "iwork.settings")
    import django

    django.setup()

    from iwork.statistics import get_date_stats, get_local_date_stats
    from iwork.api_views_local import local_date_stats
    from rest_framework.test import APIRequestFactory

    TEST_DATE = date(2026, 5, 8)
    errors = []

    def check(description, condition):
        """记录独立诊断检查的通过或失败状态。"""
        status = "PASS" if condition else "FAIL"
        if not condition:
            errors.append(description)
        print(f"  [{status}] {description}")

    # ==== 1. get_date_stats remote + stepno=[70] ====
    print(f"\n{'='*60}")
    print(f"1. get_date_stats({TEST_DATE}, [70]) -- 远程库 stepno=70")
    print(f"{'='*60}")
    r1 = get_date_stats(TEST_DATE, [70])

    check("返回 dict", isinstance(r1, dict))
    required = ['workorder_count','total_qty','date','hourly_stats','process_flow_stats',
                'monthly_process_stats','monthly_total_trend','station_stats','heatmap_data',
                'station_ranking','top_processes','workorders']
    for key in required:
        check(f"字段 {key} 存在", key in r1)

    check("total_qty > 0", isinstance(r1['total_qty'], int) and r1['total_qty'] > 0)
    check("workorder_count > 0", isinstance(r1['workorder_count'], int) and r1['workorder_count'] > 0)
    check("date 正确", r1['date'] == TEST_DATE)
    check("hourly_stats 非空", len(r1['hourly_stats']) > 0)
    check("workorders 非空", len(r1['workorders']) > 0)
    check("heatmap_data 非 None", r1['heatmap_data'] is not None)
    hm1 = r1['heatmap_data']
    if hm1:
        check("heatmap 有 hours", 'hours' in hm1 and len(hm1['hours']) > 0)
        check("heatmap 有 flows", 'flows' in hm1 and len(hm1['flows']) > 0)
        check("heatmap 有 data", 'data' in hm1 and len(hm1['data']) > 0)

    logger.info("\n  数据量:")
    print(f"    total_qty={r1['total_qty']}, workorder_count={r1['workorder_count']}")
    print(f"    hourly_stats={len(r1['hourly_stats'])} 条")
    print(f"    process_flow_stats={len(r1['process_flow_stats'])} 条")
    print(f"    monthly_process_stats={len(r1['monthly_process_stats'])} 条")
    print(f"    monthly_total_trend={len(r1['monthly_total_trend'])} 条")
    print(f"    station_stats={len(r1['station_stats'])} 条")
    print(f"    station_ranking={len(r1['station_ranking'])} 条")
    print(f"    top_processes={len(r1['top_processes'])} 条")
    print(f"    workorders={len(r1['workorders'])} 条")
    if hm1:
        print(f"    heatmap: hours={hm1['hours']}, flows={hm1['flows']}")

    # ==== 2. get_date_stats remote + stepno=None ====
    print(f"\n{'='*60}")
    print(f"2. get_date_stats({TEST_DATE}, None) -- 远程库 全工序")
    print(f"{'='*60}")
    r2 = get_date_stats(TEST_DATE, None)

    check("total_qty > 0", r2['total_qty'] > 0)
    check("top_processes >= 1", len(r2['top_processes']) >= 1)
    check("station_ranking >= 1", len(r2['station_ranking']) >= 1)
    check("heatmap_data 非 None", r2['heatmap_data'] is not None)

    logger.info("\n  数据量:")
    print(f"    total_qty={r2['total_qty']}, workorder_count={r2['workorder_count']}")
    print(f"    top_processes={len(r2['top_processes'])} 条")
    print(f"    station_ranking={len(r2['station_ranking'])} 条")
    print(f"    process_flow_stats={len(r2['process_flow_stats'])} 条")

    # ==== 3. get_local_date_stats ====
    print(f"\n{'='*60}")
    print(f"3. get_local_date_stats({TEST_DATE}, None) -- 本地库")
    print(f"{'='*60}")
    r3 = get_local_date_stats(TEST_DATE, None)

    for key in required:
        check(f"本地字段 {key} 存在", key in r3)

    logger.info("\n  数据量:")
    print(f"    total_qty={r3['total_qty']}, workorder_count={r3['workorder_count']}")
    print(f"    hourly_stats={len(r3['hourly_stats'])} 条")
    print(f"    heatmap_data={'有' if r3['heatmap_data'] else '无'}")

    # ==== 4. API remote ====
    print(f"\n{'='*60}")
    print(f"4. HTTP API GET /api/history/date/{TEST_DATE}/?mode=remote")
    print(f"{'='*60}")
    factory = APIRequestFactory()
    req4 = factory.get(f"/api/history/date/{TEST_DATE}/?mode=remote")
    resp4 = local_date_stats(req4, str(TEST_DATE))
    check("HTTP 200", resp4.status_code == 200)
    if resp4.status_code == 200:
        d4 = resp4.data
        check("source=remote", d4['source'] == 'remote')
        check("total_qty > 0", d4['total_qty'] > 0)
        for f in ['hourly_stats','process_flow_stats','monthly_process_stats',
                   'monthly_total_trend','heatmap_data','station_ranking']:
            check(f"API 字段 {f} 存在", f in d4)
        logger.info("\n  数据量:")
        for f in ['hourly_stats','process_flow_stats','monthly_process_stats',
                   'monthly_total_trend','station_stats','station_ranking','workorders']:
            val = d4.get(f, [])
            print(f"    {f}: {len(val) if isinstance(val, list) else type(val).__name__}")

    # ==== 5. API local ====
    print(f"\n{'='*60}")
    print(f"5. HTTP API GET /api/history/date/{TEST_DATE}/?mode=local")
    print(f"{'='*60}")
    req5 = factory.get(f"/api/history/date/{TEST_DATE}/?mode=local")
    resp5 = local_date_stats(req5, str(TEST_DATE))
    check("HTTP 200", resp5.status_code == 200)
    if resp5.status_code == 200:
        d5 = resp5.data
        check("source=local", d5['source'] == 'local')
        for f in ['hourly_stats','process_flow_stats','monthly_process_stats',
                   'monthly_total_trend','heatmap_data','station_ranking']:
            check(f"API 字段 {f} 存在", f in d5)

    # ==== 汇总 ====
    print(f"\n{'='*60}")
    print(f"结果: {'ALL PASS' if not errors else f'{len(errors)} FAILED'}")
    if errors:
        print("失败项:")
        for e in errors:
            print(f"  - {e}")
    print(f"{'='*60}")

    sys.exit(0 if not errors else 1)
