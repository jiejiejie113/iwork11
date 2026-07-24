from celery import shared_task
from concurrent.futures import TimeoutError as FutureTimeoutError
from loguru import logger

from iwork.statistics import get_batch_stats, cache_batch_to_redis, get_batch_detail_stats, cache_detail_batch_to_redis
from iwork.history_store import SnapshotBuildInProgressError, snapshot_history_date
from iwork.statistics import get_business_date

# =====
# 可重试异常类型（瞬时性故障）
_RETRYABLE = (
    FutureTimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否可重试（瞬时性故障可重试，数据/逻辑错误不可重试）"""
    return isinstance(exc, _RETRYABLE)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    task_time_limit=120,
    task_soft_time_limit=90,
)
def sync_dashboard_stats(self):
    """每 60s：批量构建所有工序数据 → 写入 Redis"""
    try:
        logger.info('开始批量构建看板统计数据')
        business_date = get_business_date()

        batch = get_batch_stats(target_date=business_date)
        detail_batch = get_batch_detail_stats(target_date=business_date)
        if get_business_date() != business_date:
            logger.warning('看板构建期间已跨过曼谷午夜，放弃写入日期 {} 的旧数据', business_date)
            return 0

        cache_batch_to_redis(batch, target_date=business_date)
        cache_detail_batch_to_redis(detail_batch, target_date=business_date)

        return len(batch)

    except Exception as e:
        if _is_retryable(e):
            logger.warning('批量构建任务遇到瞬时故障，将重试 (attempt {}): {}', self.request.retries + 1, e)
            raise self.retry(exc=e) from e
        else:
            logger.error('批量构建任务失败（不可重试）: {}', e)
            raise


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
