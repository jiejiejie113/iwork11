"""实时读模型 Celery 采集任务测试。"""

from datetime import date
from unittest.mock import patch

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """隔离每项任务测试使用的分布式锁。"""
    cache.clear()
    yield
    cache.clear()


@patch("iwork.tasks.connections")
@patch("iwork.tasks.SnapshotStore")
@patch("iwork.tasks.build_snapshot")
def test_refresh_builds_and_publishes_one_complete_version(
    mock_build,
    mock_store_class,
    mock_connections,
):
    """一次刷新只构建并发布一个完整版本，随后关闭远程连接。"""
    from iwork.tasks import sync_dashboard_stats

    business_date = date(2026, 7, 31)
    snapshot = {
        "metadata": {
            "snapshot_version": "v1",
            "record_count": 123,
            "business_date": business_date.isoformat(),
        },
        "views": {"processes": [70, 69]},
    }
    mock_build.return_value = snapshot

    with patch("iwork.tasks.get_business_date", return_value=business_date):
        result = sync_dashboard_stats()

    mock_build.assert_called_once_with(business_date)
    mock_store_class.return_value.publish.assert_called_once_with(snapshot)
    mock_connections.__getitem__.assert_called_with("iwork")
    mock_connections.__getitem__.return_value.close.assert_called_once()
    assert result == 123


@patch("iwork.tasks.build_snapshot")
def test_refresh_lock_prevents_overlapping_remote_collection(mock_build):
    """已有采集任务时，新任务必须跳过且不能访问远程数据。"""
    from iwork.tasks import READ_MODEL_REFRESH_LOCK_SECONDS, sync_dashboard_stats

    business_date = date(2026, 7, 31)
    lock = cache.lock(
        f"iwork:read:v1:{business_date.isoformat()}:refresh-lock",
        timeout=READ_MODEL_REFRESH_LOCK_SECONDS,
        blocking_timeout=0,
        thread_local=False,
    )
    assert lock.acquire(blocking=False)
    try:
        with patch("iwork.tasks.get_business_date", return_value=business_date):
            assert sync_dashboard_stats() == 0
    finally:
        lock.release()

    mock_build.assert_not_called()


@patch("iwork.tasks.SnapshotStore")
@patch("iwork.tasks.build_snapshot")
def test_refresh_discards_snapshot_after_bangkok_midnight(mock_build, mock_store_class):
    """构建期间跨过曼谷午夜时不得发布昨日快照。"""
    from iwork.tasks import sync_dashboard_stats

    mock_build.return_value = {
        "metadata": {"snapshot_version": "old", "record_count": 1},
        "views": {},
    }
    with patch(
        "iwork.tasks.get_business_date",
        side_effect=[date(2026, 7, 31), date(2026, 8, 1)],
    ):
        assert sync_dashboard_stats() == 0

    mock_store_class.return_value.publish.assert_not_called()
