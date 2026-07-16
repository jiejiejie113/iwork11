from datetime import date, datetime

import pytest
from django.utils import timezone

from iwork.local_models import (
    HistoricalProductionFact,
    HistoricalStepSnapshot,
    HistoricalSyncState,
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

    response = client.get(
        '/api/dashboard/detail/flow/SO5-L5C/?date=2026-07-15'
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

    response = client.get('/api/history/date/2026-07-15/?mode=local')

    assert response.status_code == 200
    payload = response.json()
    assert payload['source'] == 'local'
    assert payload['total_qty'] == 183
    assert payload['workorder_count'] == 1
    assert payload['all_stepnos'] == [38]
    assert payload['hourly_stats'] == [{'hour': 10, 'qty': 183}]
