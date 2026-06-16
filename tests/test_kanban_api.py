"""
产量看板 API 端点测试
使用 APIRequestFactory 直接调用视图函数，绕过中间件
"""
import pytest
from unittest.mock import patch
from datetime import date
from rest_framework.test import APIRequestFactory


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

    @patch('iwork.api_views.remote_get_kanban_stats')
    def test_stats_valid_request_returns_200(self, mock_stats):
        from iwork.api_views import kanban_stats
        mock_stats.return_value = {
            'worker_count': 10, 'total_production': 500,
            'avg_production': 50, 'max_production': 100,
            'max_worker_name': '12345',
        }
        request = self.factory.get('/api/kanban/stats/', {
            'date': '2026-06-16', 'stepno': '70',
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

    @patch('iwork.api_views.remote_get_kanban_ranking')
    def test_ranking_valid_request_returns_200(self, mock_ranking):
        from iwork.api_views import kanban_ranking
        mock_ranking.return_value = {
            'pagination': {'page': 1, 'page_size': 50, 'total_pages': 1, 'total_count': 2},
            'workers': [
                {'rank': 1, 'reg_per_sys_id': 'A', 'worker_name': 'A',
                 'stepno': '70', 'wrk_order': 'W1', 'flow': 'F1', 'production': 100},
            ],
        }
        request = self.factory.get('/api/kanban/ranking/', {
            'date': '2026-06-16', 'stepno': '70', 'page': 1,
        })
        response = kanban_ranking(request)
        assert response.status_code == 200
        assert 'pagination' in response.data

    @patch('iwork.api_views.remote_get_kanban_ranking')
    def test_ranking_default_page_size(self, mock_ranking):
        from iwork.api_views import kanban_ranking
        mock_ranking.return_value = {
            'pagination': {'page': 1, 'page_size': 50, 'total_pages': 1, 'total_count': 0},
            'workers': [],
        }
        request = self.factory.get('/api/kanban/ranking/', {
            'date': '2026-06-16', 'stepno': '70',
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

    @patch('iwork.api_views.remote_get_kanban_filter_options')
    def test_filter_options_valid_request_returns_200(self, mock_options):
        from iwork.api_views import kanban_filter_options
        mock_options.return_value = {
            'stepnos': ['60', '70'],
            'wrk_orders': ['SO3-001'],
            'flows': ['SO3'],
            'employees': [{'reg_per_sys_id': '12345', 'name': '12345'}],
        }
        request = self.factory.get('/api/kanban/filter-options/', {
            'date': '2026-06-16',
        })
        response = kanban_filter_options(request)
        assert response.status_code == 200
        assert 'stepnos' in response.data
