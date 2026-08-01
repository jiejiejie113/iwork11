"""
产量看板 API 端点测试
使用 APIRequestFactory 直接调用视图函数，绕过中间件
"""
from datetime import date
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory


BUSINESS_DATE = date(2026, 7, 31)


@pytest.fixture(autouse=True)
def fixed_business_date():
    """固定今日业务日期，避免测试随自然日期漂移到历史查询路径。"""
    with patch('iwork.api_views.get_business_date', return_value=BUSINESS_DATE):
        yield


def _snapshot_result(data):
    """构造看板 API 使用的快照查询结果。"""
    from iwork.read_model.store import SnapshotReadResult

    return SnapshotReadResult(
        data=data,
        metadata={
            'snapshot_version': 'v-kanban',
            'generated_at': f'{BUSINESS_DATE.isoformat()}T12:00:00+07:00',
        },
        stale=False,
    )


class TestKanbanStatsAPI:
    """GET /api/kanban/stats/"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.factory = APIRequestFactory()

    def test_stats_missing_date_returns_400(self):
        from iwork.api_views import kanban_stats
        request = self.factory.get('/api/kanban/stats/')
        response = kanban_stats(request)
        assert response.status_code == 400
        assert 'error' in response.data

    def test_stats_invalid_date_returns_400(self):
        from iwork.api_views import kanban_stats
        request = self.factory.get('/api/kanban/stats/', {'date': 'not-a-date'})
        response = kanban_stats(request)
        assert response.status_code == 400

    @patch('iwork.api_views.READ_MODEL.kanban_stats')
    def test_stats_valid_request_returns_200(self, mock_stats):
        from iwork.api_views import kanban_stats
        mock_stats.return_value = _snapshot_result({
            'worker_count': 10, 'total_production': 500,
            'avg_production': 50, 'max_production': 100,
            'max_worker_name': '12345',
        })
        request = self.factory.get('/api/kanban/stats/', {
            'date': BUSINESS_DATE.isoformat(), 'stepno': '70',
        })
        response = kanban_stats(request)
        assert response.status_code == 200
        assert response.data['worker_count'] == 10


class TestKanbanRankingAPI:
    """GET /api/kanban/ranking/"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.factory = APIRequestFactory()

    def test_ranking_missing_date_returns_400(self):
        from iwork.api_views import kanban_ranking
        request = self.factory.get('/api/kanban/ranking/')
        response = kanban_ranking(request)
        assert response.status_code == 400

    def test_ranking_invalid_page_returns_400(self):
        from iwork.api_views import kanban_ranking
        request = self.factory.get('/api/kanban/ranking/', {
            'date': '2026-06-16', 'page': 'abc',
        })
        response = kanban_ranking(request)
        assert response.status_code == 400

    @patch('iwork.api_views.READ_MODEL.kanban_ranking')
    def test_ranking_valid_request_returns_200(self, mock_ranking):
        from iwork.api_views import kanban_ranking
        mock_ranking.return_value = _snapshot_result({
            'pagination': {'page': 1, 'page_size': 50, 'total_pages': 1, 'total_count': 2},
            'workers': [
                {'rank': 1, 'reg_per_sys_id': 'A', 'worker_name': 'A',
                 'stepno': '70', 'wrk_order': 'W1', 'flow': 'F1', 'production': 100},
            ],
        })
        request = self.factory.get('/api/kanban/ranking/', {
            'date': BUSINESS_DATE.isoformat(), 'stepno': '70', 'page': 1,
        })
        response = kanban_ranking(request)
        assert response.status_code == 200
        assert 'pagination' in response.data

    @patch('iwork.api_views.READ_MODEL.kanban_ranking')
    def test_ranking_default_page_size(self, mock_ranking):
        from iwork.api_views import kanban_ranking
        mock_ranking.return_value = _snapshot_result({
            'pagination': {'page': 1, 'page_size': 50, 'total_pages': 1, 'total_count': 0},
            'workers': [],
        })
        request = self.factory.get('/api/kanban/ranking/', {
            'date': BUSINESS_DATE.isoformat(), 'stepno': '70',
        })
        response = kanban_ranking(request)
        assert response.status_code == 200
        assert response.data['pagination']['page_size'] == 50


class TestKanbanFilterOptionsAPI:
    """GET /api/kanban/filter-options/"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.factory = APIRequestFactory()

    def test_filter_options_missing_date_returns_400(self):
        from iwork.api_views import kanban_filter_options
        request = self.factory.get('/api/kanban/filter-options/')
        response = kanban_filter_options(request)
        assert response.status_code == 400

    @patch('iwork.api_views.READ_MODEL.kanban_filter_options')
    def test_filter_options_valid_request_returns_200(self, mock_options):
        from iwork.api_views import kanban_filter_options
        mock_options.return_value = _snapshot_result({
            'stepnos': ['60', '70'],
            'wrk_orders': ['SO3-001'],
            'flows': ['SO3'],
            'employees': [{'reg_per_sys_id': '12345', 'name': '12345'}],
        })
        request = self.factory.get('/api/kanban/filter-options/', {
            'date': BUSINESS_DATE.isoformat(),
        })
        response = kanban_filter_options(request)
        assert response.status_code == 200
        assert 'stepnos' in response.data
