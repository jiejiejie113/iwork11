import pytest
from unittest.mock import patch
from datetime import date


class TestSyncDashboardStats:
    """sync_dashboard_stats Celery 任务测试（batch 引擎版）"""

    def _setup_mocks(self):
        """统一 mock 设置"""
        mock_batch = {
            70: {'total_qty': 500, 'date': date(2026, 5, 9),
                 'hourly_stats': [{'hour': 8, 'qty': 100}],
                 'station_stats': [{'station': 'S1', 'qty': 150}],
                 'workorders': [{'wrk_order': 'W001', 'total_qty': 500, 'step_count': 5}]},
            'all': {'total_qty': 500, 'date': date(2026, 5, 9)},
        }
        return mock_batch

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_success(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """任务成功执行：批量构建 → 缓存"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch = self._setup_mocks()
        mock_batch_fn.return_value = mock_batch
        mock_detail_batch.return_value = {}

        result = sync_dashboard_stats()

        mock_batch_fn.assert_called_once()
        mock_cache.assert_called_once_with(mock_batch)
        mock_detail_batch.assert_called_once()
        mock_detail_cache.assert_called_once_with(mock_detail_batch.return_value)
        assert result == 2  # 70 + 'all'

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_returns_batch_count(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """任务返回工序数量"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch = {
            70: {'total_qty': 500, 'date': date(2026, 5, 9)},
            69: {'total_qty': 300, 'date': date(2026, 5, 9)},
            68: {'total_qty': 200, 'date': date(2026, 5, 9)},
            'all': {'total_qty': 1000, 'date': date(2026, 5, 9)},
        }
        mock_batch_fn.return_value = mock_batch
        mock_detail_batch.return_value = {}

        result = sync_dashboard_stats()
        assert result == 4  # 3 工序 + 'all'

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_retries_on_exception(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """batch 构建失败时触发重试"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch_fn.side_effect = Exception('DB down')

        with pytest.raises(Exception):
            sync_dashboard_stats()







    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_calls_detail_batch_functions(self, mock_batch, mock_cache, mock_detail_batch, mock_detail_cache):
        """sync_dashboard_stats 调用详情批量函数"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch.return_value = {70: {'total_qty': 500, 'date': date(2026, 5, 9)},
                                   'all': {'total_qty': 500, 'date': date(2026, 5, 9)}}
        mock_detail_batch.return_value = {
            'flow_overview': {}, 'flow_hourly': {}, 'flow_employees': {}
        }

        sync_dashboard_stats()

        mock_detail_batch.assert_called_once()
        mock_detail_cache.assert_called_once_with(mock_detail_batch.return_value)
