from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from iwork.local_models import (
    HistoricalProductionFact,
    HistoricalStepSnapshot,
    HistoricalSyncState,
    TargetProduction,
)
from iwork.history_store import HistorySnapshotPayload, snapshot_history_date


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_historical_flow_detail_uses_local_snapshot_by_default(client):
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


@pytest.mark.django_db(databases=['iwork_local'])
def test_snapshot_history_date_publishes_validated_snapshot():
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


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_missing_history_snapshot_can_be_built_then_read(client):
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

    assert build_response.status_code == 201
    build_payload = build_response.json()
    assert build_payload['created'] is True
    assert build_payload['snapshot']['date'] == '2026-07-15'
    assert build_payload['snapshot']['version'] == 1
    assert build_payload['snapshot']['source_row_count'] == 3

    detail_response = client.get(
        '/api/dashboard/detail/flow/SO5-L5C/?date=2026-07-15'
    )
    assert detail_response.status_code == 200
    assert detail_response.json()['source'] == 'local_snapshot'


@patch('iwork.api_views_local.cache')
@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_reports_build_in_progress(
    _mock_business_date,
    _mock_snapshot_state,
    mock_cache,
    client,
):
    mock_cache.add.return_value = False

    with patch('iwork.api_views_local.snapshot_history_date') as build_snapshot:
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 202
    assert response.json() == {
        'created': False,
        'code': 'history_snapshot_building',
        'message': '本地历史快照正在构建',
        'retry_after': 2,
    }
    build_snapshot.assert_not_called()


@patch('iwork.api_views_local.cache')
@patch('iwork.api_views_local._snapshot_state', return_value=None)
@patch('iwork.api_views_local.get_business_date', return_value=date(2026, 7, 16))
def test_ensure_snapshot_releases_build_lock(
    _mock_business_date,
    _mock_snapshot_state,
    mock_cache,
    client,
):
    mock_cache.add.return_value = True
    state = SimpleNamespace(
        snapshot_date=date(2026, 7, 15),
        snapshot_version=1,
        source_row_count=10,
        source_total_qty=20,
        fact_row_count=3,
        metadata_row_count=2,
        missing_metadata_count=0,
        completed_at=None,
    )

    with patch('iwork.api_views_local.snapshot_history_date', return_value=state):
        response = client.post('/api/history/snapshots/2026-07-15/ensure/')

    assert response.status_code == 201
    mock_cache.delete.assert_called_once_with('history:snapshot:build:2026-07-15')

@pytest.mark.django_db(databases=['default', 'iwork_local'], transaction=True)
def test_history_dashboard_stats_read_from_persisted_facts(client):
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
    response = client.get(url)

    assert response.status_code == 404
    assert response.json()['code'] == 'history_snapshot_not_found'
