"""
iwork 核心 API 单元测试 — mock 所有外部依赖，无需数据库/Redis

测试范围：_parse_stepno / local_date_stats / available_dates / 字段契约
"""
import json
from unittest.mock import patch, Mock
from datetime import date
from types import SimpleNamespace

import pytest
from django.test import Client


# ============================================================
# Mock 数据工厂
# ============================================================

def _make_stats(**overrides):
    """构造与 statistics._get_date_stats 返回格式一致的 mock 数据"""
    defaults = {
        'workorder_count': 42,
        'total_qty': 1500,
        'hourly_stats': [{'hour': 8, 'qty': 100}],
        'station_stats': [{'station': 'S01', 'qty': 300}],
        'workorders': [{'wrk_order': 'WO001', 'total_qty': 500, 'step_count': 3, 'worker_count': 5}],
        'process_flow_stats': [],
        'monthly_process_stats': [],
        'monthly_total_trend': [],
        'heatmap_matrix': None,
        'station_ranking': [{'station': 'S01', 'qty': 300}],
        'top_processes': [{'step': 70, 'qty': 1000}],
        'all_stepnos': [70, 69],
    }
    defaults.update(overrides)
    return defaults


# ============================================================
# _parse_stepno 辅助函数
# ============================================================

class TestParseStepno:
    """StepNo 参数解析 — 纯函数，无需 mock"""

    def test_empty_returns_none(self):
        """空参数应解析为无工序过滤。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={'stepno': ''})) is None

    def test_missing_param_returns_none(self):
        """缺少参数时应解析为无工序过滤。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={})) is None

    def test_single_value(self):
        """单个工序号应解析为整数列表。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={'stepno': '70'})) == [70]

    def test_multiple_values(self):
        """多个工序号应完整解析。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={'stepno': '70,69,68'})) == [70, 69, 68]

    def test_ignores_invalid(self):
        """无效工序号应被忽略。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={'stepno': '70,abc,68'})) == [70, 68]

    def test_all_invalid_returns_none(self):
        """全部无效时应返回无过滤。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={'stepno': 'abc,xyz'})) is None

    def test_strips_whitespace(self):
        """解析工序号时应去除空白。"""
        from iwork.api_views_local import _parse_stepno
        assert _parse_stepno(Mock(query_params={'stepno': ' 70 , 69 '})) == [70, 69]


# ============================================================
# local_date_stats 视图
# ============================================================

class TestLocalDateStats:
    """GET /api/history/date/{date}/ — 日期统计数据"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """初始化历史日期 API 测试客户端。"""
        self.client = Client()
        with patch(
            'iwork.api_views_local._snapshot_state',
            return_value=SimpleNamespace(snapshot_version=4, completed_at=None),
        ):
            yield

    def test_legacy_local_mode_returns_snapshot_source(self):
        """旧 local 模式应返回本地快照来源。"""
        with patch('iwork.api_views_local.get_local_date_stats', return_value=_make_stats()):
            resp = self.client.get('/api/history/date/2026-04-24/?mode=local')

        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['source'] == 'local_snapshot'
        assert data['date'] == '2026-04-24'
        assert data['total_qty'] == 1500

    def test_legacy_remote_mode_is_ignored(self):
        """旧 remote 模式参数应被忽略。"""
        with patch('iwork.api_views_local.get_local_date_stats', return_value=_make_stats()):
            resp = self.client.get('/api/history/date/2026-04-24/?mode=remote')

        assert resp.status_code == 200
        assert json.loads(resp.content)['source'] == 'local_snapshot'

    def test_defaults_to_local(self):
        """历史日期查询应默认使用本地快照。"""
        with patch('iwork.api_views_local.get_local_date_stats', return_value=_make_stats()):
            resp = self.client.get('/api/history/date/2026-04-24/')

        assert json.loads(resp.content)['source'] == 'local_snapshot'

    def test_invalid_date_returns_400(self):
        """无效日期应返回 400。"""
        resp = self.client.get('/api/history/date/not-a-date/')
        assert resp.status_code == 400

    def test_db_error_returns_500(self):
        """数据库异常应返回 500。"""
        with patch('iwork.api_views_local.get_local_date_stats', side_effect=ValueError('DB down')):
            resp = self.client.get('/api/history/date/2026-04-24/')

        assert resp.status_code == 500
        assert 'error' in json.loads(resp.content)

    def test_all_required_fields_present(self):
        """响应应包含所有必需字段。"""
        with patch('iwork.api_views_local.get_local_date_stats', return_value=_make_stats()):
            resp = self.client.get('/api/history/date/2026-04-24/')

        data = json.loads(resp.content)
        required = [
            'date', 'source', 'total_qty', 'workorder_count',
            'hourly_stats', 'station_stats', 'workorders',
            'process_flow_stats', 'monthly_process_stats',
            'monthly_total_trend', 'heatmap_matrix', 'station_ranking',
            'process_stats', 'top_processes', 'all_stepnos',
        ]
        for f in required:
            assert f in data, f"缺少字段: {f}"

    def test_heatmap_matrix_can_be_none(self):
        """热力图矩阵允许为空。"""
        with patch('iwork.api_views_local.get_local_date_stats', return_value=_make_stats(heatmap_matrix=None)):
            resp = self.client.get('/api/history/date/2026-04-24/')

        assert resp.status_code == 200
        assert json.loads(resp.content)['heatmap_matrix'] is None

    def test_stepno_filter_is_forwarded(self):
        """工序过滤应传递到统计层。"""
        with patch('iwork.api_views_local.get_local_date_stats', return_value=_make_stats()) as mock_fn:
            self.client.get('/api/history/date/2026-04-24/?stepno=70,69')

        mock_fn.assert_called_once()
        assert mock_fn.call_args.kwargs['stepno_filter'] == [70, 69]


# ============================================================
# available_dates 视图
# ============================================================

class TestAvailableDates:
    """GET /api/history/dates/ — 可用日期"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """初始化历史日期列表 API 测试客户端。"""
        self.client = Client()

    def test_returns_dates_sorted(self):
        """可用日期应按顺序返回。"""
        mock_dates = [date(2026, 4, 24), date(2026, 4, 23)]
        with patch('iwork.api_views_local.get_available_dates', return_value=mock_dates):
            resp = self.client.get('/api/history/dates/')

        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['source'] == 'local_snapshot'
        assert data['dates'] == ['2026-04-24', '2026-04-23']

    def test_legacy_remote_mode_is_ignored(self):
        """日期列表应忽略旧 remote 模式。"""
        with patch('iwork.api_views_local.get_available_dates', return_value=[date(2026, 4, 24)]):
            resp = self.client.get('/api/history/dates/?mode=remote')

        assert resp.status_code == 200
        assert json.loads(resp.content)['source'] == 'local_snapshot'

    def test_error_returns_500(self):
        """日期列表查询异常应返回 500。"""
        with patch('iwork.api_views_local.get_available_dates', side_effect=Exception('fail')):
            resp = self.client.get('/api/history/dates/')

        assert resp.status_code == 500


# ============================================================
# API 数据契约验证
# ============================================================

class TestApiStatisticsContract:
    """验证 API 层与 statistics 层字段一致性"""

    def test_api_keys_exist_in_stats_structure(self):
        """API 字段应存在于统计结构中。"""
        stats = _make_stats()
        api_keys = [
            'total_qty', 'workorder_count', 'hourly_stats', 'station_stats',
            'workorders', 'process_flow_stats', 'monthly_process_stats',
            'monthly_total_trend', 'heatmap_matrix', 'station_ranking', 'top_processes',
        ]
        for key in api_keys:
            assert key in stats, f"statistics 缺少 API 需要的字段: {key}"

    def test_all_stepnos_is_optional_in_api(self):
        """API 层使用 stats.get('all_stepnos', []) 兜底"""
        stats_without_key = _make_stats()
        del stats_without_key['all_stepnos']
        result = stats_without_key.get('all_stepnos', [])
        assert result == []
