from dataclasses import dataclass
from datetime import date, datetime, time
from threading import Event, Thread

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import ExtractHour
from django.utils import timezone
from loguru import logger
from redis.exceptions import LockNotOwnedError

from iwork.local_models import (
    HistoricalProductionFact,
    HistoricalStepSnapshot,
    HistoricalSyncState,
    ProductionOrder,
)
from iwork.models import Pytckreg3
from iwork.queries import get_batch_step_metadata, get_date_range
from iwork.statistics import get_business_date


# ======
# 历史快照锁配置
HISTORY_SNAPSHOT_LOCK_TIMEOUT = settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT
HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL = settings.HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL


class SnapshotBuildInProgressError(RuntimeError):
    """同一日期的历史快照已经在构建。"""


class SnapshotBuildLeaseLostError(SnapshotBuildInProgressError):
    """历史快照构建任务已失去分布式锁所有权。"""


@dataclass(frozen=True)
class HistorySnapshotPayload:
    facts: list[dict]
    metadata: list[dict]
    source_row_count: int
    source_total_qty: int


class RemoteHistorySource:
    """从远程只读生产库构建一个日期的聚合快照载荷。"""

    def load(self, target_date: date) -> HistorySnapshotPayload:
        """从远程只读库构建指定日期的聚合载荷。

        Args:
            target_date: 已结束的曼谷业务日期。

        Returns:
            经过聚合的生产事实、工序元数据和源数据计数。
        """
        start, end = get_date_range(target_date)
        rows = list(
            Pytckreg3.objects.using('iwork')
            .filter(RegDate__gte=start, RegDate__lt=end)
            .annotate(event_hour=ExtractHour('RegTime'))
            .values(
                'event_hour', 'Flow', 'StationID', 'RegPerSysID',
                'WrkOrder', 'StepNo',
            )
            .annotate(qty=Sum('Qty'), source_record_count=Count('*'))
            .order_by()
        )
        facts = [
            {
                'event_hour': row['event_hour'] if row['event_hour'] is not None else -1,
                'flow': row['Flow'] or '',
                'station_id': row['StationID'] or '',
                'employee_id': row['RegPerSysID'] or 0,
                'wrk_order': row['WrkOrder'] or '',
                'step_no': row['StepNo'] or 0,
                'qty': row['qty'] or 0,
                'source_record_count': row['source_record_count'] or 0,
            }
            for row in rows
        ]
        metadata = self._load_metadata(facts)
        return HistorySnapshotPayload(
            facts=facts,
            metadata=metadata,
            source_row_count=sum(row['source_record_count'] for row in facts),
            source_total_qty=sum(row['qty'] for row in facts),
        )

    @staticmethod
    def _load_metadata(facts: list[dict]) -> list[dict]:
        """批量加载快照事实引用的工序与产品元数据。"""
        pairs = sorted({
            (row['wrk_order'], row['step_no'])
            for row in facts
            if row['wrk_order']
        })
        wrk_orders = sorted({wrk_order for wrk_order, _ in pairs})
        step_metadata = get_batch_step_metadata(wrk_orders) if wrk_orders else {}

        prefixes = {wrk_order[:6] for wrk_order in wrk_orders if len(wrk_order) >= 6}
        product_lookup = {}
        if prefixes:
            product_rows = (
                ProductionOrder.objects.using('iwork_local')
                .filter(style_no__in=prefixes)
                .values('style_no', 'product_name', 'order_no')
                .distinct()
            )
            for row in product_rows:
                product_lookup.setdefault(
                    row['style_no'],
                    (row['product_name'] or '', row['order_no'] or ''),
                )

        result = []
        for wrk_order, step_no in pairs:
            step = step_metadata.get((wrk_order, step_no), {})
            style_no = wrk_order[:6] if len(wrk_order) >= 6 else ''
            product_name, order_no = product_lookup.get(style_no, ('', ''))
            result.append({
                'wrk_order': wrk_order,
                'step_no': step_no,
                'description': step.get('description', ''),
                'step_time': step.get('step_time'),
                'style_no': style_no,
                'product_name': product_name,
                'order_no': order_no,
            })
        return result


def snapshot_history_date(target_date: date, source=None) -> HistoricalSyncState:
    """构建并原子发布一个已结束生产日期的本地历史快照。

    Args:
        target_date: 需要生成快照的曼谷业务日期。
        source: 可选的远程数据源适配器。

    Returns:
        发布成功后的历史同步状态。

    Raises:
        SnapshotBuildInProgressError: 同一日期已有其他构建任务。
        ValueError: 目标日期尚未结束或载荷校验失败。
    """
    lock_key = f'history:snapshot:build:{target_date.isoformat()}'
    lock = cache.lock(
        lock_key,
        timeout=HISTORY_SNAPSHOT_LOCK_TIMEOUT,
        blocking_timeout=0,
        thread_local=False,
    )
    if not lock.acquire(blocking=False):
        raise SnapshotBuildInProgressError(f'{target_date} 的历史快照正在构建')

    stop_renewal = Event()
    lease_lost = Event()
    renewal_thread = Thread(
        target=_renew_snapshot_lock,
        args=(lock, target_date, stop_renewal, lease_lost),
        name=f'history-snapshot-lock-{target_date.isoformat()}',
        daemon=True,
    )
    renewal_thread.start()

    def ensure_lock_owned() -> None:
        """确认当前任务仍持有同日期快照锁。"""
        if lease_lost.is_set() or not lock.owned():
            raise SnapshotBuildLeaseLostError(f'{target_date} 的历史快照构建锁已失效')

    try:
        return _snapshot_history_date_locked(
            target_date,
            source=source,
            ensure_lock_owned=ensure_lock_owned,
        )
    finally:
        stop_renewal.set()
        renewal_thread.join(timeout=5)
        try:
            lock.release()
        except LockNotOwnedError:
            logger.warning('历史快照 {} 的构建锁已过期或所有权已变化，不执行释放', target_date)


def _renew_snapshot_lock(lock, target_date: date, stop_event: Event, lease_lost: Event) -> None:
    """定期续租历史快照锁，防止长查询期间租约自然过期。

    Args:
        lock: django-redis 分布式锁实例。
        target_date: 当前构建的曼谷业务日期。
        stop_event: 主任务完成后用于停止续租线程的事件。
        lease_lost: 续租失败时通知主任务终止发布的事件。
    """
    while not stop_event.wait(HISTORY_SNAPSHOT_LOCK_RENEW_INTERVAL):
        try:
            if not lock.extend(HISTORY_SNAPSHOT_LOCK_TIMEOUT, replace_ttl=True):
                lease_lost.set()
                logger.error('历史快照 {} 的构建锁续租失败', target_date)
                return
        except Exception as exc:
            lease_lost.set()
            logger.error('历史快照 {} 的构建锁续租异常: {}', target_date, exc)
            return


def _snapshot_history_date_locked(
    target_date: date,
    source=None,
    ensure_lock_owned=None,
) -> HistoricalSyncState:
    """在持有单日期构建锁时生成并发布历史快照。

    Args:
        target_date: 需要生成快照的曼谷业务日期。
        source: 可选的远程数据源适配器。
        ensure_lock_owned: 发布前验证分布式锁所有权的回调。

    Returns:
        发布成功后的历史同步状态。
    """
    if target_date >= get_business_date():
        raise ValueError('只能持久化已经结束的历史日期')

    ensure_lock_owned = ensure_lock_owned or (lambda: None)
    ensure_lock_owned()
    source = source or RemoteHistorySource()
    existing = HistoricalSyncState.objects.using('iwork_local').filter(
        snapshot_date=target_date,
    ).first()
    previous_success = bool(
        existing and existing.status == HistoricalSyncState.Status.SUCCESS
    )
    version = (existing.snapshot_version + 1) if existing else 1
    if existing:
        state = existing
        if not previous_success:
            state.status = HistoricalSyncState.Status.RUNNING
            state.error_message = ''
            state.completed_at = None
            state.save(using='iwork_local')
    else:
        state = HistoricalSyncState.objects.using('iwork_local').create(
            snapshot_date=target_date,
            status=HistoricalSyncState.Status.RUNNING,
            snapshot_version=version,
        )

    try:
        payload = source.load(target_date)
        _validate_payload(payload)
        ensure_lock_owned()
        registered_date = timezone.make_aware(datetime.combine(target_date, time.min))
        fact_objects = []
        for row in payload.facts:
            event_hour = row['event_hour']
            registered_time = None
            if event_hour >= 0:
                registered_time = timezone.make_aware(
                    datetime.combine(target_date, time(hour=event_hour)),
                )
            fact_objects.append(HistoricalProductionFact(
                production_date=target_date,
                registered_date=registered_date,
                registered_time=registered_time,
                **row,
            ))
        metadata_objects = [
            HistoricalStepSnapshot(snapshot_date=target_date, **row)
            for row in payload.metadata
        ]

        with transaction.atomic(using='iwork_local'):
            state = HistoricalSyncState.objects.using('iwork_local').select_for_update().get(
                pk=state.pk,
            )
            ensure_lock_owned()
            version = (
                state.snapshot_version + 1
                if state.status == HistoricalSyncState.Status.SUCCESS
                else state.snapshot_version
            )
            HistoricalProductionFact.objects.using('iwork_local').filter(
                production_date=target_date,
            ).delete()
            HistoricalStepSnapshot.objects.using('iwork_local').filter(
                snapshot_date=target_date,
            ).delete()
            HistoricalProductionFact.objects.using('iwork_local').bulk_create(
                fact_objects,
                batch_size=2000,
            )
            HistoricalStepSnapshot.objects.using('iwork_local').bulk_create(
                metadata_objects,
                batch_size=2000,
            )
            ensure_lock_owned()
            state.status = HistoricalSyncState.Status.SUCCESS
            state.source_row_count = payload.source_row_count
            state.source_total_qty = payload.source_total_qty
            state.fact_row_count = len(fact_objects)
            state.metadata_row_count = len(metadata_objects)
            state.missing_metadata_count = sum(
                row.get('step_time') is None for row in payload.metadata
            )
            state.snapshot_version = version
            state.error_message = ''
            state.completed_at = timezone.now()
            state.save(using='iwork_local')
    except Exception as exc:
        failure_fields = {'error_message': str(exc)}
        if not previous_success:
            failure_fields.update({
                'status': HistoricalSyncState.Status.FAILED,
                'completed_at': timezone.now(),
            })
        HistoricalSyncState.objects.using('iwork_local').filter(pk=state.pk).update(
            **failure_fields,
        )
        logger.exception('历史快照 {} 发布失败', target_date)
        raise

    return state


def _validate_payload(payload: HistorySnapshotPayload) -> None:
    """校验聚合载荷与源数据记录数及总产量一致。"""
    fact_row_count = sum(row['source_record_count'] for row in payload.facts)
    fact_total_qty = sum(row['qty'] for row in payload.facts)
    if fact_row_count != payload.source_row_count:
        raise ValueError('历史快照源记录数校验失败')
    if fact_total_qty != payload.source_total_qty:
        raise ValueError('历史快照总产量校验失败')
