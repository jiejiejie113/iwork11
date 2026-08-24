import json
import asyncio
import pytest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import ANY, patch
from datetime import date
from rest_framework.test import APIRequestFactory


class TestDashboardView:
    """dashboard 页面视图测试"""

    def test_dashboard_returns_stats_context(self):
        """测试 dashboard 视图返回 stats 上下文"""
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

    def test_dashboard_renders_zero_state_when_snapshot_not_ready(self):
        """首个 Celery 快照完成前页面仍能加载且不回源。"""
        from django.test import Client
        from iwork.read_model.errors import ReadModelNotReadyError

        with patch(
            'iwork.views.get_realtime_stats',
            side_effect=ReadModelNotReadyError('未准备好'),
        ):
            response = Client().get('/')

        assert response.status_code == 200
        assert response.context['stats']['total_qty'] == 0


def _snapshot_result(data, stale=False, snapshot_version='v-test'):
    """构造 API 测试使用的统一快照结果。"""
    from iwork.read_model.store import SnapshotReadResult

    return SnapshotReadResult(
        data=data,
        metadata={
            'snapshot_version': snapshot_version,
            'generated_at': '2026-07-31T12:00:00+07:00',
        },
        stale=stale,
    )


class TestRealtimeReadModelEndpoints:
    """实时、小时、Flow 和工单端点统一读取快照。"""

    def test_realtime_returns_snapshot_headers(self):
        """实时接口返回原有主体及快照元数据响应头。"""
        from iwork.api_views import realtime_stats

        request = APIRequestFactory().get('/api/dashboard/realtime/?stepno=70')
        with patch(
            'iwork.api_views.READ_MODEL.realtime',
            return_value=_snapshot_result({'total_qty': 500}),
        ) as read:
            response = realtime_stats(request)

        assert response.status_code == 200
        assert response.data['total_qty'] == 500
        assert response['X-Iwork-Snapshot-Version'] == 'v-test'
        read.assert_called_once()

    def test_missing_snapshot_returns_503_without_fallback(self):
        """快照缺失时明确返回 503，不回源远程数据库。"""
        from iwork.api_views import realtime_stats
        from iwork.read_model.errors import ReadModelNotReadyError

        request = APIRequestFactory().get('/api/dashboard/realtime/')
        with patch(
            'iwork.api_views.READ_MODEL.realtime',
            side_effect=ReadModelNotReadyError('未准备好'),
        ):
            response = realtime_stats(request)

        assert response.status_code == 503
        assert response.data['code'] == 'realtime_snapshot_unavailable'

    def test_hourly_reads_realtime_snapshot(self):
        """今日小时趋势来自同一实时快照。"""
        from iwork.api_views import hourly_stats

        request = APIRequestFactory().get('/api/dashboard/hourly/?stepno=70')
        with patch(
            'iwork.api_views.READ_MODEL.realtime',
            return_value=_snapshot_result({'hourly_stats': [{'hour': 8, 'qty': 10}]}),
        ):
            response = hourly_stats(request)
        assert response.status_code == 200
        assert response.data == [{'hour': 8, 'qty': 10}]

    def test_workorders_use_read_model_pagination(self):
        """今日工单分页只调用读模型。"""
        from iwork.api_views import workorder_list

        payload = {'items': [{'wrk_order': 'WO1'}], 'total': 1, 'total_pages': 1}
        request = APIRequestFactory().get('/api/dashboard/workorders/?page=1&page_size=20')
        with patch(
            'iwork.api_views.READ_MODEL.workorders',
            return_value=_snapshot_result(payload),
        ) as read:
            response = workorder_list(request)
        assert response.status_code == 200
        assert response.data['items'][0]['wrk_order'] == 'WO1'
        read.assert_called_once()

    def test_workorder_detail_uses_read_model(self):
        """今日工单详情读取版本化详情映射。"""
        from iwork.api_views import workorder_detail

        request = APIRequestFactory().get('/api/dashboard/workorders/WO1/')
        with patch(
            'iwork.api_views.READ_MODEL.workorder_detail',
            return_value=_snapshot_result({'wrk_order': 'WO1', 'total_qty': 10, 'steps': []}),
        ):
            response = workorder_detail(request, 'WO1')
        assert response.status_code == 200
        assert response.data['total_qty'] == 10
        assert response.data['steps'] == []


class TestLocalDateStatsAPI:
    """本地日期统计API集成测试"""

    @patch('iwork.api_views_local.HistoricalSyncState.objects')
    def test_local_date_stats_returns_correct_source(self, mock_states):
        """测试本地日期统计返回本地快照来源。"""
        from django.test import Client
        from django.urls import reverse

        client = Client()
        mock_full = {
            'workorder_count': 50, 'total_qty': 200,
            'hourly_stats': [], 'station_stats': [], 'workorders': [],
            'process_flow_stats': [], 'monthly_process_stats': [],
            'monthly_total_trend': [], 'heatmap_matrix': None,
            'station_ranking': [], 'top_processes': [],
        }

        mock_states.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            snapshot_version=2,
            completed_at=None,
        )
        with patch('iwork.api_views_local.get_local_date_stats', return_value=mock_full):
            response = client.get(
                reverse('history:local-date-stats', kwargs={'target_date': '2026-04-24'})
            )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['source'] == 'local_snapshot'
        assert data['snapshot_version'] == 2
        assert data['date'] == '2026-04-24'
        assert data['workorder_count'] == 50

    def test_local_date_stats_invalid_date_returns_400(self):
        """测试无效日期返回400。"""
        from django.test import Client
        from django.urls import reverse

        client = Client()
        response = client.get(
            reverse('history:local-date-stats', kwargs={'target_date': 'not-a-date'})
        )
        assert response.status_code == 400

    @patch('iwork.api_views_local.HistoricalSyncState.objects')
    def test_local_date_stats_includes_all_sections(self, mock_states):
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
            'heatmap_matrix': None,
            'station_ranking': [{'station': 'S01', 'qty': 150}],
            'top_processes': [{'step': 70, 'qty': 200}],
        }

        mock_states.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            snapshot_version=1,
            completed_at=None,
        )
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
        assert data['source'] == 'local_snapshot'
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


class TestEnsureHistorySnapshotAPI:
    """自动确保历史快照 API。"""

    @patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
    def test_rejects_current_or_future_date(self, _mock_business_date):
        """当前或未来业务日期不允许生成历史快照。"""
        from django.test import Client
        from django.urls import reverse

        response = Client().post(
            reverse('history:ensure-snapshot', kwargs={'target_date': '2026-07-16'})
        )

        assert response.status_code == 400
        assert response.json()['error'] == '只能构建已经结束的历史日期'

    def test_rejects_invalid_date(self):
        """非法日期参数应被拒绝。"""
        from django.test import Client

        response = Client().post('/api/history/snapshots/not-a-date/ensure/')

        assert response.status_code == 400
        assert response.json()['error'] == '日期格式错误，需为 YYYY-MM-DD'

    @patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 31))
    @patch('iwork.api_views_local._snapshot_state', return_value=None)
    @patch('iwork.api_views_local.build_history_snapshot.delay')
    def test_missing_snapshot_is_queued_and_returns_202(
        self,
        mock_delay,
        _mock_state,
        _mock_business_date,
    ):
        """HTTP 请求只提交后台任务，不同步访问远程数据库。"""
        from django.core.cache import cache
        from django.test import Client

        mock_delay.return_value.id = 'task-1'
        response = Client().post('/api/history/snapshots/2026-07-30/ensure/')
        cache.delete('history:snapshot:request:2026-07-30')

        assert response.status_code == 202
        assert response.json()['code'] == 'history_snapshot_building'
        mock_delay.assert_called_once_with('2026-07-30', ANY)

    @patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 31))
    @patch('iwork.api_views_local._snapshot_state', return_value=None)
    @patch('iwork.api_views_local.build_history_snapshot.delay')
    def test_duplicate_request_does_not_enqueue_second_task(
        self,
        mock_delay,
        _mock_state,
        _mock_business_date,
    ):
        """同一天并发确保请求只产生一个后台任务。"""
        from django.core.cache import cache
        from django.test import Client

        request_lock = cache.lock(
            'history:snapshot:request:2026-07-30',
            timeout=60,
            thread_local=False,
        )
        assert request_lock.acquire(blocking=False)
        try:
            response = Client().post('/api/history/snapshots/2026-07-30/ensure/')
        finally:
            request_lock.release()

        assert response.status_code == 202
        mock_delay.assert_not_called()


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


class TestRealtimeDerivedEndpoints:
    """月趋势、对比、热力图、排行和工序列表均来自快照。"""

    @pytest.mark.parametrize(
        ('view_name', 'field', 'payload'),
        [
            ('monthly_trend', 'monthly_total_trend', [{'date': '2026-07-31', 'qty': 10}]),
            ('process_compare', 'process_flow_stats', [{'step': 70, 'flow': 'A', 'qty': 10}]),
            ('heatmap', 'heatmap_matrix', {'hours': [8], 'flows': ['A'], 'data': [[10]]}),
            ('station_ranking', 'station_ranking', [{'station': 'S1', 'qty': 10}]),
        ],
    )
    def test_endpoint_reads_realtime_snapshot(self, view_name, field, payload):
        """派生统计不再独立查询远程数据库。"""
        import iwork.api_views as api_views

        request = APIRequestFactory().get('/?stepnos=70,69')
        with patch(
            'iwork.api_views.READ_MODEL.realtime',
            return_value=_snapshot_result({field: payload}),
        ):
            response = getattr(api_views, view_name)(request)
        assert response.status_code == 200
        assert response.data == payload

    def test_process_list_reads_snapshot(self):
        """今日工序列表从读模型获取。"""
        from iwork.api_views import process_list

        request = APIRequestFactory().get('/')
        with patch(
            'iwork.api_views.READ_MODEL.processes',
            return_value=_snapshot_result([70, 69]),
        ):
            response = process_list(request)
        assert response.status_code == 200
        assert response.data['stepnos'] == [70, 69]

    @patch('iwork.api_views._snapshot_state', return_value=object())
    def test_historical_process_list_stays_local(self, _mock_snapshot):
        """历史日期继续读取本地快照。"""
        from iwork.api_views import process_list

        request = APIRequestFactory().get('/?date=2026-05-12')
        with patch('iwork.api_views.local_get_all_stepnos', return_value=[70, 65]):
            response = process_list(request)
        assert response.status_code == 200
        assert response.data['mode'] == 'local'

    @pytest.mark.parametrize(
        ('view_name', 'field', 'expected'),
        [
            (
                'process_compare',
                'process_flow_stats',
                [{'step': 70, 'flow': 'A', 'qty': 10}],
            ),
            (
                'heatmap',
                'heatmap_matrix',
                {'hours': [8], 'flows': ['A'], 'data': [[10]]},
            ),
            (
                'station_ranking',
                'station_ranking',
                [{'station': 'S1', 'qty': 10}],
            ),
        ],
    )
    @patch('iwork.api_views._snapshot_state', return_value=object())
    def test_historical_derived_endpoints_stay_local(
        self,
        _mock_snapshot,
        view_name,
        field,
        expected,
    ):
        """历史派生统计必须读取本地快照，不能查今日 Redis 读模型。"""
        import iwork.api_views as api_views

        local_stats = {
            field: expected,
            'top_processes': [{'step': 70, 'qty': 10}],
        }
        request = APIRequestFactory().get('/?date=2026-05-12')
        with patch(
            'iwork.api_views.get_local_date_stats',
            return_value=local_stats,
        ) as get_local, patch(
            'iwork.api_views.READ_MODEL.realtime',
        ) as read_realtime:
            response = getattr(api_views, view_name)(request)

        assert response.status_code == 200
        assert response.data == expected
        get_local.assert_called_once()
        read_realtime.assert_not_called()


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

    def test_returns_snapshot_flow_overview(self):
        """Flow 概览读取版本化详情视图。"""
        from iwork.api_views import flow_overview

        payload = {'VCO-L5': {'total_qty': 800, 'worker_count': 15}}
        with patch(
            'iwork.api_views.READ_MODEL.detail',
            return_value=_snapshot_result(payload),
        ) as read:
            response = flow_overview(APIRequestFactory().get('/'))
        assert response.status_code == 200
        assert 'VCO-L5' in response.data
        read.assert_called_once()


class TestFlowDetailEndpoint:
    """GET /api/dashboard/detail/flow/<name>/"""

    @patch('iwork.api_views._get_wo_targets_with_fallback', return_value={})
    @patch('iwork.api_views._get_targets_with_fallback', return_value={})
    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    def test_returns_flow_employees(
        self, _mock_minutes, _mock_targets, _mock_wo_targets,
    ):
        """员工明细和小时趋势来自同一个固定版本。"""
        from iwork.api_views import flow_detail

        bundle = {
            'flow_employees': {'VCO-L5': [{
                'reg_per_sys_id': 1001,
                'total_qty': 500,
                'cumulative_qty': 800,
                'output_value': 420.0,
                'steps': [],
            }]},
            'flow_hourly': {'VCO-L5': [{'hour': 8, 'qty': 100}]},
        }
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ) as read:
            response = flow_detail(
                APIRequestFactory().get('/api/dashboard/detail/flow/VCO-L5/'),
                flow_name='VCO-L5',
            )
        assert response.status_code == 200
        assert response.data['flow'] == 'VCO-L5'
        assert response.data['work_minutes'] == 210
        assert response.data['cumulative_qty'] == 800
        assert len(response.data['employees']) == 1
        assert response.data['employees'][0]['employee_efficiency'] == 200.0
        assert response.data['source'] == 'redis_snapshot'
        read.assert_called_once()

    @patch('iwork.api_views._get_wo_targets_with_fallback', return_value={})
    @patch('iwork.api_views._get_targets_with_fallback', return_value={'1001': 250})
    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    def test_cached_snapshot_gets_request_time_efficiency(
        self, _mock_minutes, _mock_targets, _mock_wo_targets,
    ):
        """缓存快照应按请求时刻重新计算效率。"""
        from iwork.api_views import flow_detail

        cached_employees = [{
            'reg_per_sys_id': 1001,
            'total_qty': 300,
            'output_value': 420.0,
            'steps': [],
        }]
        bundle = {
            'flow_employees': {'VCO-L5': cached_employees},
            'flow_hourly': {'VCO-L5': [{'hour': 10, 'qty': 300}]},
        }
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ):
            response = flow_detail(
                APIRequestFactory().get('/api/dashboard/detail/flow/VCO-L5/'),
                flow_name='VCO-L5',
            )

        assert response.status_code == 200
        assert response.data['work_minutes'] == 210
        assert response.data['employees'][0]['employee_efficiency'] == 200.0
        assert response.data['employees'][0]['target'] == 250
        assert 'employee_efficiency' not in cached_employees[0]
        assert 'target' not in cached_employees[0]

    @patch('iwork.api_views._get_group_work_minutes_with_fallback', return_value=600)
    @patch('iwork.api_views._get_group_target_with_fallback', return_value=1000)
    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    def test_group_target_is_distributed_to_each_step_worker(
        self, _mock_minutes, _mock_group_target, _mock_group_work_minutes,
    ):
        """整组目标应独立分配给每道工序，再按工序人数分配到员工。"""
        from iwork.api_views import flow_detail

        employees = []
        for employee_id in range(1001, 1006):
            steps = [{'stepno': 2, 'qty': employee_id - 990, 'workorder': 'WO-1'}]
            if employee_id in (1001, 1002):
                steps.append({'stepno': 1, 'qty': 100, 'workorder': 'WO-1'})
            employees.append({
                'reg_per_sys_id': employee_id,
                'total_qty': sum(step['qty'] for step in steps),
                'output_value': 0,
                'steps': steps,
            })

        bundle = {
            'flow_employees': {'SO3-L3A': employees},
            'flow_hourly': {'SO3-L3A': []},
        }
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ):
            response = flow_detail(
                APIRequestFactory().get('/api/dashboard/detail/flow/SO3-L3A/'),
                flow_name='SO3-L3A',
            )

        assert response.status_code == 200
        assert response.data['group_target'] == 1000
        assert response.data['work_hours'] == 10
        assert response.data['current_group_target'] == 400
        assert response.data['step_targets'] == {
            '1': {'target': 1000, 'current_target': 400, 'worker_count': 2},
            '2': {'target': 1000, 'current_target': 400, 'worker_count': 5},
        }
        first_employee = response.data['employees'][0]
        assert first_employee['step_targets']['1']['full_target'] == 500
        assert first_employee['step_targets']['1']['target'] == 200
        assert first_employee['step_targets']['2']['full_target'] == 200
        assert first_employee['step_targets']['2']['target'] == 80
        assert first_employee['full_target'] == 700
        assert first_employee['target'] == 280
        assert first_employee['target_rate'] == pytest.approx(
            first_employee['total_qty'] / 280 * 100,
        )

    @patch('iwork.api_views._get_group_target_with_fallback', return_value=1000)
    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    def test_group_target_remainder_is_stable_and_preserves_step_total(
        self, _mock_minutes, _mock_group_target,
    ):
        """目标不能整除人数时应稳定分配余数，且个人目标合计不变。"""
        employees = [
            {
                'reg_per_sys_id': employee_id,
                'total_qty': 10,
                'output_value': 0,
                'steps': [{'stepno': 2, 'qty': 10, 'workorder': 'WO-1'}],
            }
            for employee_id in (1003, 1001, 1002)
        ]

        from iwork.api_views import flow_detail

        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result({
                'flow_employees': {'SO3-L3A': employees},
                'flow_hourly': {'SO3-L3A': []},
            }),
        ):
            response = flow_detail(
                APIRequestFactory().get('/api/dashboard/detail/flow/SO3-L3A/'),
                flow_name='SO3-L3A',
            )

        assigned = {
            employee['reg_per_sys_id']: employee['step_targets']['2']['target']
            for employee in response.data['employees']
        }
        assert assigned == {1003: 333, 1001: 334, 1002: 333}
        assert sum(assigned.values()) == 1000
        assert 'target' not in employees[0]['steps'][0]

    @patch('iwork.api_views._get_group_work_minutes_with_fallback', return_value=600)
    @patch('iwork.api_views._get_group_target_with_fallback', return_value=1000)
    @patch('iwork.api_views.get_effective_work_minutes', return_value=420)
    def test_group_target_uses_current_work_period_for_target_rate(
        self, _mock_minutes, _mock_group_target, _mock_group_work_minutes,
    ):
        """15:00 已工作7小时，10小时目标应折算为当前时段目标700。"""
        from iwork.api_views import flow_detail

        employees = [
            {
                'reg_per_sys_id': employee_id,
                'total_qty': 140,
                'output_value': 0,
                'steps': [
                    {'stepno': 2, 'qty': 140, 'workorder': f'WO-{employee_id}'},
                ],
            }
            for employee_id in range(1001, 1006)
        ]
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result({
                'flow_employees': {'SO3-L3A': employees},
                'flow_hourly': {'SO3-L3A': []},
            }),
        ):
            response = flow_detail(
                APIRequestFactory().get('/api/dashboard/detail/flow/SO3-L3A/'),
                flow_name='SO3-L3A',
            )

        assert response.data['current_group_target'] == 700
        assert response.data['employees'][0]['target'] == 140
        assert response.data['employees'][0]['target_rate'] == 100

    @pytest.mark.parametrize(
        ('elapsed_minutes', 'expected_target'),
        [
            (340, 600),  # 13:40 的有效工时为5小时40分，向上取整为6小时。
            (360, 600),  # 已在整点时不继续进位。
            (601, 1000),  # 超过计划工时后仍封顶为全天目标。
        ],
    )
    def test_current_group_target_rounds_work_period_up_to_full_hour(
        self,
        elapsed_minutes,
        expected_target,
    ):
        """当前时段目标应把有效工作分钟向上取整到整小时。"""
        from iwork.api_views import _calculate_current_group_target

        assert _calculate_current_group_target(
            group_target=1000,
            planned_work_minutes=600,
            elapsed_work_minutes=elapsed_minutes,
        ) == expected_target

    def test_same_employee_step_aggregates_actuals_across_workorders(self):
        """同一员工同一工序的多个本厂款号应共用一个目标和达成率。"""
        from iwork.api_views import _distribute_group_target

        employees = [
            {
                'reg_per_sys_id': 1001,
                'total_qty': 100,
                'steps': [
                    {'stepno': 2, 'qty': 60, 'workorder': 'WO-1'},
                    {'stepno': 2, 'qty': 40, 'workorder': 'WO-2'},
                ],
            },
            {
                'reg_per_sys_id': 1002,
                'total_qty': 50,
                'steps': [{'stepno': 2, 'qty': 50, 'workorder': 'WO-3'}],
            },
        ]

        _distribute_group_target(employees, 1000)

        step_target = employees[0]['step_targets']['2']
        assert step_target['target'] == 500
        assert step_target['actual_qty'] == 100
        assert step_target['target_rate'] == 20
        assert employees[0]['steps'][0]['target'] == 500
        assert employees[0]['steps'][1]['target'] == 500


class TestStepnoDetailEndpoint:
    """GET /api/dashboard/detail/stepno/<stepno>/"""

    @patch('iwork.api_views._get_targets_with_fallback', return_value={})
    def test_returns_stepno_employees(self, _mock_targets):
        """返回快照中的指定工序员工明细。"""
        from iwork.api_views import stepno_detail

        bundle = {
            'stepno_employees': {
                70: [{'reg_per_sys_id': 1001, 'qty': 300, 'flows': ['VCO-L5']}],
            },
        }
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ):
            response = stepno_detail(
                APIRequestFactory().get('/api/dashboard/detail/stepno/70/'),
                stepno=70,
            )
        assert response.status_code == 200
        assert response.data['stepno'] == 70
        assert response.data['total_qty'] == 300


class TestInitialStyleOverviewEndpoint:
    """GET /api/dashboard/detail/initial-style-overview/。"""

    def test_aggregates_styles_across_flows_from_one_snapshot(self):
        """初版款号概览应跨普通线汇总并对员工、本厂款号去重。"""
        from iwork.api_views import initial_style_overview

        bundle = {
            'flow_employees': {
                'SO3-L3A': [
                    {
                        'reg_per_sys_id': 1001,
                        'steps': [
                            {
                                'stepno': 1,
                                'qty': 10,
                                'workorder': 'WO-1',
                                'initial_style_no': 'BU-1',
                            },
                            {
                                'stepno': 70,
                                'qty': 20,
                                'workorder': 'WO-1',
                                'initial_style_no': 'BU-1',
                            },
                            {
                                'stepno': 3,
                                'qty': 5,
                                'workorder': 'WO-X',
                                'initial_style_no': '',
                            },
                        ],
                    },
                    {
                        'reg_per_sys_id': 1002,
                        'steps': [{
                            'stepno': 70,
                            'qty': 7,
                            'workorder': 'WO-S',
                            'initial_style_no': 'ST/特殊',
                        }],
                    },
                ],
                'SO5-L5B': [
                    {
                        'reg_per_sys_id': 1001,
                        'steps': [{
                            'stepno': 70,
                            'qty': 30,
                            'workorder': 'WO-2',
                            'initial_style_no': 'BU-1',
                        }],
                    },
                    {
                        'reg_per_sys_id': 1003,
                        'steps': [{
                            'stepno': 3,
                            'qty': 40,
                            'workorder': 'WO-3',
                            'initial_style_no': 'BU-1',
                        }],
                    },
                    {
                        'reg_per_sys_id': 1004,
                        'steps': [{
                            'stepno': 70,
                            'qty': 9,
                            'workorder': 'WO-Y',
                            'initial_style_no': '   ',
                        }],
                    },
                ],
            },
        }
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ) as read:
            response = initial_style_overview(APIRequestFactory().get('/'))

        assert response.status_code == 200
        assert [item['initial_style_no'] for item in response.data['items']] == [
            'BU-1',
            'ST/特殊',
            '',
        ]
        style = response.data['items'][0]
        assert style['total_qty'] == 50
        assert style['worker_count'] == 2
        assert style['workorder_count'] == 3
        assert style['flows'] == [
            {'flow': 'SO5-L5B', 'qty': 30, 'worker_count': 2},
            {'flow': 'SO3-L3A', 'qty': 20, 'worker_count': 1},
        ]
        assert style['stepnos'] == {
            1: {'qty': 10},
            3: {'qty': 40},
            70: {'qty': 50},
        }
        assert response.data['items'][-1]['label'] == '未设置'
        assert response.data['items'][-1]['total_qty'] == 9
        assert response.data['source'] == 'redis_snapshot'
        read.assert_called_once()

    @patch(
        'iwork.api_views._snapshot_state',
        return_value=SimpleNamespace(snapshot_version='history-v1'),
    )
    def test_historical_overview_reads_local_snapshot(self, _mock_state):
        """历史初版款号概览只能读取本地历史快照。"""
        from iwork.api_views import initial_style_overview

        local_data = {
            'SO3-L3A': [{
                'reg_per_sys_id': 1001,
                'steps': [{
                    'stepno': 70,
                    'qty': 12,
                    'workorder': 'WO-1',
                    'initial_style_no': 'BU-1',
                }],
            }],
        }
        request = APIRequestFactory().get('/', {'date': '2026-08-10'})
        with patch(
            'iwork.api_views.local_get_batch_flow_employees',
            return_value=local_data,
        ) as read_local, patch(
            'iwork.api_views.READ_MODEL.details',
        ) as read_realtime:
            response = initial_style_overview(request)

        assert response.status_code == 200
        assert response.data['items'][0]['total_qty'] == 12
        assert response.data['source'] == 'local_snapshot'
        read_local.assert_called_once_with(date(2026, 8, 10))
        read_realtime.assert_not_called()


class TestInitialStyleDetailEndpoint:
    """GET /api/dashboard/detail/initial-style/。"""

    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    def test_merges_employee_steps_across_flows(self, _mock_minutes):
        """款号详情应合并员工并在每条工序中保留生产线。"""
        from iwork.api_views import initial_style_detail

        bundle = {
            'flow_employees': {
                'SO3-L3A': [{
                    'reg_per_sys_id': 1001,
                    'steps': [
                        {
                            'stepno': 1,
                            'qty': 10,
                            'cumulative_qty': 100,
                            'workorder': 'WO-1',
                            'initial_style_no': 'BU-1',
                            'output_value': 10.0,
                        },
                        {
                            'stepno': 2,
                            'qty': 99,
                            'workorder': 'WO-X',
                            'initial_style_no': 'OTHER',
                            'output_value': 99.0,
                        },
                    ],
                }],
                'SO5-L5B': [
                    {
                        'reg_per_sys_id': 1001,
                        'steps': [{
                            'stepno': 3,
                            'qty': 30,
                            'cumulative_qty': 300,
                            'workorder': 'WO-2',
                            'initial_style_no': 'BU-1',
                            'output_value': 30.0,
                        }],
                    },
                    {
                        'reg_per_sys_id': 1002,
                        'steps': [{
                            'stepno': 6,
                            'qty': 40,
                            'cumulative_qty': 400,
                            'workorder': 'WO-3',
                            'initial_style_no': 'BU-1',
                            'output_value': 40.0,
                        }],
                    },
                ],
            },
        }
        request = APIRequestFactory().get('/', {'initial_style_no': 'BU-1'})
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ) as read:
            response = initial_style_detail(request)

        assert response.status_code == 200
        assert response.data['initial_style_no'] == 'BU-1'
        assert response.data['total_qty'] == 80
        assert response.data['cumulative_qty'] == 800
        assert response.data['worker_count'] == 2
        assert response.data['flows'] == ['SO3-L3A', 'SO5-L5B']
        first_employee = response.data['employees'][0]
        assert first_employee['reg_per_sys_id'] == 1001
        assert first_employee['total_qty'] == 40
        assert first_employee['cumulative_qty'] == 400
        assert first_employee['workorders'] == ['WO-1', 'WO-2']
        assert [step['flow'] for step in first_employee['steps']] == [
            'SO3-L3A',
            'SO5-L5B',
        ]
        assert all(
            step['initial_style_no'] == 'BU-1'
            for employee in response.data['employees']
            for step in employee['steps']
        )
        assert response.data['source'] == 'redis_snapshot'
        read.assert_called_once()

    @patch('iwork.api_views._get_group_work_minutes_with_fallback', return_value=600)
    @patch('iwork.api_views._get_group_target_with_fallback', return_value=1000)
    @patch('iwork.api_views.get_effective_work_minutes', return_value=300)
    def test_reuses_full_flow_target_allocation_before_filtering_style(
        self,
        _mock_minutes,
        _mock_group_target,
        _mock_group_work_minutes,
    ):
        """初版款号目标与达成率应沿用完整分组口径，而非按款号子集重算。"""
        from iwork.api_views import initial_style_detail

        bundle = {
            'flow_employees': {
                'SO3-L3A': [
                    {
                        'reg_per_sys_id': 1001,
                        'total_qty': 100,
                        'steps': [
                            {
                                'stepno': 1,
                                'qty': 40,
                                'workorder': 'WO-STYLE',
                                'initial_style_no': '30405',
                                'output_value': 40.0,
                            },
                            {
                                'stepno': 1,
                                'qty': 60,
                                'workorder': 'WO-OTHER',
                                'initial_style_no': 'OTHER',
                                'output_value': 60.0,
                            },
                        ],
                    },
                    {
                        'reg_per_sys_id': 1002,
                        'total_qty': 20,
                        'steps': [{
                            'stepno': 1,
                            'qty': 20,
                            'workorder': 'WO-OTHER-2',
                            'initial_style_no': 'OTHER',
                            'output_value': 20.0,
                        }],
                    },
                ],
            },
        }
        request = APIRequestFactory().get('/', {'initial_style_no': '30405'})
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ):
            response = initial_style_detail(request)

        assert response.status_code == 200
        assert response.data['total_qty'] == 40
        step = response.data['employees'][0]['steps'][0]
        assert step['target'] == 250
        assert step['target_rate'] == pytest.approx(40.0)
        assert response.data['flow_targets'] == [{
            'flow': 'SO3-L3A',
            'group_target': 1000,
            'current_group_target': 500,
            'work_hours': 10.0,
        }]

    def test_missing_style_parameter_returns_400(self):
        """缺少初版款号参数时应明确拒绝请求。"""
        from iwork.api_views import initial_style_detail

        response = initial_style_detail(APIRequestFactory().get('/'))

        assert response.status_code == 400
        assert response.data['error'] == '缺少 initial_style_no 参数'

    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    def test_explicit_blank_style_returns_unassigned_detail(self, _mock_minutes):
        """显式空初版款号应返回“未设置”组而不是漏数。"""
        from iwork.api_views import initial_style_detail

        bundle = {
            'flow_employees': {
                'SO3-L3A': [{
                    'reg_per_sys_id': 1001,
                    'steps': [{
                        'stepno': 1,
                        'qty': 12,
                        'workorder': 'WO-1',
                        'initial_style_no': '   ',
                        'output_value': 3.0,
                    }],
                }],
            },
        }
        request = APIRequestFactory().get('/', {'initial_style_no': ''})
        with patch(
            'iwork.api_views.READ_MODEL.details',
            return_value=_snapshot_result(bundle),
        ):
            response = initial_style_detail(request)

        assert response.status_code == 200
        assert response.data['initial_style_no'] == ''
        assert response.data['label'] == '未设置'
        assert response.data['total_qty'] == 12

    @patch('iwork.api_views.get_effective_work_minutes', return_value=210)
    @patch(
        'iwork.api_views._snapshot_state',
        return_value=SimpleNamespace(snapshot_version='history-v1'),
    )
    def test_historical_detail_reads_local_snapshot(
        self,
        _mock_state,
        _mock_minutes,
    ):
        """历史初版款号详情只能读取本地历史快照。"""
        from iwork.api_views import initial_style_detail

        local_data = {
            'SO3-L3A': [{
                'reg_per_sys_id': 1001,
                'steps': [{
                    'stepno': 1,
                    'qty': 15,
                    'workorder': 'WO-1',
                    'initial_style_no': 'BU-1',
                    'output_value': 3.0,
                }],
            }],
        }
        request = APIRequestFactory().get('/', {
            'initial_style_no': 'BU-1',
            'date': '2026-08-10',
        })
        with patch(
            'iwork.api_views.local_get_batch_flow_employees',
            return_value=local_data,
        ) as read_local, patch(
            'iwork.api_views.READ_MODEL.details',
        ) as read_realtime:
            response = initial_style_detail(request)

        assert response.status_code == 200
        assert response.data['total_qty'] == 15
        assert response.data['source'] == 'local_snapshot'
        read_local.assert_called_once_with(date(2026, 8, 10))
        read_realtime.assert_not_called()

    def test_routes_keep_style_value_in_query_string(self):
        """初版款号 API 和页面应使用查询参数，兼容斜杠及空款号。"""
        from django.urls import reverse

        assert reverse('detail-initial-style-overview') == (
            '/api/dashboard/detail/initial-style-overview/'
        )
        assert reverse('detail-initial-style-detail') == (
            '/api/dashboard/detail/initial-style/'
        )
        assert reverse('production-detail-initial-style') == (
            '/production/detail-data/initial-style/'
        )


class TestProductOverviewEndpoint:
    """GET /api/dashboard/detail/product-overview/"""

    def test_uses_versioned_snapshot(self):
        """产品概览读取版本化详情视图。"""
        from iwork.api_views import product_overview

        cached = {
            'products': [{
                'wrk_orders': [{
                    'stepnos': [{
                        'stepno': 70,
                        'description': '后整',
                        'step_time': 0.331,
                        'output_value': 33.1,
                    }],
                }],
            }],
            'normal_flows': ['SO3-L3A'],
        }
        with patch(
            'iwork.api_views.READ_MODEL.detail',
            return_value=_snapshot_result(cached),
        ) as read:
            response = product_overview(
                APIRequestFactory().get('/api/dashboard/detail/product-overview/')
            )

        assert response.status_code == 200
        assert response.data['products'] == cached['products']
        assert response.data['normal_flows'] == ['SO3-L3A']
        assert response.data['source'] == 'redis_snapshot'
        read.assert_called_once()


# ============================================================================
# SSE 推送 + 目标产量设置 测试


class TestDashboardStream:
    """dashboard_stream SSE 视图测试"""

    @pytest.mark.asyncio
    async def test_returns_event_stream_response(self):
        """SSE 视图返回 StreamingHttpResponse"""
        from iwork.api_views import dashboard_stream
        from django.http import StreamingHttpResponse

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/')
        response = await dashboard_stream(request)

        assert isinstance(response, StreamingHttpResponse)
        assert response['Content-Type'] == 'text/event-stream'
        assert response['Cache-Control'] == 'no-cache'

    @pytest.mark.asyncio
    async def test_sse_announces_lease_expiry_before_reauthorization(self):
        """租约到期前发送续租事件，再正常结束连接以触发重新授权。"""
        from iwork.api_views import dashboard_stream

        factory = APIRequestFactory()
        payload = {
            'data': {'total_qty': 500},
            'process_list': [70],
            'detail_overview': {},
        }
        with (
            patch(
                'iwork.api_views.READ_MODEL.stream_payload',
                return_value=_snapshot_result(payload),
            ),
            patch('iwork.api_views.SSE_CONNECTION_LEASE_SECONDS', 0.2),
            patch('iwork.api_views.SSE_LEASE_EXPIRING_NOTICE_SECONDS', 0.05),
            patch('iwork.api_views.SSE_HEARTBEAT_SECONDS', 60.0),
        ):
            response = await dashboard_stream(factory.get('/api/dashboard/stream/'))
            stream = response.streaming_content
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            first_chunk = await anext(stream)
            lease_chunk = await asyncio.wait_for(anext(stream), timeout=0.19)
            notice_elapsed = loop.time() - started_at

            assert first_chunk.decode('utf-8').startswith('data: ')
            assert lease_chunk.decode('utf-8') == (
                'event: lease_expiring\n'
                'data: {"type": "lease_expiring"}\n\n'
            )
            assert notice_elapsed < 0.19
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(stream), timeout=0.1)
            assert loop.time() - started_at >= 0.18

    @pytest.mark.asyncio
    async def test_sse_first_chunk_has_valid_json(self):
        """SSE 第一条消息包含快照版本与同版本数据。"""
        from iwork.api_views import dashboard_stream

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/')
        payload = {
            'data': {'total_qty': 500, 'date': '2026-07-31'},
            'process_list': [70, 69],
            'detail_overview': [{'flow': 'VCO-L5', 'qty': 200}],
        }
        with patch(
            'iwork.api_views.READ_MODEL.stream_payload',
            return_value=_snapshot_result(payload),
        ):
            response = await dashboard_stream(request)
            first_chunk = (await anext(response.streaming_content)).decode('utf-8')
        assert first_chunk.startswith('data: ')
        assert first_chunk.endswith('\n\n')

        json_str = first_chunk[6:-2]
        data = json.loads(json_str)
        assert data['type'] == 'dashboard_update'
        assert data['snapshot_version'] == 'v-test'
        assert 'timestamp' in data
        assert data['data']['total_qty'] == 500
        assert data['process_list'] == [70, 69]
        assert data['detail_overview'] == [{'flow': 'VCO-L5', 'qty': 200}]

    @pytest.mark.asyncio
    async def test_notification_mode_sends_only_snapshot_metadata(self):
        """生产详情通知模式不得发送实时看板的大体积业务负载。"""
        from iwork.api_views import dashboard_stream

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/?mode=notification')
        with (
            patch(
                'iwork.api_views.READ_MODEL.snapshot_metadata',
                return_value=_snapshot_result({}),
            ) as read_metadata,
            patch('iwork.api_views.READ_MODEL.stream_payload') as read_payload,
        ):
            response = await dashboard_stream(request)
            first_chunk = (await anext(response.streaming_content)).decode('utf-8')

        data = json.loads(first_chunk[6:-2])
        assert data == {
            'type': 'snapshot_published',
            'business_date': date.today().isoformat(),
            'snapshot_version': 'v-test',
            'generated_at': '2026-07-31T12:00:00+07:00',
            'stale': False,
        }
        read_metadata.assert_called_once_with(date.today())
        read_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_sse_respects_stepno_filter(self):
        """SSE 视图支持 stepno 参数过滤"""
        from iwork.api_views import dashboard_stream

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/?stepno=69')
        payload = {'data': {'total_qty': 300}, 'process_list': [69], 'detail_overview': {}}
        with patch(
            'iwork.api_views.READ_MODEL.stream_payload',
            return_value=_snapshot_result(payload),
        ) as read:
            response = await dashboard_stream(request)
            await anext(response.streaming_content)
        read.assert_called_once_with(date.today(), [69])

    @pytest.mark.asyncio
    async def test_unavailable_snapshot_waits_for_heartbeat_before_retry(self):
        """快照不可用时不得无等待循环读取 Redis 和刷屏错误事件。"""
        from iwork.api_views import dashboard_stream
        from iwork.read_model.errors import ReadModelNotReadyError
        from iwork.sse_events import SharedSSEPayloadCache

        factory = APIRequestFactory()
        with (
            patch(
                'iwork.api_views.READ_MODEL.stream_payload',
                side_effect=ReadModelNotReadyError('测试快照不可用'),
            ) as read,
            patch('iwork.api_views.SSE_HEARTBEAT_SECONDS', 0.01),
            patch(
                'iwork.api_views.get_sse_payload_cache',
                return_value=SharedSSEPayloadCache(),
            ),
        ):
            response = await dashboard_stream(factory.get('/api/dashboard/stream/'))
            first_chunk = (await anext(response.streaming_content)).decode('utf-8')
            second_chunk = (
                await asyncio.wait_for(
                    anext(response.streaming_content),
                    timeout=0.2,
                )
            ).decode('utf-8')
            await response.streaming_content.aclose()

        assert first_chunk.startswith('event: snapshot_unavailable')
        assert second_chunk == ': heartbeat\n\n'
        assert read.call_count == 1

    @pytest.mark.asyncio
    async def test_published_snapshot_reaches_all_connected_clients_without_connection_delay(self):
        """错开建立的连接应在同一次快照发布后立即收到相同版本。"""
        from iwork.api_views import dashboard_stream

        class TestSnapshotBroker:
            """测试使用的进程内快照发布适配器。"""

            def __init__(self):
                """初始化订阅队列集合。"""
                self.queues = set()

            @asynccontextmanager
            async def subscribe(self):
                """注册并在退出时清理单个 SSE 订阅。"""
                queue = asyncio.Queue(maxsize=1)
                self.queues.add(queue)
                try:
                    yield queue
                finally:
                    self.queues.discard(queue)

            async def publish(self, snapshot_version):
                """向所有已连接客户端广播快照版本。"""
                for queue in self.queues:
                    queue.put_nowait({'snapshot_version': snapshot_version})

        state = {'version': 'v1', 'qty': 1000}
        broker = TestSnapshotBroker()

        def current_snapshot(*_args):
            """返回当前测试快照。"""
            return _snapshot_result(
                {
                    'data': {'total_qty': state['qty']},
                    'process_list': [70],
                    'detail_overview': {},
                },
                snapshot_version=state['version'],
            )

        factory = APIRequestFactory()
        with (
            patch('iwork.api_views.READ_MODEL.stream_payload', side_effect=current_snapshot),
            patch('iwork.api_views.get_snapshot_notification_broker', return_value=broker),
        ):
            response_a = await dashboard_stream(factory.get('/api/dashboard/stream/?stepno=70'))
            stream_a = response_a.streaming_content
            first_a = json.loads((await anext(stream_a)).decode('utf-8')[6:-2])

            response_b = await dashboard_stream(factory.get('/api/dashboard/stream/?stepno=70'))
            stream_b = response_b.streaming_content
            first_b = json.loads((await anext(stream_b)).decode('utf-8')[6:-2])

            assert first_a['snapshot_version'] == 'v1'
            assert first_b['snapshot_version'] == 'v1'

            state.update(version='v2', qty=2000)
            await broker.publish('v2')

            second_a, second_b = await asyncio.gather(
                asyncio.wait_for(anext(stream_a), timeout=0.5),
                asyncio.wait_for(anext(stream_b), timeout=0.5),
            )

        event_a = json.loads(second_a.decode('utf-8')[6:-2])
        event_b = json.loads(second_b.decode('utf-8')[6:-2])
        assert event_a['snapshot_version'] == 'v2'
        assert event_b['snapshot_version'] == 'v2'
        assert event_a['data']['total_qty'] == 2000
        assert event_b['data']['total_qty'] == 2000


class TestSetTargets:
    """set_targets HTTP POST 视图测试"""

    pytestmark = pytest.mark.django_db(databases=['default', 'iwork_local'])

    @pytest.fixture(autouse=True)
    def trusted_admin_identity(self, monkeypatch):
        """为直接调用视图的旧测试注入当前可信管理员身份。"""
        from iwork.identity import IworkIdentity

        original_post = APIRequestFactory.post

        def post_with_identity(factory, *args, **kwargs):
            """创建携带可信管理员身份的 DRF 请求。"""
            request = original_post(factory, *args, **kwargs)
            request.iwork_identity = IworkIdentity(
                subject='test-admin-subject',
                username='test-admin',
                keycloak_groups=['/admin'],
                is_admin=True,
            )
            return request

        monkeypatch.setattr(APIRequestFactory, 'post', post_with_identity)

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

    @patch('iwork.api_views.cache')
    def test_legacy_zero_target_replaces_previous_database_value(self, mock_cache):
        """旧格式合法零目标必须落库，不能在缓存过期后恢复旧值。"""
        from iwork.api_views import set_targets
        from iwork.local_models import TargetProduction
        from iwork.statistics import get_business_date

        target_date = get_business_date()
        target = TargetProduction.objects.using('iwork_local').create(
            target_date=target_date,
            employee_id='1001',
            workorder='',
            target_qty=100,
        )
        request = APIRequestFactory().post(
            '/api/dashboard/set-targets/',
            data={'targets': {'1001': 0}},
            format='json',
        )

        response = set_targets(request)

        target.refresh_from_db(using='iwork_local')
        assert response.status_code == 200
        assert target.target_qty == 0

    @patch('iwork.api_views.save_group_target')
    @patch('iwork.api_views.cache')
    def test_set_group_target_success(self, mock_cache, mock_save_group_target):
        """整组目标应按业务日期和生产组持久化，并刷新当天缓存。"""
        from iwork.api_views import set_targets

        request = APIRequestFactory().post(
            '/api/dashboard/set-targets/',
            data={'flow': 'SO3-L3A', 'group_target': 1000},
            format='json',
        )

        mock_save_group_target.return_value = SimpleNamespace(is_late=False)
        response = set_targets(request)

        assert response.status_code == 200
        assert response.data['status'] == 'ok'
        assert response.data['flow'] == 'SO3-L3A'
        assert response.data['group_target'] == 1000
        mock_save_group_target.assert_called_once_with(
            identity=request.iwork_identity,
            target_date=date.today(),
            flow_name='SO3-L3A',
            target_qty=1000,
            planned_work_minutes=None,
        )
        mock_cache.set.assert_called_once_with(
            f'group_target:{date.today().isoformat()}:SO3-L3A',
            1000,
            timeout=mock_cache.set.call_args.kwargs['timeout'],
        )

    @patch('iwork.api_views.GroupTargetProduction.objects.update_or_create')
    def test_set_group_target_rejects_negative_value(self, mock_update_or_create):
        """负数整组目标应返回 400，且不能写入数据库。"""
        from iwork.api_views import set_targets

        request = APIRequestFactory().post(
            '/api/dashboard/set-targets/',
            data={'flow': 'SO3-L3A', 'group_target': -1},
            format='json',
        )

        response = set_targets(request)

        assert response.status_code == 400
        assert response.data['error'] == '整组目标不能小于 0'
        mock_update_or_create.assert_not_called()

    @patch('iwork.api_views.save_group_target')
    @patch('iwork.api_views.cache')
    def test_set_group_target_saves_work_hours(self, mock_cache, mock_save_group_target):
        """保存整组目标时应同时保存计划工作时长。"""
        from iwork.api_views import set_targets

        request = APIRequestFactory().post(
            '/api/dashboard/set-targets/',
            data={'flow': 'SO3-L3A', 'group_target': 1000, 'work_hours': 10},
            format='json',
        )

        mock_save_group_target.return_value = SimpleNamespace(is_late=False)
        response = set_targets(request)

        assert response.status_code == 200
        assert response.data['work_hours'] == 10
        mock_save_group_target.assert_called_once_with(
            identity=request.iwork_identity,
            target_date=date.today(),
            flow_name='SO3-L3A',
            target_qty=1000,
            planned_work_minutes=600,
        )
        assert mock_cache.set.call_count == 2

    @pytest.mark.parametrize('work_hours', [0, 0.001, 25, 'invalid'])
    @patch('iwork.api_views.GroupTargetProduction.objects.update_or_create')
    def test_set_group_target_rejects_invalid_work_hours(
        self,
        mock_update_or_create,
        work_hours,
    ):
        """计划工作时长必须大于0且不超过24小时。"""
        from iwork.api_views import set_targets

        request = APIRequestFactory().post(
            '/api/dashboard/set-targets/',
            data={
                'flow': 'SO3-L3A',
                'group_target': 1000,
                'work_hours': work_hours,
            },
            format='json',
        )

        response = set_targets(request)

        assert response.status_code == 400
        assert response.data['error'] == '工作时间必须大于 0 且不超过 24 小时'
        mock_update_or_create.assert_not_called()

    @patch('iwork.api_views.GroupTargetProduction.objects.update_or_create')
    def test_set_group_target_rejects_fractional_value(self, mock_update_or_create):
        """小数整组目标不能被静默截断为整数。"""
        from iwork.api_views import set_targets

        request = APIRequestFactory().post(
            '/api/dashboard/set-targets/',
            data={'flow': 'SO3-L3A', 'group_target': 1000.5},
            format='json',
        )

        response = set_targets(request)

        assert response.status_code == 400
        assert response.data['error'] == '整组目标必须是整数'
        mock_update_or_create.assert_not_called()
