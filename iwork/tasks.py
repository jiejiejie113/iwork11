from celery import shared_task
from concurrent.futures import TimeoutError as FutureTimeoutError
from loguru import logger

from iwork.statistics import get_batch_stats, cache_batch_to_redis, get_batch_detail_stats, cache_detail_batch_to_redis

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

        batch = get_batch_stats()
        cache_batch_to_redis(batch)

        # 并行构建生产详情数据
        detail_batch = get_batch_detail_stats()
        cache_detail_batch_to_redis(detail_batch)

        return len(batch)

    except Exception as e:
        if _is_retryable(e):
            logger.warning('批量构建任务遇到瞬时故障，将重试 (attempt {}): {}', self.request.retries + 1, e)
            raise self.retry(exc=e)
        else:
            logger.error('批量构建任务失败（不可重试）: {}', e)
            raise
