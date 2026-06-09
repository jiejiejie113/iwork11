import json
import pytest
from unittest.mock import patch
from datetime import date
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory


class TestDashboardView:
    """dashboard 页面视图测试"""

    def test_dashboard_returns_stats_context(self):
        """测试 dashboard 视图返回 stats 上下文"""
        from iwork.views import dashboard
        from django.test import Client
        
        client = Client()
        
        mock_stats = {
            'workorder_count': 100,
            'total_qty': 500,
            'avg_time_cost': 30.5,
            'date': date(2026, 4, 22),
            'hourly_stats': [],
            'process_stats': [],
            'flow_stats': [],
            'station_stats': [],
            'worker_ranking': [],
            'workorders': [],
        }
        
        with patch('iwork.views.get_realtime_stats', return_value=mock_stats):
            response = client.get('/')
        
        assert response.status_code == 200
        assert 'stats' in response.context
        assert response.context['stats']['workorder_count'] == 100

    def test_dashboard_date_is_date_object(self):
        """测试 stats.date 是 date 对象，而非字符串"""
        from iwork.views import dashboard
        from django.test import Client
        
        client = Client()
        
        with patch('iwork.views.get_realtime_stats') as mock_func:
            mock_func.return_value = {'date': date.today(), 'workorder_count': 0}
            response = client.get('/')
        
        stats = response.context['stats']
        assert isinstance(stats['date'], date)

    def test_dashboard_template_date_filter_returns_empty_for_string(self):
        """测试模板中 date 过滤器对字符串返回空字符串（问题确认）"""
        from django.template import Template, Context
        
        template = Template('{{ stats.date|date:"m-d" }}')
        context = Context({'stats': {'date': '2026-04-22'}})
        result = template.render(context)
        
        assert result == ''

    def test_dashboard_template_date_filter_works_with_date_object(self):
        """测试 date 过滤器对 date 对象有效"""
        from django.template import Template, Context
        
        template = Template('{{ stats.date|date:"m-d" }}')
        context = Context({'stats': {'date': date(2026, 4, 22)}})
        result = template.render(context)
        
        assert result == '04-22'


class TestRealtimeStats:
    """realtime_stats 视图测试"""

    def test_realtime_stats_success(self):
        """测试成功获取实时统计数据"""
        from iwork.api_views import realtime_stats
        
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/realtime/')
        
        mock_stats = {
            'workorder_count': 100,
            'total_qty': 500,
            'avg_time_cost': 30.5,
            'date': date.today()
        }
        
        with patch('iwork.api_views.get_realtime_stats', return_value=mock_stats):
            response = realtime_stats(request)
            
        assert response.status_code == 200
        assert response.data['workorder_count'] == 100
        assert response.data['total_qty'] == 500

    def test_realtime_stats_error(self):
        """测试获取实时统计失败"""
        from iwork.api_views import realtime_stats
        
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/realtime/')
        
        with patch('iwork.api_views.get_realtime_stats', side_effect=Exception('DB Error')):
            response = realtime_stats(request)
            
        assert response.status_code == 500
        assert 'error' in response.data


class TestHourlyStats:
    """hourly_stats 视图测试"""

    def test_hourly_stats_success(self):
        """测试成功获取小时统计数据"""
        from iwork.api_views import hourly_stats
        
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/hourly/')
        
        mock_stats = [
            {'hour': 8, 'qty': 100},
            {'hour': 9, 'qty': 150},
        ]
        
        with patch('iwork.api_views.cache.get', return_value=mock_stats):
            response = hourly_stats(request)
            
        assert response.status_code == 200
        assert len(response.data) == 2

    def test_hourly_stats_with_date_param(self):
        """测试带日期参数获取小时统计"""
        from iwork.api_views import hourly_stats
        
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/hourly/?date=2026-04-20')
        
        mock_stats = [{'hour': 10, 'qty': 200}]
        
        with patch('iwork.api_views.cache.get', return_value=mock_stats):
            response = hourly_stats(request)
            
        assert response.status_code == 200


class TestFlowStats:
    """flow_stats 视图测试"""

    def test_flow_stats_success(self):
        """测试成功获取 Flow 统计"""
        from iwork.api_views import flow_stats
        
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/flow/FlowA/')
        
        mock_result = {'flow': 'FlowA', 'total_qty': 500, 'worker_count': 10}
        
        with patch('iwork.api_views.get_flow_detail', return_value=mock_result):
            response = flow_stats(request, 'FlowA')
            
        assert response.status_code == 200
        assert response.data['flow'] == 'FlowA'
        assert response.data['total_qty'] == 500
        assert response.data['worker_count'] == 10


class TestWorkorderList:
    """workorder_list 视图测试"""

    def test_workorder_list_success(self):
        """测试成功获取工单列表"""
        from iwork.api_views import workorder_list
        
        factory = APIRequestFactory()
        request = factory.get('/api/workorders/')
        
        mock_result = {
            'items': [{'wrk_order': 'WO001', 'total_qty': 100, 'step_count': 5}],
            'total': 1, 'page': 1, 'page_size': 20, 'total_pages': 1,
        }

        with patch('iwork.api_views.get_workorders_paginated', return_value=mock_result):
            response = workorder_list(request)

        assert response.status_code == 200
        assert len(response.data['items']) == 1

    def test_workorder_list_error(self):
        """测试获取工单列表失败"""
        from iwork.api_views import workorder_list
        
        factory = APIRequestFactory()
        request = factory.get('/api/workorders/')
        
        with patch('iwork.api_views.get_workorders_paginated', side_effect=Exception('DB Error')):
            response = workorder_list(request)

        assert response.status_code == 500
        assert 'error' in response.data


class TestWorkorderDetail:
    """workorder_detail 视图测试"""

    def test_workorder_detail_success(self):
        """测试成功获取工单详情"""
        from iwork.api_views import workorder_detail
        
        factory = APIRequestFactory()
        request = factory.get('/api/workorders/WO001/')
        
        mock_result = {
            'wrk_order': 'WO001',
            'total_qty': 300,
            'steps': [
                {'StepNo': 1, 'qty': 100, 'count': 10},
                {'StepNo': 2, 'qty': 200, 'count': 20},
            ],
        }
        
        with patch('iwork.api_views.get_workorder_detail', return_value=mock_result):
            response = workorder_detail(request, 'WO001')
            
        assert response.status_code == 200
        assert response.data['wrk_order'] == 'WO001'
        assert response.data['total_qty'] == 300
        assert len(response.data['steps']) == 2

    def test_workorder_detail_not_found(self):
        """测试工单不存在"""
        from iwork.api_views import workorder_detail
        
        factory = APIRequestFactory()
        request = factory.get('/api/workorders/WO999/')
        
        mock_result = {'wrk_order': 'WO999', 'total_qty': 0, 'steps': []}
        
        with patch('iwork.api_views.get_workorder_detail', return_value=mock_result):
            response = workorder_detail(request, 'WO999')
            
        assert response.status_code == 200
        assert response.data['total_qty'] == 0
        assert response.data['steps'] == []


class TestLocalDateStatsAPI:
    """本地日期统计API集成测试"""

    def test_local_date_stats_returns_correct_source(self):
        """测试本地日期统计返回 source=local"""
        from django.test import Client
        from django.urls import reverse

        client = Client()
        mock_full = {
            'workorder_count': 50, 'total_qty': 200,
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
        assert data['source'] == 'local'
        assert data['date'] == '2026-04-24'
        assert data['workorder_count'] == 50

    def test_local_date_stats_invalid_date_returns_500(self):
        """测试无效日期返回500"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        response = client.get(
            reverse('history:local-date-stats', kwargs={'target_date': 'not-a-date'})
        )
        assert response.status_code == 500

    def test_local_date_stats_includes_all_sections(self):
        """测试本地日期统计包含所有数据段"""
        from django.test import Client
        from django.urls import reverse

        client = Client()
        mock_full = {
            'workorder_count': 10, 'total_qty': 50,
            'hourly_stats': [{'hour': 8, 'qty': 100}],
            'station_stats': [{'station': 'S01', 'qty': 150}],
            'workorders': [{'wrk_order': 'WO001', 'total_qty': 100, 'step_count': 3}],
            'process_flow_stats': [],
            'monthly_process_stats': [],
            'monthly_total_trend': [],
            'heatmap_data': None,
            'station_ranking': [{'station': 'S01', 'qty': 150}],
            'top_processes': [{'step': 70, 'qty': 200}],
        }

        with patch('iwork.api_views_local.get_local_date_stats', return_value=mock_full):
            response = client.get(
                reverse('history:local-date-stats', kwargs={'target_date': '2026-04-24'})
            )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data['hourly_stats']) == 1
        assert len(data['station_stats']) == 1
        assert len(data['workorders']) == 1


class TestAvailableDatesAPI:
    """可用日期列表API集成测试"""

    def test_available_dates_returns_local_mode(self):
        """测试可用日期返回 mode=local"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        mock_dates = [date(2026, 4, 23), date(2026, 4, 24)]
        
        with patch('iwork.api_views_local.get_available_dates', return_value=mock_dates):
            response = client.get(reverse('history:available-dates'))
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['mode'] == 'local'
        assert len(data['dates']) == 2
        assert '2026-04-23' in data['dates']
        assert '2026-04-24' in data['dates']

    def test_available_dates_empty_list(self):
        """测试无可用日期时返回空列表"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        
        with patch('iwork.api_views_local.get_available_dates', return_value=[]):
            response = client.get(reverse('history:available-dates'))
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['dates'] == []


class TestSyncDateAPI:
    """同步API集成测试"""

    def test_sync_date_returns_success(self):
        """测试同步API返回成功结果"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        mock_stats = {'synced_count': 100, 'updated_count': 10, 'skipped_count': 5}
        
        with patch('iwork.api_views_local.sync_date_data', return_value=mock_stats):
            response = client.post(
                reverse('history:sync-date', kwargs={'target_date': '2026-04-24'})
            )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        assert data['synced_count'] == 100
        assert data['updated_count'] == 10
        assert data['skipped_count'] == 5

    def test_sync_date_invalid_date_returns_500(self):
        """测试同步无效日期返回500"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        response = client.post(
            reverse('history:sync-date', kwargs={'target_date': 'invalid'})
        )
        assert response.status_code == 500

    def test_sync_date_exception_returns_500(self):
        """测试同步异常返回500"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        
        with patch('iwork.api_views_local.sync_date_data', side_effect=Exception('DB Error')):
            response = client.post(
                reverse('history:sync-date', kwargs={'target_date': '2026-04-24'})
            )

        assert response.status_code == 500


class TestParseStepno:
    """_parse_stepno 参数解析"""

    def test_empty_returns_none(self):
        """空参数 → None（全工序）"""
        from iwork.api_views import _parse_stepno
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/')
        assert _parse_stepno(request) is None

    def test_single_stepno(self):
        """?stepno=70 → [70]"""
        from iwork.api_views import _parse_stepno
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/?stepno=70')
        assert _parse_stepno(request) == [70]

    def test_multiple_comma_separated(self):
        """?stepno=70,69,68 → [70, 69, 68]"""
        from iwork.api_views import _parse_stepno
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/?stepno=70,69,68')
        assert _parse_stepno(request) == [70, 69, 68]

    def test_invalid_values_ignored(self):
        """?stepno=70,abc → 只返回 [70]"""
        from iwork.api_views import _parse_stepno
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/?stepno=70,abc')
        assert _parse_stepno(request) == [70]

    def test_all_invalid_returns_none(self):
        """?stepno=abc,xyz → None（无有效数字）"""
        from iwork.api_views import _parse_stepno
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/?stepno=abc,xyz')
        assert _parse_stepno(request) is None

    def test_spaces_trimmed(self):
        """?stepno=70, 69 → [70, 69]（空格被 strip）"""
        from iwork.api_views import _parse_stepno
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/?stepno=70, 69')
        assert _parse_stepno(request) == [70, 69]


class TestMonthlyTrend:
    """monthly_trend 端点"""

    def test_returns_trend_data(self):
        """返回当月趋势数据"""
        from iwork.api_views import monthly_trend
        from rest_framework.test import APIRequestFactory

        mock_data = [{'date': '2026-05-01', 'qty': 100}, {'date': '2026-05-12', 'qty': 200}]
        request = APIRequestFactory().get('/?date=2026-05-12')

        with patch('iwork.api_views.get_monthly_total_trend', return_value=mock_data):
            response = monthly_trend(request)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_error_returns_500(self):
        """异常返回 500"""
        from iwork.api_views import monthly_trend
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/')
        with patch('iwork.api_views.get_monthly_total_trend', side_effect=Exception('DB Error')):
            response = monthly_trend(request)

        assert response.status_code == 500


class TestProcessCompare:
    """process_compare 端点"""

    def test_returns_compare_data(self):
        """返回工序×Flow 对比"""
        from iwork.api_views import process_compare
        from rest_framework.test import APIRequestFactory

        mock_data = [{'step': 70, 'flow': 'A1', 'qty': 500}]
        request = APIRequestFactory().get('/?stepnos=70,69')

        with patch('iwork.api_views.get_process_by_flow', return_value=mock_data):
            response = process_compare(request)

        assert response.status_code == 200
        assert response.data[0]['step'] == 70

    def test_no_stepnos_defaults_to_top8(self):
        """不传 stepnos → 默认取 Top 8 工序"""
        from iwork.api_views import process_compare
        from rest_framework.test import APIRequestFactory

        mock_top = [{'step': 70, 'qty': 500}, {'step': 69, 'qty': 300}]
        mock_compare = [{'step': 70, 'flow': 'A1', 'qty': 500}]
        request = APIRequestFactory().get('/')

        with patch('iwork.api_views.get_process_stats', return_value=mock_top), \
             patch('iwork.api_views.get_process_by_flow', return_value=mock_compare):
            response = process_compare(request)

        assert response.status_code == 200

    def test_error_returns_500(self):
        """异常返回 500"""
        from iwork.api_views import process_compare
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/')
        with patch('iwork.api_views.get_process_stats', side_effect=Exception('DB Error')):
            response = process_compare(request)
        assert response.status_code == 500


class TestHeatmap:
    """heatmap 端点"""

    def test_returns_heatmap_structure(self):
        """返回 hours/flows/data 结构"""
        from iwork.api_views import heatmap
        from rest_framework.test import APIRequestFactory

        mock_data = {'hours': [8, 9], 'flows': ['A1'], 'data': [[100], [200]]}
        request = APIRequestFactory().get('/')

        with patch('iwork.api_views.get_heatmap_data', return_value=mock_data):
            response = heatmap(request)

        assert response.status_code == 200
        assert 'hours' in response.data
        assert 'data' in response.data

    def test_error_returns_500(self):
        """异常返回 500"""
        from iwork.api_views import heatmap
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/')
        with patch('iwork.api_views.get_heatmap_data', side_effect=Exception()):
            response = heatmap(request)
        assert response.status_code == 500


class TestStationRanking:
    """station_ranking 端点"""

    def test_returns_ranking_data(self):
        """返回工站排行"""
        from iwork.api_views import station_ranking
        from rest_framework.test import APIRequestFactory

        mock_data = [{'station': 'S01', 'qty': 500}]
        request = APIRequestFactory().get('/?limit=5')

        with patch('iwork.api_views.get_station_ranking', return_value=mock_data):
            response = station_ranking(request)

        assert response.status_code == 200
        assert response.data[0]['station'] == 'S01'

    def test_default_limit_is_15(self):
        """不传 limit → 默认 15"""
        from iwork.api_views import station_ranking
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/')
        with patch('iwork.api_views.get_station_ranking', return_value=[]) as mock_fn:
            station_ranking(request)
            call_kwargs = mock_fn.call_args
            assert call_kwargs[1].get('limit') == 15


class TestProcessListEndpoint:
    """统一工序列表端点（api_views.process_list）"""

    def test_returns_stepnos_default_remote(self):
        """默认模式 remote → 查远程库"""
        from iwork.api_views import process_list
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/')
        with patch('iwork.api_views.remote_get_all_stepnos', return_value=[70, 69, 68]):
            response = process_list(request)

        assert response.status_code == 200
        assert response.data['stepnos'] == [70, 69, 68]
        assert response.data['mode'] == 'remote'

    def test_local_mode_returns_local_data(self):
        """mode=local → 查本地库"""
        from iwork.api_views import process_list
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/?mode=local&date=2026-05-12')
        with patch('iwork.api_views.local_get_all_stepnos', return_value=[70, 65]):
            response = process_list(request)

        assert response.status_code == 200
        assert response.data['mode'] == 'local'
        assert response.data['date'] == '2026-05-12'

    def test_error_returns_500(self):
        """异常返回 500"""
        from iwork.api_views import process_list
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get('/')
        with patch('iwork.api_views.remote_get_all_stepnos', side_effect=Exception()):
            response = process_list(request)
        assert response.status_code == 500


class TestHistoryDashboard:
    """history_dashboard 页面视图"""

    def test_returns_200_with_zero_stats(self):
        """返回 200 + 初始数据为 0"""
        from django.test import Client

        client = Client()
        response = client.get('/history/')

        assert response.status_code == 200
        assert response.context['stats']['total_qty'] == 0
        assert response.context['stats']['workorder_count'] == 0
        assert response.context['initial_view'] == 'history'

    def test_template_used(self):
        """使用 dashboard.html 模板"""
        from django.test import Client

        client = Client()
        response = client.get('/history/')
        templates = [t.name for t in response.templates]
        assert 'iwork/dashboard.html' in templates


# ============================================================================
# 生产详情 API 端点测试


class TestFlowOverviewEndpoint:
    """GET /api/dashboard/detail/flows/"""

    @patch('iwork.api_views.cache')
    def test_returns_cached_flow_overview(self, mock_cache):
        """Redis 缓存命中时直接返回缓存数据"""
        from iwork.api_views import flow_overview
        from rest_framework.test import APIRequestFactory

        mock_cache.get.return_value = {
            'VCO-L5': {'total_qty': 800, 'worker_count': 15},
        }
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/flows/')
        response = flow_overview(request)
        assert response.status_code == 200
        assert 'VCO-L5' in response.data

    @patch('iwork.api_views.remote_get_batch_flow_overview')
    @patch('iwork.api_views.cache')
    def test_cache_miss_falls_back_to_db(self, mock_cache, mock_query):
        """缓存未命中时回退到数据库查询"""
        from iwork.api_views import flow_overview
        from rest_framework.test import APIRequestFactory

        mock_cache.get.return_value = None
        mock_query.return_value = {'VCO-L5': {'total_qty': 800, 'worker_count': 15}}
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/flows/')
        response = flow_overview(request)
        assert response.status_code == 200
        mock_query.assert_called_once()


class TestFlowDetailEndpoint:
    """GET /api/dashboard/detail/flow/<name>/"""

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.remote_get_batch_flow_employees')
    @patch('iwork.api_views.remote_get_batch_flow_hourly')
    def test_returns_flow_employees(self, mock_hourly, mock_employees, mock_cache):
        """返回指定 Flow 的员工明细和小时趋势"""
        from iwork.api_views import flow_detail
        from rest_framework.test import APIRequestFactory

        mock_employees.return_value = {
            'VCO-L5': [{'reg_per_sys_id': 1001, 'total_qty': 500, 'steps': [{'stepno': 70, 'qty': 300}]}],
        }
        mock_hourly.return_value = {'VCO-L5': [{'hour': 8, 'qty': 100}]}
        mock_cache.get.return_value = None  # 缓存未命中
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/flow/VCO-L5/')
        response = flow_detail(request, flow_name='VCO-L5')
        assert response.status_code == 200
        assert response.data['flow'] == 'VCO-L5'
        assert len(response.data['employees']) == 1


class TestStepnoDetailEndpoint:
    """GET /api/dashboard/detail/stepno/<stepno>/"""

    @patch('iwork.api_views.remote_get_batch_stepno_employees')
    def test_returns_stepno_employees(self, mock_employees):
        """返回指定工序的员工明细"""
        from iwork.api_views import stepno_detail
        from rest_framework.test import APIRequestFactory

        mock_employees.return_value = {
            70: [{'reg_per_sys_id': 1001, 'qty': 300, 'flows': ['VCO-L5']}],
        }
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/detail/stepno/70/')
        response = stepno_detail(request, stepno=70)
        assert response.status_code == 200
        assert response.data['stepno'] == 70


# ============================================================================
# SSE 推送 + 目标产量设置 测试


class TestDashboardStream:
    """dashboard_stream SSE 视图测试"""

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.get_realtime_stats')
    def test_returns_event_stream_response(self, mock_stats, mock_cache):
        """SSE 视图返回 StreamingHttpResponse"""
        from iwork.api_views import dashboard_stream
        from django.http import StreamingHttpResponse

        mock_stats.return_value = {'total_qty': 100}
        mock_cache.get.return_value = []

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/')
        response = dashboard_stream(request)

        assert isinstance(response, StreamingHttpResponse)
        assert response['Content-Type'] == 'text/event-stream'
        assert response['Cache-Control'] == 'no-cache'

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.get_realtime_stats')
    def test_sse_first_chunk_has_valid_json(self, mock_stats, mock_cache):
        """SSE 生成器第一个 chunk 包含有效的 JSON 数据"""
        from iwork.api_views import dashboard_stream

        mock_stats.return_value = {'total_qty': 500, 'date': '2026-06-04'}
        mock_cache.get.side_effect = lambda key: {
            'stats:realtime:_process_list': [70, 69],
            'stats:detail:flow_overview': [{'flow': 'VCO-L5', 'qty': 200}],
        }.get(key, None)

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/')
        response = dashboard_stream(request)

        # 取第一个 chunk（生成器 yield 后停在 sleep，不会阻塞）
        first_chunk = next(response.streaming_content).decode('utf-8')
        assert first_chunk.startswith('data: ')
        assert first_chunk.endswith('\n\n')

        json_str = first_chunk[6:-2]
        data = json.loads(json_str)
        assert data['type'] == 'dashboard_update'
        assert 'timestamp' in data
        assert data['data']['total_qty'] == 500
        assert data['process_list'] == [70, 69]
        assert data['detail_overview'] == [{'flow': 'VCO-L5', 'qty': 200}]

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.get_realtime_stats')
    def test_sse_respects_stepno_filter(self, mock_stats, mock_cache):
        """SSE 视图支持 stepno 参数过滤"""
        from iwork.api_views import dashboard_stream

        mock_stats.return_value = {'total_qty': 300}
        mock_cache.get.return_value = []

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/?stepno=69')
        response = dashboard_stream(request)

        # 触发生成器执行到第一个 yield
        next(response.streaming_content)
        mock_stats.assert_called_once_with(stepno_filter=[69])


class TestSetTargets:
    """set_targets HTTP POST 视图测试"""

    @patch('iwork.api_views.cache')
    def test_set_targets_success(self, mock_cache):
        """POST 成功写入 Redis 并返回 200"""
        from iwork.api_views import set_targets
        from unittest.mock import MagicMock

        mock_cache.set = MagicMock()

        factory = APIRequestFactory()
        request = factory.post(
            '/api/dashboard/set-targets/',
            data={'targets': {'1001': 100, '1002': 150}},
            format='json',
        )

        response = set_targets(request)
        assert response.status_code == 200
        assert response.data['status'] == 'ok'
        assert response.data['count'] == 2
        mock_cache.set.assert_called_once()

    @patch('iwork.api_views.cache')
    def test_set_targets_empty(self, mock_cache):
        """空 targets 也能正常处理"""
        from iwork.api_views import set_targets

        factory = APIRequestFactory()
        request = factory.post(
            '/api/dashboard/set-targets/',
            data={'flow': 'VCO-L5', 'targets': {}},
            format='json',
        )

        response = set_targets(request)
        assert response.status_code == 200
        assert response.data['count'] == 0