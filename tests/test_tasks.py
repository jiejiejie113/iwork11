"""Celery 任务异常策略测试。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """隔离每项任务测试使用的缓存锁。"""
    cache.clear()
    yield
    cache.clear()


def _acquire_snapshot_request(target_date: str):
    """创建测试使用的带所有权令牌历史快照请求锁。"""
    from django.conf import settings

    token = uuid4().hex
    lock = cache.lock(
        f'history:snapshot:request:{target_date}',
        timeout=settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
        blocking_timeout=0,
        thread_local=False,
    )
    assert lock.acquire(blocking=False, token=token)
    return lock, token


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


def test_sync_dashboard_stats_retries_snapshot_consistency_error():
    """远程数据在分批查询间变化时应重试且不得发布不一致快照。"""
    from celery.exceptions import Retry
    from iwork.read_model.errors import SnapshotConsistencyError
    from iwork.tasks import sync_dashboard_stats

    sync_dashboard_stats.push_request(retries=0)
    try:
        with patch(
            "iwork.tasks.get_business_date",
            return_value=date(2026, 7, 31),
        ), patch(
            "iwork.tasks.build_snapshot",
            side_effect=SnapshotConsistencyError("实时汇总变化"),
        ), patch.object(
            sync_dashboard_stats,
            "retry",
            side_effect=Retry(),
        ) as retry, pytest.raises(Retry):
            sync_dashboard_stats.run()
    finally:
        sync_dashboard_stats.pop_request()

    retry.assert_called_once()
    assert isinstance(retry.call_args.kwargs["exc"], SnapshotConsistencyError)


def test_history_snapshot_final_retry_clears_request_marker():
    """历史构建耗尽重试后必须释放入队标记，允许用户重新发起任务。"""
    from django.db import OperationalError
    from iwork.tasks import build_history_snapshot

    request_lock, request_token = _acquire_snapshot_request('2026-07-15')
    build_history_snapshot.push_request(retries=build_history_snapshot.max_retries)
    try:
        with patch(
            'iwork.tasks.snapshot_history_date',
            side_effect=OperationalError('模拟最终失败'),
        ), pytest.raises(OperationalError, match='模拟最终失败'):
            build_history_snapshot.run('2026-07-15', request_token)
    finally:
        build_history_snapshot.pop_request()

    assert not request_lock.owned()


def test_history_snapshot_success_clears_request_markers():
    """历史快照发布成功后应清理排队标记和恢复凭证。"""
    from iwork.tasks import build_history_snapshot

    request_lock, request_token = _acquire_snapshot_request('2026-07-15')
    state = SimpleNamespace(snapshot_version=7, fact_row_count=42)

    with patch('iwork.tasks.snapshot_history_date', return_value=state):
        result = build_history_snapshot.run('2026-07-15', request_token)

    assert result == {'date': '2026-07-15', 'version': 7, 'facts': 42}
    assert not request_lock.owned()


def test_history_snapshot_intermediate_retry_keeps_request_marker():
    """尚有重试机会时应保留入队标记，避免等待期间重复提交。"""
    from celery.exceptions import Retry
    from django.db import OperationalError
    from iwork.tasks import build_history_snapshot

    request_lock, request_token = _acquire_snapshot_request('2026-07-15')
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
            build_history_snapshot.run('2026-07-15', request_token)
    finally:
        build_history_snapshot.pop_request()

    assert request_lock.owned()
    request_lock.release()


def test_history_snapshot_build_in_progress_keeps_request_marker():
    """同日期已有构建任务时应保留入队标记，阻止前端轮询重复提交。"""
    from iwork.history_store import SnapshotBuildInProgressError
    from iwork.tasks import build_history_snapshot

    request_lock, request_token = _acquire_snapshot_request('2026-07-15')

    with patch(
        'iwork.tasks.snapshot_history_date',
        side_effect=SnapshotBuildInProgressError('模拟同日期正在构建'),
    ):
        result = build_history_snapshot.run('2026-07-15', request_token)

    assert result == {'date': '2026-07-15', 'status': 'building'}
    assert not request_lock.owned()


def test_history_snapshot_stale_owner_does_not_delete_new_request():
    """旧任务失去令牌后不得执行构建或删除新一代请求锁。"""
    from iwork.tasks import build_history_snapshot

    old_lock, old_token = _acquire_snapshot_request('2026-07-15')
    old_lock.release()
    new_lock, _new_token = _acquire_snapshot_request('2026-07-15')

    with patch(
        'iwork.tasks.snapshot_history_date',
    ) as snapshot_history:
        result = build_history_snapshot.run('2026-07-15', old_token)

    assert result == {'date': '2026-07-15', 'status': 'superseded'}
    snapshot_history.assert_not_called()
    assert new_lock.owned()
    new_lock.release()


def test_history_snapshot_legacy_task_without_token_is_safely_skipped():
    """部署前已排队的旧参数任务不得绕过新所有权锁执行构建。"""
    from iwork.tasks import build_history_snapshot

    with patch('iwork.tasks.snapshot_history_date') as snapshot_history:
        result = build_history_snapshot.run('2026-07-15')

    assert result == {'date': '2026-07-15', 'status': 'superseded'}
    snapshot_history.assert_not_called()
