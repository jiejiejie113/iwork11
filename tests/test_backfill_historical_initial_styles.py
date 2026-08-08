"""历史初版款号回填命令测试。"""

from datetime import date, datetime
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from iwork.local_models import (
    HistoricalProductionFact,
    HistoricalStepSnapshot,
    HistoricalSyncState,
)


def create_history_rows(target_date: date) -> None:
    """创建一组可回填的历史元数据和不可变事实。

    Args:
        target_date: 测试快照日期。
    """
    registered_at = timezone.make_aware(datetime.combine(target_date, datetime.min.time()))
    HistoricalProductionFact.objects.using('iwork_local').create(
        production_date=target_date,
        event_hour=0,
        registered_date=registered_at,
        registered_time=registered_at,
        flow='SO3-L3A',
        station_id='L3A',
        employee_id=1001,
        wrk_order='BU1001',
        step_no=70,
        qty=20,
        source_record_count=1,
    )
    HistoricalStepSnapshot.objects.using('iwork_local').bulk_create([
        HistoricalStepSnapshot(
            snapshot_date=target_date,
            wrk_order='BU1001',
            step_no=70,
        ),
        HistoricalStepSnapshot(
            snapshot_date=target_date,
            wrk_order='BU1001',
            step_no=80,
        ),
        HistoricalStepSnapshot(
            snapshot_date=target_date,
            wrk_order='BU1002',
            step_no=70,
            initial_style_no='EXISTING',
        ),
    ])
    HistoricalSyncState.objects.using('iwork_local').create(
        snapshot_date=target_date,
        status=HistoricalSyncState.Status.SUCCESS,
        fact_row_count=1,
        metadata_row_count=3,
        snapshot_version=3,
    )


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_backfill_updates_only_empty_metadata_and_increments_version():
    """回填应更新空字段、保留已有值，并且不改写历史事实。"""
    target_date = date(2026, 7, 15)
    create_history_rows(target_date)
    original_fact = HistoricalProductionFact.objects.using('iwork_local').get()

    with patch(
        'iwork.management.commands.backfill_historical_initial_styles.'
        'get_initial_style_numbers',
        return_value={'BU1001': 'SAMPLE-01'},
    ):
        call_command('backfill_historical_initial_styles', batch_size=50)

    values = list(
        HistoricalStepSnapshot.objects.using('iwork_local')
        .order_by('wrk_order', 'step_no')
        .values_list('wrk_order', 'step_no', 'initial_style_no')
    )
    assert values == [
        ('BU1001', 70, 'SAMPLE-01'),
        ('BU1001', 80, 'SAMPLE-01'),
        ('BU1002', 70, 'EXISTING'),
    ]
    state = HistoricalSyncState.objects.using('iwork_local').get(
        snapshot_date=target_date,
    )
    assert state.snapshot_version == 4
    assert HistoricalProductionFact.objects.using('iwork_local').get().pk == original_fact.pk


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_backfill_is_idempotent_and_keeps_missing_mapping_empty():
    """无匹配数据时应保持空值，重复执行也不得递增版本。"""
    target_date = date(2026, 7, 15)
    create_history_rows(target_date)

    with patch(
        'iwork.management.commands.backfill_historical_initial_styles.'
        'get_initial_style_numbers',
        return_value={'BU1001': ''},
    ) as query:
        call_command('backfill_historical_initial_styles', batch_size=1)
        call_command('backfill_historical_initial_styles', batch_size=1)

    assert not HistoricalStepSnapshot.objects.using('iwork_local').filter(
        wrk_order='BU1001',
    ).exclude(initial_style_no='').exists()
    state = HistoricalSyncState.objects.using('iwork_local').get(
        snapshot_date=target_date,
    )
    assert state.snapshot_version == 3
    assert query.call_count == 2
