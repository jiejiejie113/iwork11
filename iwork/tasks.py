from celery import shared_task
from concurrent.futures import TimeoutError as FutureTimeoutError
from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, connections
from loguru import logger
from redis.exceptions import LockError, LockNotOwnedError

from iwork.alerts.tasks import evaluate_published_snapshot_task
from iwork.history_store import SnapshotBuildInProgressError, snapshot_history_date
from iwork.read_model.builder import build_snapshot
from iwork.read_model.errors import SnapshotConsistencyError
from iwork.read_model.store import SnapshotStore
from iwork.sse_events import publish_snapshot_notification
from iwork.snapshot_request_lock import renew_request_lock, restore_request_lock
from iwork.statistics import get_business_date

# =====
# 可重试异常类型（瞬时性故障）
_RETRYABLE = (
    FutureTimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
    OperationalError,
    SnapshotConsistencyError,
)

# ======
# 实时快照采集配置
READ_MODEL_CACHE_PREFIX = settings.READ_MODEL_CACHE_PREFIX
READ_MODEL_REFRESH_LOCK_SECONDS = settings.READ_MODEL_REFRESH_LOCK_SECONDS


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否可重试（瞬时性故障可重试，数据/逻辑错误不可重试）"""
    return isinstance(exc, _RETRYABLE)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    task_time_limit=60,
    task_soft_time_limit=55,
)
def sync_dashboard_stats(self):
    """每 60 秒受控采集远程数据并原子发布完整实时快照。

    Returns:
        int: 发布的源记录数量；跳过发布时返回 ``0``。

    Raises:
        Exception: 快照构建遇到不可重试错误或重试仍失败时抛出。
    """
    business_date = get_business_date()
    lock_key = f'{READ_MODEL_CACHE_PREFIX}:{business_date.isoformat()}:refresh-lock'
    lock = cache.lock(
        lock_key,
        timeout=READ_MODEL_REFRESH_LOCK_SECONDS,
        blocking_timeout=0,
        thread_local=False,
    )
    if not lock.acquire(blocking=False):
        logger.info('实时快照 {} 已由其他任务采集，本轮跳过', business_date)
        return 0

    try:
        logger.info('开始构建完整实时快照: {}', business_date)
        snapshot = build_snapshot(business_date)
        if get_business_date() != business_date:
            logger.warning('实时快照构建期间已跨过曼谷午夜，放弃发布日期 {}', business_date)
            return 0

        version = SnapshotStore().publish(snapshot)
        try:
            subscriber_count = publish_snapshot_notification(business_date, version)
            logger.info(
                '实时快照通知已发布: date={} version={} subscribers={}',
                business_date,
                version,
                subscriber_count,
            )
        except Exception as notification_error:
            logger.warning(
                '实时快照已完成，但 SSE 版本通知发送失败，将由周期核对补偿: '
                'date={} version={} error={}',
                business_date,
                version,
                notification_error,
            )
        try:
            evaluate_published_snapshot_task.apply_async(
                args=[business_date.isoformat(), version],
                queue="alerts",
            )
        except Exception as alert_error:
            logger.warning(
                "实时快照已完成，但警报评估任务入队失败，将由补偿任务恢复: "
                "date={} version={} error={}",
                business_date,
                version,
                alert_error,
            )
        record_count = snapshot['metadata']['record_count']
        logger.success(
            '完整实时快照发布完成: date={} version={} source_records={}',
            business_date,
            version,
            record_count,
        )
        return record_count

    except Exception as e:
        if _is_retryable(e):
            logger.warning('批量构建任务遇到瞬时故障，将重试 (attempt {}): {}', self.request.retries + 1, e)
            raise self.retry(exc=e) from e
        logger.error('批量构建任务失败（不可重试）: {}', e)
        raise
    finally:
        connections['iwork'].close()
        try:
            lock.release()
        except LockNotOwnedError:
            logger.warning('实时快照采集锁已过期或所有权已变化: {}', business_date)
        except Exception as release_error:
            logger.warning('实时快照采集锁释放失败: {}', release_error)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    task_time_limit=300,
    task_soft_time_limit=270,
)
def snapshot_recent_history(self, days=3):
    """每天重建最近几个已结束的生产日期，覆盖迟到或修正数据。"""
    from datetime import timedelta

    completed = []
    try:
        business_today = get_business_date()
        for days_ago in range(1, days + 1):
            target_date = business_today - timedelta(days=days_ago)
            try:
                state = snapshot_history_date(target_date)
            except SnapshotBuildInProgressError:
                logger.info('历史快照 {} 已由其他入口构建，本轮跳过', target_date)
                continue
            completed.append({
                'date': target_date.isoformat(),
                'version': state.snapshot_version,
                'facts': state.fact_row_count,
            })
        return completed
    except Exception as exc:
        if _is_retryable(exc):
            raise self.retry(exc=exc) from exc
        logger.error('历史快照任务失败: {}', exc)
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    task_time_limit=1800,
    task_soft_time_limit=1740,
)
def build_history_snapshot(
    self,
    target_date_text: str,
    request_token: str | None = None,
):
    """异步构建单个历史日期快照。

    Args:
        target_date_text: ISO 格式的曼谷业务日期。
        request_token: Web 请求生成的分布式锁所有权令牌；旧任务缺少令牌时安全退出。

    Returns:
        发布成功的快照摘要。
    """
    from datetime import date

    target_date = date.fromisoformat(target_date_text)
    if not request_token:
        logger.warning('历史快照 {} 任务缺少请求所有权令牌，安全跳过', target_date)
        return {'date': target_date_text, 'status': 'superseded'}

    request_lock = restore_request_lock(target_date_text, request_token)
    keep_request_lock = False
    try:
        try:
            if not renew_request_lock(
                request_lock,
                settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
            ):
                logger.warning('历史快照 {} 请求所有权已失效', target_date)
                return {'date': target_date_text, 'status': 'superseded'}
        except LockError:
            logger.warning('历史快照 {} 请求已被新一代任务取代', target_date)
            return {'date': target_date_text, 'status': 'superseded'}

        state = snapshot_history_date(target_date)
        return {
            'date': target_date_text,
            'version': state.snapshot_version,
            'facts': state.fact_row_count,
        }
    except SnapshotBuildInProgressError:
        logger.info('历史快照 {} 已由其他任务构建，本任务结束', target_date)
        return {'date': target_date_text, 'status': 'building'}
    except Exception as exc:
        if _is_retryable(exc):
            if self.request.retries < self.max_retries:
                try:
                    keep_request_lock = renew_request_lock(
                        request_lock,
                        settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
                    )
                except Exception as renewal_error:
                    logger.warning(
                        '历史快照 {} 重试前无法续租请求锁: {}',
                        target_date,
                        renewal_error,
                    )
                if not keep_request_lock:
                    return {'date': target_date_text, 'status': 'superseded'}
            raise self.retry(exc=exc) from exc
        logger.error('历史快照 {} 异步构建失败: {}', target_date, exc)
        raise
    finally:
        connections['iwork'].close()
        if not keep_request_lock:
            try:
                request_lock.release()
            except LockError:
                logger.warning(
                    '历史快照 {} 请求锁已失效或已被取代',
                    target_date,
                )
            except Exception as cleanup_error:
                logger.warning(
                    '释放历史快照请求锁失败: date={} error={}',
                    target_date,
                    cleanup_error,
                )
