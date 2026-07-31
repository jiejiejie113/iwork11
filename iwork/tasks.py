from celery import shared_task
from concurrent.futures import TimeoutError as FutureTimeoutError
from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, connections
from loguru import logger
from redis.exceptions import LockNotOwnedError

from iwork.history_store import SnapshotBuildInProgressError, snapshot_history_date
from iwork.read_model.builder import build_snapshot
from iwork.read_model.store import SnapshotStore
from iwork.statistics import get_business_date

# =====
# 可重试异常类型（瞬时性故障）
_RETRYABLE = (
    FutureTimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
    OperationalError,
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
    """每 60 秒受控采集远程数据并原子发布完整实时快照。"""
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
def build_history_snapshot(self, target_date_text: str):
    """异步构建单个历史日期快照。

    Args:
        target_date_text: ISO 格式的曼谷业务日期。

    Returns:
        发布成功的快照摘要。
    """
    from datetime import date

    target_date = date.fromisoformat(target_date_text)
    request_key = f'history:snapshot:request:{target_date_text}'
    keep_request_marker = False
    try:
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
            keep_request_marker = self.request.retries < self.max_retries
            raise self.retry(exc=exc) from exc
        logger.error('历史快照 {} 异步构建失败: {}', target_date, exc)
        raise
    finally:
        connections['iwork'].close()
        if not keep_request_marker:
            try:
                cache.delete(request_key)
            except Exception as cleanup_error:
                logger.warning(
                    '清理历史快照请求标记失败: date={} error={}',
                    target_date,
                    cleanup_error,
                )
