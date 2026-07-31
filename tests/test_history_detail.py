from datetime import date, datetime
from unittest.mock import patch

import pytest
from django.utils import timezone

from iwork.local_models import (
    HistoricalProductionFact,
    HistoricalStepSnapshot,
    HistoricalSyncState,
    TargetProduction,
)
from iwork.history_store import (
    HistorySnapshotPayload,
    SnapshotBuildInProgressError,
    SnapshotBuildLeaseLostError,
    snapshot_history_date,
)


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_historical_flow_detail_uses_local_snapshot_by_default(client):
    """历史 Flow 详情应默认读取本地快照。"""
    target_date = date(2026, 7, 15)
    registered_at = timezone.make_aware(datetime(2026, 7, 15, 10))
    HistoricalProductionFact.objects.using('iwork_local').create(
        production_date=target_date,
        event_hour=10,
        registered_date=registered_at,
        registered_time=registered_at,
        flow='SO5-L5C',
        station_id='L5C',
        employee_id=1942,
        wrk_order='BU1208A',
        step_no=38,
        qty=183,
        source_record_count=3,
    )
    HistoricalStepSnapshot.objects.using('iwork_local').create(
        snapshot_date=target_date,
        wrk_order='BU1208A',
        step_no=38,
        description='翻猪肠绑绳',
        step_time=0.131,
        style_no='BU1208',
        product_name='Test product',
        order_no='SO-TEST',
    )
    HistoricalSyncState.objects.using('iwork_local').create(
        snapshot_date=target_date,
        status=HistoricalSyncState.Status.SUCCESS,
        source_row_count=3,
        source_total_qty=183,
        fact_row_count=1,
        metadata_row_count=1,
    )
    TargetProduction.objects.using('iwork_local').bulk_create([
        TargetProduction(
            target_date=date(2026, 7, 14),
            employee_id='1942',
            workorder='',
            target_qty=999,
        ),
        TargetProduction(
            target_date=target_date,
            employee_id='1942',
            workorder='',
            target_qty=200,
        ),
        TargetProduction(
            target_date=date(2026, 7, 14),
            employee_id='1942',
            workorder='BU1208A',
            target_qty=888,
        ),
        TargetProduction(
            target_date=target_date,
            employee_id='1942',
            workorder='BU1208A',
            target_qty=150,
        ),
    ])

    response = client.get(
        '/api/dashboard/detail/flow/SO5-L5C/?date=2026-07-15&mode=remote'
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['source'] == 'local_snapshot'
    assert payload['snapshot_date'] == '2026-07-15'
    assert payload['employees'][0]['reg_per_sys_id'] == 1942
    assert payload['employees'][0]['steps'] == [
        {
            'stepno': 38,
            'qty': 183,
            'workorder': 'BU1208A',
            'description': '翻猪肠绑绳',
            'step_time': 0.131,
            'output_value': pytest.approx(23.973),
        }
    ]
    assert payload['employees'][0]['output_value'] == pytest.approx(23.973)
    assert payload['employees'][0]['employee_efficiency'] is None
    assert payload['employees'][0]['target'] == 200
    assert payload['employees'][0]['wo_targets'] == {'BU1208A': 150}


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_historical_product_overview_uses_snapshot_metadata(client):
    """历史产品概览应使用快照元数据。"""
    target_date = date(2026, 7, 15)
    registered_at = timezone.make_aware(datetime(2026, 7, 15, 10))
    HistoricalProductionFact.objects.using('iwork_local').create(
        production_date=target_date,
        event_hour=10,
        registered_date=registered_at,
        registered_time=registered_at,
        flow='SO5-L5C',
        station_id='L5C',
        employee_id=1942,
        wrk_order='BU1208A',
        step_no=38,
        qty=183,
        source_record_count=3,
    )
    HistoricalStepSnapshot.objects.using('iwork_local').create(
        snapshot_date=target_date,
        wrk_order='BU1208A',
        step_no=38,
        description='翻猪肠绑绳',
        step_time=0.131,
        style_no='BU1208',
        product_name='Sage pile jacket',
        order_no='SO-TEST',
    )
    HistoricalSyncState.objects.using('iwork_local').create(
        snapshot_date=target_date,
        status=HistoricalSyncState.Status.SUCCESS,
        source_row_count=3,
        source_total_qty=183,
        fact_row_count=1,
        metadata_row_count=1,
    )

    response = client.get(
        '/api/dashboard/detail/product-overview/?date=2026-07-15'
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['source'] == 'local_snapshot'
    product = payload['products'][0]
    assert product['product_name'] == 'Sage pile jacket'
    assert product['total_qty'] == 183
    step = product['wrk_orders'][0]['stepnos'][0]
    assert step['description'] == '翻猪肠绑绳'
    assert step['step_time'] == 0.131
    assert step['output_value'] == pytest.approx(23.973)
    assert step['flows'] == [{'flow': 'SO5-L5C', 'qty': 183, 'workers': 1}]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_snapshot_history_date_publishes_validated_snapshot():
    """历史快照应校验载荷并以递增版本发布。"""
    target_date = date(2026, 7, 15)

    class FakeSource:
        def load(self, requested_date):
            assert requested_date == target_date
            return HistorySnapshotPayload(
                facts=[{
                    'event_hour': 10,
                    'flow': 'SO5-L5C',
                    'station_id': 'L5C',
                    'employee_id': 1942,
                    'wrk_order': 'BU1208A',
                    'step_no': 38,
                    'qty': 183,
                    'source_record_count': 3,
                }],
                metadata=[{
                    'wrk_order': 'BU1208A',
                    'step_no': 38,
                    'description': '翻猪肠绑绳',
                    'step_time': 0.131,
                    'style_no': 'BU1208',
                    'product_name': 'Sage pile jacket',
                    'order_no': 'SO-TEST',
                }],
                source_row_count=3,
                source_total_qty=183,
            )

    state = snapshot_history_date(target_date, source=FakeSource())

    assert state.status == HistoricalSyncState.Status.SUCCESS
    assert state.snapshot_version == 1
    assert state.fact_row_count == 1
    assert state.metadata_row_count == 1
    assert HistoricalProductionFact.objects.using('iwork_local').filter(
        production_date=target_date,
    ).count() == 1

    refreshed = snapshot_history_date(target_date, source=FakeSource())
    assert refreshed.snapshot_version == 2
    assert HistoricalProductionFact.objects.using('iwork_local').filter(
        production_date=target_date,
    ).count() == 1

    class FailingSource:
        """模拟远程读取失败的数据源。"""

        def load(self, requested_date):
            """在确认请求日期后抛出远程读取异常。"""
            assert requested_date == target_date
            raise RuntimeError('远程读取失败')

    with pytest.raises(RuntimeError, match='远程读取失败'):
        snapshot_history_date(target_date, source=FailingSource())

    preserved = HistoricalSyncState.objects.using('iwork_local').get(
        snapshot_date=target_date,
    )
    assert preserved.status == HistoricalSyncState.Status.SUCCESS
    assert preserved.snapshot_version == 2
    assert preserved.error_message == '远程读取失败'
    assert HistoricalProductionFact.objects.using('iwork_local').filter(
        production_date=target_date,
        qty=183,
    ).count() == 1


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_snapshot_history_date_rejects_duplicate_build_before_loading_source():
    """同日期已有构建任务时，服务层应在远程查询前拒绝重复任务。"""
    from django.core.cache import cache

    target_date = date(2026, 7, 15)
    lock_key = f'history:snapshot:build:{target_date.isoformat()}'
    cache.set(lock_key, 'existing-owner', timeout=900)

    class UnexpectedSource:
        """一旦被调用就让测试失败的远程数据源。"""

        def load(self, _requested_date):
            """拒绝任何远程读取调用。"""
            raise AssertionError('锁冲突时不应访问远程数据源')

    try:
        with pytest.raises(SnapshotBuildInProgressError):
            snapshot_history_date(target_date, source=UnexpectedSource())
    finally:
        cache.delete(lock_key)


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_snapshot_history_date_does_not_release_a_replacement_lock():
    """旧任务失去锁所有权后，不得删除新任务持有的锁。"""
    from django.core.cache import cache

    target_date = date(2026, 7, 15)
    lock_key = f'history:snapshot:build:{target_date.isoformat()}'

    class ReplacingSource:
        """模拟构建期间原锁过期并由新任务取得所有权。"""

        def load(self, _requested_date):
            """替换锁令牌并返回空但有效的快照载荷。"""
            cache.set(lock_key, 'new-owner', timeout=900)
            return HistorySnapshotPayload(
                facts=[],
                metadata=[],
                source_row_count=0,
                source_total_qty=0,
            )

    try:
        with pytest.raises(SnapshotBuildLeaseLostError):
            snapshot_history_date(target_date, source=ReplacingSource())
        assert cache.get(lock_key) == 'new-owner'
    finally:
        cache.delete(lock_key)


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@patch('iwork.history_store.HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL', 0.01)
@patch('iwork.history_store.cache.lock')
def test_snapshot_history_date_renews_lock_during_long_build(mock_cache_lock):
    """长时间构建期间应续租分布式锁并在完成后释放。"""
    from time import sleep

    target_date = date(2026, 7, 15)
    lock = mock_cache_lock.return_value
    lock.acquire.return_value = True
    lock.owned.return_value = True
    lock.extend.return_value = True

    class SlowSource:
        """模拟超过一次续租间隔的远程数据源。"""

        def load(self, _requested_date):
            """等待续租线程运行后返回空快照。"""
            sleep(0.04)
            return HistorySnapshotPayload(
                facts=[],
                metadata=[],
                source_row_count=0,
                source_total_qty=0,
            )

    snapshot_history_date(target_date, source=SlowSource())

    lock.extend.assert_called()
    lock.release.assert_called_once_with()


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_missing_history_snapshot_can_be_built_then_read(client):
    """缺失的历史快照应可构建后读取。"""
    payload = HistorySnapshotPayload(
        facts=[{
            'event_hour': 10,
            'flow': 'SO5-L5C',
            'station_id': 'L5C',
            'employee_id': 1942,
            'wrk_order': 'BU1208A',
            'step_no': 38,
            'qty': 183,
            'source_record_count': 3,
        }],
        metadata=[{
            'wrk_order': 'BU1208A',
            'step_no': 38,
            'description': '翻猪肠绑绳',
            'step_time': 0.131,
            'style_no': 'BU1208',
            'product_name': 'Sage pile jacket',
            'order_no': 'SO-TEST',
        }],
        source_row_count=3,
        source_total_qty=183,
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            'iwork.history_store.RemoteHistorySource.load',
            lambda _source, requested_date: payload,
        )
        build_response = client.post(
            '/api/history/snapshots/2026-07-15/ensure/'
        )

    assert build_response.status_code == 202
    build_payload = build_response.json()
    assert build_payload['created'] is False
    assert build_payload['code'] == 'history_snapshot_building'

    detail_response = client.get(
        '/api/dashboard/detail/flow/SO5-L5C/?date=2026-07-15'
    )
    assert detail_response.status_code == 200
    assert detail_response.json()['source'] == 'local_snapshot'


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_reports_build_in_progress(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """同日期已经入队时，API 应返回可轮询的 202。"""

    with patch('iwork.api_views_local.cache.add', return_value=False), patch(
        'iwork.api_views_local.build_history_snapshot.delay',
    ) as build_snapshot:
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 202
    assert response.json() == {
        'created': False,
        'code': 'history_snapshot_building',
        'message': '本地历史快照正在构建',
        'retry_after': 2,
    }
    build_snapshot.assert_not_called()


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_delegates_build_to_history_store(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """API 应将远程构建委托给 Celery 后台任务。"""

    with patch('iwork.api_views_local.cache.add', return_value=True), patch(
        'iwork.api_views_local.build_history_snapshot.delay',
    ) as build_snapshot:
        build_snapshot.return_value.id = 'task-history-1'
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 202
    build_snapshot.assert_called_once_with('2026-07-15')


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_returns_503_when_queue_lock_cache_is_unavailable(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """Redis 无法创建入队标记时应明确返回 503，且不得重复提交任务。"""
    with patch(
        'iwork.api_views_local.cache.add',
        side_effect=ConnectionError('Redis unavailable'),
    ), patch('iwork.api_views_local.build_history_snapshot.delay') as build_snapshot:
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 503
    assert response.json()['code'] == 'history_snapshot_queue_unavailable'
    build_snapshot.assert_not_called()


def test_snapshot_history_command_skips_build_in_progress():
    """人工命令遇到同日期构建时应跳过且不报告失败。"""
    from iwork.management.commands.snapshot_history import Command

    command = Command()
    options = {
        'target_date': '2026-07-15',
        'start': None,
        'end': None,
        'continue_on_error': False,
    }
    with patch(
        'iwork.management.commands.snapshot_history.snapshot_history_date',
        side_effect=SnapshotBuildInProgressError('正在构建'),
    ) as build_snapshot:
        command.handle(**options)

    build_snapshot.assert_called_once_with(date(2026, 7, 15))

@pytest.mark.django_db(databases=['default', 'iwork_local'], transaction=True)
def test_history_dashboard_stats_read_from_persisted_facts(client):
    """历史看板统计应读取持久化事实。"""
    target_date = date(2026, 7, 15)
    registered_at = timezone.make_aware(datetime(2026, 7, 15, 10))
    HistoricalProductionFact.objects.using('iwork_local').create(
        production_date=target_date,
        event_hour=10,
        registered_date=registered_at,
        registered_time=registered_at,
        flow='SO5-L5C',
        station_id='L5C',
        employee_id=1942,
        wrk_order='BU1208A',
        step_no=38,
        qty=183,
        source_record_count=3,
    )
    HistoricalSyncState.objects.using('iwork_local').create(
        snapshot_date=target_date,
        status=HistoricalSyncState.Status.SUCCESS,
        source_row_count=3,
        source_total_qty=183,
        fact_row_count=1,
        metadata_row_count=0,
    )

    response = client.get('/api/history/date/2026-07-15/')

    assert response.status_code == 200
    payload = response.json()
    assert payload['source'] == 'local_snapshot'
    assert payload['snapshot_date'] == '2026-07-15'
    assert payload['snapshot_version'] == 1
    assert payload['total_qty'] == 183
    assert payload['workorder_count'] == 1
    assert payload['all_stepnos'] == [38]
    assert payload['hourly_stats'] == [{'hour': 10, 'qty': 183}]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_history_dashboard_reports_missing_snapshot_without_remote_fallback(client):
    """快照缺失时不应回退远程查询。"""
    response = client.get('/api/history/date/2026-07-15/?mode=remote')

    assert response.status_code == 404
    assert response.json() == {
        'error': '该日期尚未生成本地历史快照',
        'code': 'history_snapshot_not_found',
    }


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@pytest.mark.parametrize('url', [
    '/api/dashboard/processes/?date=2026-07-15',
    '/api/dashboard/workorders/?date=2026-07-15&page_size=100&stepno=70',
    '/api/dashboard/workorders/BU1208A/?date=2026-07-15',
])
def test_all_historical_read_endpoints_report_missing_snapshot(client, url):
    """所有历史读取端点都应报告快照缺失。"""
    response = client.get(url)

    assert response.status_code == 404
    assert response.json()['code'] == 'history_snapshot_not_found'
