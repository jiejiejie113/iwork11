"""
统计引擎测试
"""
import pytest
from unittest.mock import patch, Mock
from datetime import date, datetime, timedelta


class TestCalculateFlowEfficiency:
    """calculate_flow_efficiency"""

    def test_normal_efficiency_calculation(self):
        """avg_time=3, baseline=10 → 0.7"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=3, baseline=10) == 0.7

    def test_zero_avg_time_returns_max_efficiency(self):
        """avg_time=0 → 1.0"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=0, baseline=10) == 1.0

    def test_high_avg_time_returns_zero_efficiency(self):
        """avg_time=15, baseline=10 → 0.0"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=15, baseline=10) == 0.0

    def test_none_avg_time_returns_none(self):
        """avg_time=None → None"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=None, baseline=10) is None

    def test_none_baseline_returns_none(self):
        """baseline=None → None"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=5, baseline=None) is None

    def test_negative_avg_time_clamped_to_zero(self):
        """avg_time=-5 → 0.0"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=-5, baseline=10) == 0.0

    def test_zero_baseline_returns_none(self):
        """baseline=0 → None（避免除零）"""
        from iwork.statistics import calculate_flow_efficiency
        assert calculate_flow_efficiency(avg_time=5, baseline=0) is None


class TestSecondsToMidnight:
    """_seconds_to_midnight TTL 计算"""

    def test_returns_positive_integer(self):
        """返回正整数"""
        from iwork.statistics import _seconds_to_midnight
        result = _seconds_to_midnight()
        assert isinstance(result, int)
        assert result > 0

    def test_result_less_than_86400(self):
        """结果 < 24小时的秒数"""
        from iwork.statistics import _seconds_to_midnight
        result = _seconds_to_midnight()
        assert result < 86400 + 10  # 24h + 5s buffer

    def test_includes_5_second_buffer(self):
        """包含 +5s 缓冲区"""
        from iwork.statistics import _seconds_to_midnight

        # 直接计算预期值
        now = datetime.now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        expected = int((midnight - now).total_seconds()) + 5

        result = _seconds_to_midnight()
        # 允许 2s 误差（执行时间差）
        assert abs(result - expected) <= 2


class TestStepnoKey:
    """_stepno_key 缓存键格式化"""

    def test_none_returns_all(self):
        """None → 'all'"""
        from iwork.statistics import _stepno_key
        assert _stepno_key(None) == 'all'

    def test_list_returns_joined(self):
        """[70, 69] → '69_70'（排序后连接）"""
        from iwork.statistics import _stepno_key
        assert _stepno_key([70, 69]) == '69_70'

    def test_single_value_returns_string(self):
        """[70] → '70'"""
        from iwork.statistics import _stepno_key
        assert _stepno_key([70]) == '70'


class TestMergeBatchTopProcesses:
    """_merge_batch_top_processes"""

    def test_returns_top_8_sorted(self):
        """返回产量最高的 8 个工序，降序"""
        from iwork.statistics import _merge_batch_top_processes

        batch_basic = {
            70: {'total_qty': 500},
            69: {'total_qty': 300},
            68: {'total_qty': 200},
            67: {'total_qty': 100},
            66: {'total_qty': 90},
            65: {'total_qty': 80},
            64: {'total_qty': 70},
            63: {'total_qty': 60},
            62: {'total_qty': 50},
            61: {'total_qty': 40},
        }

        result = _merge_batch_top_processes(batch_basic)
        assert len(result) == 8
        assert result[0] == {'step': 70, 'qty': 500}
        assert result[7]['step'] == 63

    def test_fewer_than_8_returns_all(self):
        """少于 8 个工序时返回全部"""
        from iwork.statistics import _merge_batch_top_processes

        batch_basic = {70: {'total_qty': 500}}
        result = _merge_batch_top_processes(batch_basic)
        assert len(result) == 1


class TestMergeBatchStationFull:
    """_merge_batch_station_full"""

    def test_merges_across_stepnos(self):
        """跨工序合并同一工站的产量"""
        from iwork.statistics import _merge_batch_station_full

        batch_station = {
            70: [{'station': 'S01', 'qty': 100}, {'station': 'S02', 'qty': 50}],
            69: [{'station': 'S01', 'qty': 200}],
        }

        result = _merge_batch_station_full(batch_station)
        # S01: 100+200=300, S02: 50
        s01 = next(r for r in result if r['station'] == 'S01')
        assert s01['qty'] == 300

    def test_returns_top_15(self):
        """最多返回 15 条"""
        from iwork.statistics import _merge_batch_station_full

        batch_station = {}
        for i in range(20):
            batch_station.setdefault(70, []).append({'station': f'S{i:02d}', 'qty': 100 - i})

        result = _merge_batch_station_full(batch_station)
        assert len(result) <= 15


class TestAssembleStepnoStats:
    """_assemble_stepno_stats 工序统计组装"""

    def test_includes_workorder_count_from_batch(self):
        """使用 batch_basic 中的 workorder_count"""
        from iwork.statistics import _assemble_stepno_stats

        batch_basic = {70: {'total_qty': 500, 'workorder_count': 12}}
        today = date(2026, 5, 12)
        month_start = date(2026, 5, 1)

        result = _assemble_stepno_stats(
            70, batch_basic, {}, {}, {}, {}, {}, {}, {},
            today, month_start
        )

        assert result['workorder_count'] == 12
        assert result['total_qty'] == 500
        assert result['date'] == today

    def test_missing_stepno_defaults_to_zero(self):
        """工序不在 batch 中 → 默认值 0"""
        from iwork.statistics import _assemble_stepno_stats

        result = _assemble_stepno_stats(
            99, {}, {}, {}, {}, {}, {}, {}, {},
            date(2026, 5, 12), date(2026, 5, 1)
        )

        assert result['total_qty'] == 0
        assert result['workorder_count'] == 0

    def test_includes_all_stepnos_list(self):
        """传入 all_stepnos_list → 返回中包含"""
        from iwork.statistics import _assemble_stepno_stats

        result = _assemble_stepno_stats(
            70, {70: {'total_qty': 100, 'workorder_count': 3}},
            {}, {}, {}, {}, {}, {}, {},
            date(2026, 5, 12), date(2026, 5, 1),
            all_stepnos_list=[70, 69, 68]
        )

        assert result['all_stepnos'] == [70, 69, 68]

    def test_all_stepnos_defaults_to_empty(self):
        """不传 all_stepnos_list → 空列表"""
        from iwork.statistics import _assemble_stepno_stats

        result = _assemble_stepno_stats(
            70, {70: {'total_qty': 0, 'workorder_count': 0}},
            {}, {}, {}, {}, {}, {}, {},
            date(2026, 5, 12), date(2026, 5, 1)
        )

        assert result['all_stepnos'] == []


class TestGetCachedMonthly:
    """_get_cached_monthly"""

    @patch('iwork.statistics.cache')
    def test_cache_hit_returns_cached(self, mock_cache):
        """缓存命中 → 直接返回"""
        from iwork.statistics import _get_cached_monthly

        mock_cache.get.return_value = [{'date': '2026-05-12', 'qty': 100}]

        fetch_fn = Mock()
        result = _get_cached_monthly('test_key', fetch_fn)

        assert len(result) == 1
        fetch_fn.assert_not_called()

    @patch('iwork.statistics.cache')
    def test_cache_miss_calls_fetch_and_sets(self, mock_cache):
        """缓存未命中 → 调用 fetch_fn → 写入缓存"""
        from iwork.statistics import _get_cached_monthly

        mock_cache.get.return_value = None
        fetch_fn = Mock(return_value=[{'date': '2026-05-12', 'qty': 200}])

        result = _get_cached_monthly('test_key2', fetch_fn)

        fetch_fn.assert_called_once()
        mock_cache.set.assert_called_once()
        assert result[0]['qty'] == 200


class TestInvalidateLocalCache:
    """invalidate_local_cache（修复后使用 cache.keys 通配符）"""

    @patch('iwork.statistics.cache')
    def test_uses_keys_pattern_matching(self, mock_cache):
        """使用 cache.keys(pattern) 匹配所有键"""
        from iwork.statistics import invalidate_local_cache

        mock_cache.keys.return_value = [
            'stats:local:date:2026-05-12:all',
            'stats:local:date:2026-05-12:70',
            'stats:local:date:2026-05-12:80',  # 修复前会被遗漏
        ]

        invalidate_local_cache(date(2026, 5, 12))

        assert mock_cache.delete.call_count == 3
        mock_cache.keys.assert_called_once()

    @patch('iwork.statistics.cache')
    def test_no_keys_deletes_nothing(self, mock_cache):
        """无匹配键 → 不删除"""
        from iwork.statistics import invalidate_local_cache

        mock_cache.keys.return_value = []

        invalidate_local_cache(date(2026, 5, 12))

        mock_cache.delete.assert_not_called()


class TestGetRealtimeStats:
    """get_realtime_stats（修复后移除死代码）"""

    @patch('iwork.statistics.cache')
    @patch('iwork.statistics._get_date_stats')
    def test_cache_miss_falls_back_to_live_query(self, mock_get_stats, mock_cache):
        """缓存未命中 → 实时查询 → 写入缓存"""
        from iwork.statistics import get_realtime_stats

        mock_cache.get.return_value = None
        mock_get_stats.return_value = {'total_qty': 500, 'workorder_count': 12}

        result = get_realtime_stats(stepno_filter=[70])

        mock_get_stats.assert_called_once()
        mock_cache.set.assert_called_once()
        assert result['total_qty'] == 500

    @patch('iwork.statistics.cache')
    def test_cache_hit_returns_directly(self, mock_cache):
        """缓存命中 → 直接返回，不查询 DB"""
        from iwork.statistics import get_realtime_stats

        mock_cache.get.return_value = {'total_qty': 300, 'workorder_count': 8}

        with patch('iwork.statistics._get_date_stats') as mock_get:
            result = get_realtime_stats(stepno_filter=None)

        mock_get.assert_not_called()
        assert result['total_qty'] == 300


class TestGetBatchDetailStats:
    """get_batch_detail_stats —— Batch 详情引擎"""

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
        mock_remote.get_batch_stepno_employees.return_value = {
            70: [{'reg_per_sys_id': 1001, 'qty': 300, 'flows': ['VCO-L5']}],
        }

        result = get_batch_detail_stats()

        assert result['flow_overview']['VCO-L5']['total_qty'] == 800
        assert result['flow_hourly']['VCO-L5'][0]['qty'] == 100
        assert result['flow_employees']['VCO-L5'][0]['reg_per_sys_id'] == 1001
        assert 70 in result['stepno_employees']

    @patch('iwork.statistics.remote_q')
    def test_uses_custom_query_module(self, mock_remote):
        from iwork.statistics import get_batch_detail_stats
        from unittest.mock import Mock
        custom_q = Mock()
        custom_q.get_batch_flow_overview = Mock(return_value={})
        custom_q.get_batch_flow_hourly = Mock(return_value={})
        custom_q.get_batch_flow_employees = Mock(return_value={})
        custom_q.get_batch_stepno_employees = Mock(return_value={})
        custom_q.get_batch_product_overview = Mock(return_value={'products': []})

        get_batch_detail_stats(q=custom_q)
        custom_q.get_batch_flow_overview.assert_called_once()


class TestBatchHourlyMergeNoneSafe:
    """get_batch_stats 合并小时数据时过滤 None hour"""

    @patch('iwork.statistics.remote_q')
    def test_sorts_hours_even_when_regtime_is_null(self, mock_remote):
        """batch_hourly 中有 hour=None 时不崩溃"""
        from iwork.statistics import get_batch_stats

        mock_remote.get_batch_basic_stats.return_value = {70: {'total_qty': 100, 'workorder_count': 1}}
        mock_remote.get_batch_hourly_stats.return_value = {
            70: [{'hour': 8, 'qty': 50}, {'hour': None, 'qty': 20}]  # NULL hour
        }
        mock_remote.get_batch_process_by_flow.return_value = {}
        mock_remote.get_batch_heatmap_data.return_value = {}
        mock_remote.get_batch_station_ranking.return_value = {}
        mock_remote.get_batch_workorders_list.return_value = {}
        mock_remote.get_batch_monthly_total_trend.return_value = {}
        mock_remote.get_batch_monthly_process_stats.return_value = {}
        mock_remote.get_batch_monthly_hourly_stats.return_value = {}

        result = get_batch_stats()
        assert result is not None
        # None hour 应被过滤，不影响排序
        assert result[70]['hourly_stats'] == [{'hour': 8, 'qty': 50}]


class TestCacheDetailBatchToRedis:
    """cache_detail_batch_to_redis"""

    @patch('iwork.statistics._seconds_to_midnight')
    @patch('iwork.statistics.cache')
    def test_caches_flow_keys(self, mock_cache, mock_ttl):
        from iwork.statistics import cache_detail_batch_to_redis

        mock_ttl.return_value = 36000
        detail_batch = {
            'flow_overview': {'VCO-L5': {'total_qty': 800, 'worker_count': 15}},
            'flow_hourly': {'VCO-L5': [{'hour': 8, 'qty': 100}]},
            'flow_employees': {'VCO-L5': [{'reg_per_sys_id': 1001, 'total_qty': 500}]},
            'stepno_employees': {70: [{'reg_per_sys_id': 1001, 'qty': 300, 'flows': ['VCO-L5']}]},
            'product_overview': {'products': []},
        }

        cache_detail_batch_to_redis(detail_batch)
        mock_cache.set.assert_any_call('stats:detail:flow_overview', detail_batch['flow_overview'], 36000)
        mock_cache.set.assert_any_call('stats:detail:flow_hourly', detail_batch['flow_hourly'], 36000)
        mock_cache.set.assert_any_call('stats:detail:flow:VCO-L5', detail_batch['flow_employees']['VCO-L5'], 36000)
        mock_cache.set.assert_any_call('stats:detail:stepno_overview', detail_batch['stepno_employees'], 36000)
        mock_cache.set.assert_any_call(
            'stats:detail:product_overview:v2', detail_batch['product_overview'], 36000,
        )
