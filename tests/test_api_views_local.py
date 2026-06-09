"""
本地API视图测试
"""
import pytest
import json
from unittest.mock import patch
from django.test import Client
from django.urls import reverse


class TestLocalDateStats:
    """本地日期统计API测试"""
    
    def test_local_date_stats_get(self):
        """测试获取本地日期统计"""
        client = Client()
        mock_full = {
            'workorder_count': 100, 'total_qty': 500,
            'hourly_stats': [], 'station_stats': [], 'workorders': [],
            'process_flow_stats': [], 'monthly_process_stats': [],
            'monthly_total_trend': [], 'heatmap_data': None,
            'station_ranking': [], 'top_processes': [],
        }

        with patch('iwork.api_views_local.get_local_date_stats', return_value=mock_full):
            response = client.get(
                reverse('history:local-date-stats', kwargs={'target_date': '2026-04-24'})
            )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['date'] == '2026-04-24'
        assert data['source'] == 'local'
    
    def test_local_date_stats_invalid_date(self):
        """测试无效日期格式"""
        client = Client()
        response = client.get(
            reverse('history:local-date-stats', kwargs={'target_date': 'invalid-date'})
        )
        assert response.status_code == 500
    
    def test_available_dates_get(self):
        """测试获取可用日期列表"""
        client = Client()
        mock_dates = []
        
        with patch('iwork.api_views_local.get_available_dates', return_value=mock_dates):
            response = client.get(reverse('history:available-dates'))
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'dates' in data
        assert data['mode'] == 'local'
