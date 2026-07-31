"""Celery 任务异常策略测试。"""

from datetime import date
from unittest.mock import patch

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """隔离每项任务测试使用的缓存锁。"""
    cache.clear()
    yield
    cache.clear()


def test_sync_dashboard_stats_propagates_non_retryable_build_error():
    """数据或逻辑错误不得被吞掉或发布半成品。"""
    from iwork.tasks import sync_dashboard_stats

    with patch("iwork.tasks.get_business_date", return_value=date(2026, 7, 31)), patch(
        "iwork.tasks.build_snapshot",
        side_effect=ValueError("快照字段不完整"),
    ), pytest.raises(ValueError, match="快照字段不完整"):
        sync_dashboard_stats()


def test_sync_dashboard_stats_closes_remote_connection_on_failure():
    """构建失败后仍必须释放远程数据库连接。"""
    from iwork.tasks import sync_dashboard_stats

    with patch("iwork.tasks.get_business_date", return_value=date(2026, 7, 31)), patch(
        "iwork.tasks.build_snapshot",
        side_effect=ValueError("失败"),
    ), patch("iwork.tasks.connections") as connections, pytest.raises(ValueError):
        sync_dashboard_stats()

    connections.__getitem__.return_value.close.assert_called_once()


def test_history_snapshot_final_retry_clears_request_marker():
    """历史构建耗尽重试后必须释放入队标记，允许用户重新发起任务。"""
    from django.db import OperationalError
    from iwork.tasks import build_history_snapshot

    request_key = 'history:snapshot:request:2026-07-15'
    cache.set(request_key, 'queued', 60)
    build_history_snapshot.push_request(retries=build_history_snapshot.max_retries)
    try:
        with patch(
            'iwork.tasks.snapshot_history_date',
            side_effect=OperationalError('模拟最终失败'),
        ), pytest.raises(OperationalError, match='模拟最终失败'):
            build_history_snapshot.run('2026-07-15')
    finally:
        build_history_snapshot.pop_request()

    assert cache.get(request_key) is None


def test_history_snapshot_intermediate_retry_keeps_request_marker():
    """尚有重试机会时应保留入队标记，避免等待期间重复提交。"""
    from celery.exceptions import Retry
    from django.db import OperationalError
    from iwork.tasks import build_history_snapshot

    request_key = 'history:snapshot:request:2026-07-15'
    cache.set(request_key, 'queued', 60)
    build_history_snapshot.push_request(retries=0)
    try:
        with patch(
            'iwork.tasks.snapshot_history_date',
            side_effect=OperationalError('模拟瞬时失败'),
        ), patch.object(
            build_history_snapshot,
            'retry',
            side_effect=Retry(),
        ), pytest.raises(Retry):
            build_history_snapshot.run('2026-07-15')
    finally:
        build_history_snapshot.pop_request()

    assert cache.get(request_key) == 'queued'
