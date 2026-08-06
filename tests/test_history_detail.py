from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Event
from time import sleep
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

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
    """历史产品概览应使用快照元数据并保留非普通线 Flow。"""
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
    HistoricalProductionFact.objects.using('iwork_local').create(
        production_date=target_date,
        event_hour=11,
        registered_date=registered_at,
        registered_time=registered_at,
        flow='Finishing-QC1',
        station_id='QC1',
        employee_id=1943,
        wrk_order='BU1208A',
        step_no=80,
        qty=50,
        source_record_count=1,
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
    HistoricalStepSnapshot.objects.using('iwork_local').create(
        snapshot_date=target_date,
        wrk_order='BU1208A',
        step_no=80,
        description='成品检查',
        step_time=0.2,
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
    assert product['total_qty'] == 233
    assert 'SO5-L5C' in payload['normal_flows']
    assert 'Finishing-QC1' not in payload['normal_flows']
    steps = product['wrk_orders'][0]['stepnos']
    step = steps[0]
    assert step['description'] == '翻猪肠绑绳'
    assert step['step_time'] == 0.131
    assert step['output_value'] == pytest.approx(23.973)
    assert step['flows'] == [{'flow': 'SO5-L5C', 'qty': 183, 'workers': 1}]
    assert steps[1]['flows'] == [
        {'flow': 'Finishing-QC1', 'qty': 50, 'workers': 1},
    ]


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

    assert build_response.status_code == 200
    build_payload = build_response.json()
    assert build_payload['created'] is False
    assert build_payload['message'] == '本地历史快照已生成'

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
    """同日期真实构建锁仍存在时，API 应返回202且不得重复提交任务。"""
    from django.core.cache import cache

    build_key = 'history:snapshot:build:2026-07-15'
    build_lock = cache.lock(build_key, timeout=60, thread_local=False)
    assert build_lock.acquire(blocking=False)

    try:
        with patch(
            'iwork.api_views_local.build_history_snapshot.delay',
        ) as build_snapshot:
            response = client.post('/api/history/snapshots/2026-07-15/ensure/')
    finally:
        build_lock.release()

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
def test_ensure_snapshot_requeues_after_existing_builder_releases_lock(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """外部构建锁释放后应清理等待标记并恢复提交，不得误报构建中30分钟。"""
    from django.core.cache import cache

    build_key = 'history:snapshot:build:2026-07-15'
    build_lock = cache.lock(build_key, timeout=60, thread_local=False)
    assert build_lock.acquire(blocking=False)
    build_lock.release()

    try:
        with patch(
            'iwork.api_views_local.build_history_snapshot.delay',
        ) as build_snapshot:
            build_snapshot.return_value.id = 'task-history-recovered'
            response = client.post('/api/history/snapshots/2026-07-15/ensure/')
    finally:
        cache.delete('history:snapshot:request:2026-07-15')

    assert response.status_code == 202
    assert response.json()['message'] == '本地历史快照已提交后台构建'
    build_snapshot.assert_called_once_with('2026-07-15', ANY)


def test_snapshot_request_allows_only_one_concurrent_claim():
    """并发轮询只能有一个请求取得带所有权令牌的入队资格。"""
    from django.conf import settings
    from iwork.api_views_local import _claim_snapshot_request

    target_date = '2026-07-15'
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_claim_snapshot_request, target_date)
            for _ in range(8)
        ]
        claims = [future.result() for future in futures]

    winners = [claim for claim in claims if claim[3]]
    assert len(winners) == 1
    request_lock, request_token, request_lease, _claimed = winners[0]
    assert request_token
    assert request_lock.owned()
    assert request_lock.timeout == settings.HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT
    request_lease.stop()
    request_lock.release()


def test_snapshot_request_renews_during_slow_build_lock_check(settings):
    """真实构建锁检查超过初始租约时也不得让第二个请求获权。"""
    from django.core.cache import cache
    from iwork.api_views_local import _claim_snapshot_request

    settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT = 1
    settings.HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT = 1
    settings.HISTORY_SNAPSHOT_REQUEST_RENEW_INTERVAL = 0.1
    check_started = Event()

    def slow_build_check(_target_date):
        """模拟 Redis 构建锁检查长时间阻塞。"""
        check_started.set()
        sleep(1.3)
        return False

    try:
        with patch(
            'iwork.api_views_local.snapshot_build_in_progress',
            side_effect=slow_build_check,
        ) as build_check, ThreadPoolExecutor(max_workers=1) as executor:
            first_claim_future = executor.submit(
                _claim_snapshot_request,
                '2026-07-15',
            )
            assert check_started.wait(timeout=1)
            sleep(1.05)
            second_claim = _claim_snapshot_request('2026-07-15')
            first_claim = first_claim_future.result(timeout=2)

        assert first_claim[3] is True
        assert second_claim[3] is False
        assert build_check.call_count == 1
        first_claim[2].stop()
        first_claim[0].release()
    finally:
        cache.delete('history:snapshot:request:2026-07-15')


def test_late_web_renewal_cannot_shorten_celery_request_lease():
    """晚到的Web续租只能增加TTL，不得覆盖Celery提升后的长租约。"""
    from iwork.snapshot_request_lock import (
        acquire_request_lock,
        cap_request_lock_ttl,
        renew_request_lock,
    )

    request_lock, _request_token, acquired = acquire_request_lock(
        '2026-07-15',
        timeout=1,
    )
    assert acquired
    renew_request_lock(request_lock, timeout=5)
    cap_request_lock_ttl(request_lock, timeout=1)

    sleep(1.1)

    assert request_lock.owned()
    request_lock.release()


def test_request_lease_caps_ttl_without_shortening_long_lease():
    """后台续租应补足短TTL且不缩短已提升的长租约。"""
    from iwork.snapshot_request_lock import RequestLockLease

    request_lock = MagicMock()
    request_lock.reacquire.return_value = True
    request_lock.cap_ttl.return_value = True
    lease = RequestLockLease(
        request_lock,
        timeout=1,
        renew_interval=0.1,
    ).start()

    sleep(0.35)
    lease.stop()

    assert request_lock.cap_ttl.call_count >= 2
    for call in request_lock.cap_ttl.call_args_list:
        assert call.args == (1,)
        assert call.kwargs == {}


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_delegates_build_to_history_store(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """API 应将远程构建委托给 Celery 后台任务。"""

    with patch(
        'iwork.api_views_local.build_history_snapshot.delay',
    ) as build_snapshot:
        build_snapshot.return_value.id = 'task-history-1'
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')
    from django.core.cache import cache
    cache.delete('history:snapshot:request:2026-07-15')

    assert response.status_code == 202
    build_snapshot.assert_called_once_with('2026-07-15', ANY)


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_returns_503_when_queue_lock_cache_is_unavailable(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """Redis 无法创建入队标记时应明确返回 503，且不得重复提交任务。"""
    with patch(
        'iwork.api_views_local.acquire_request_lock',
        side_effect=ConnectionError('Redis unavailable'),
    ), patch('iwork.api_views_local.build_history_snapshot.delay') as build_snapshot:
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 503
    assert response.json()['code'] == 'history_snapshot_queue_unavailable'
    build_snapshot.assert_not_called()


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_broker_failure_uses_short_self_healing_lock(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """Broker失败且锁释放异常时，请求锁也只能保留短暂待确认租约。"""
    from django.conf import settings

    request_lock = MagicMock()
    request_lock.timeout = settings.HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT
    request_lock.release.side_effect = ConnectionError('Redis unavailable')
    request_lease = MagicMock()
    request_lease.lost = False

    with patch(
        'iwork.api_views_local._claim_snapshot_request',
        return_value=(request_lock, 'request-token', request_lease, True),
    ), patch(
        'iwork.api_views_local.build_history_snapshot.delay',
        side_effect=ConnectionError('Broker unavailable'),
    ):
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 500
    assert request_lock.timeout == settings.HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT
    request_lease.stop.assert_called_once_with()
    request_lock.release.assert_called_once_with()


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_returns_503_when_confirmed_task_loses_request_lock(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """Broker确认后无法提升完整租约时，不得把入队状态报告为成功。"""
    request_lock = MagicMock()
    request_lease = MagicMock()
    request_lease.lost = True

    with patch(
        'iwork.api_views_local._claim_snapshot_request',
        return_value=(request_lock, 'request-token', request_lease, True),
    ), patch(
        'iwork.api_views_local.build_history_snapshot.delay',
        return_value=SimpleNamespace(id='task-with-lost-request-lock'),
    ):
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 503
    assert response.json()['code'] == 'history_snapshot_queue_unavailable'
    request_lease.stop.assert_called_once_with()
    request_lock.release.assert_not_called()


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_returns_503_when_full_request_lease_cannot_be_confirmed(
    _mock_business_date,
    _mock_snapshot_state,
    client,
):
    """Broker确认后完整请求租约提升失败时，不得返回已提交成功。"""
    request_lock = MagicMock()
    request_lease = MagicMock()
    request_lease.lost = False

    with patch(
        'iwork.api_views_local._claim_snapshot_request',
        return_value=(request_lock, 'request-token', request_lease, True),
    ), patch(
        'iwork.api_views_local.build_history_snapshot.delay',
        return_value=SimpleNamespace(id='task-with-short-request-lock'),
    ), patch(
        'iwork.api_views_local.renew_request_lock',
        return_value=False,
    ):
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 503
    assert response.json()['code'] == 'history_snapshot_queue_unavailable'
    request_lease.stop.assert_called_once_with()
    request_lock.release.assert_not_called()


@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_renews_request_lock_during_slow_broker_submission(
    _mock_business_date,
    _mock_snapshot_state,
    client,
    settings,
):
    """Broker提交超过待确认租约时，轮询仍不得产生第二个后台任务。"""
    from django.core.cache import cache
    from django.test import Client

    settings.HISTORY_SNAPSHOT_REQUEST_PENDING_TIMEOUT = 1
    settings.HISTORY_SNAPSHOT_REQUEST_RENEW_INTERVAL = 0.1
    delay_started = Event()

    def slow_delay(_target_date, _request_token):
        """模拟超过初始请求锁租约的 Broker 阻塞。"""
        delay_started.set()
        sleep(1.3)
        return SimpleNamespace(id='slow-broker-task')

    try:
        with patch(
            'iwork.api_views_local.build_history_snapshot.delay',
            side_effect=slow_delay,
        ) as build_snapshot, ThreadPoolExecutor(max_workers=1) as executor:
            first_response_future = executor.submit(
                Client().post,
                '/api/history/snapshots/2026-07-15/ensure/',
            )
            assert delay_started.wait(timeout=1)
            sleep(1.05)
            second_response = client.post(
                '/api/history/snapshots/2026-07-15/ensure/',
            )
            first_response = first_response_future.result(timeout=2)
    finally:
        cache.delete('history:snapshot:request:2026-07-15')

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert build_snapshot.call_count == 1


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
