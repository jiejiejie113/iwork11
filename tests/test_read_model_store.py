"""版本化 Redis 读模型的行为测试。"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache

from iwork.read_model.errors import (
    ReadModelNotReadyError,
    SnapshotPublishInProgressError,
    SnapshotValidationError,
)
from iwork.read_model.store import SnapshotStore


BUSINESS_TIME_ZONE = ZoneInfo("Asia/Bangkok")
BUSINESS_DATE = date(2026, 7, 31)


def _snapshot_payload(generated_at: datetime, total_qty: int = 100) -> dict:
    """构造包含全部必要视图的测试快照。"""
    return {
        "metadata": {
            "schema_version": 1,
            "snapshot_version": generated_at.strftime("%Y%m%d-%H%M%S-%f"),
            "business_date": BUSINESS_DATE.isoformat(),
            "generated_at": generated_at.isoformat(),
            "source_completed_at": generated_at.isoformat(),
            "source_status": "success",
            "record_count": 0,
        },
        "views": {
            "realtime": {"all": {"date": BUSINESS_DATE, "total_qty": total_qty}},
            "processes": [70],
            "workorders": {"rows": [], "products": {}},
            "workorder_details": {},
            "detail": {
                "flow_overview": {},
                "flow_hourly": {},
                "flow_employees": {},
                "stepno_employees": {},
                "product_overview": {},
            },
            "kanban": [],
        },
    }


@pytest.fixture(autouse=True)
def clear_cache():
    """隔离每个读模型测试使用的缓存。"""
    cache.clear()
    yield
    cache.clear()


def test_publish_switches_current_only_after_complete_snapshot():
    """完整快照发布后，消费者才能看到新版本。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)

    first = _snapshot_payload(now - timedelta(seconds=30), total_qty=100)
    second = _snapshot_payload(now, total_qty=200)

    store.publish(first)
    store.publish(second)

    result = store.read("realtime", BUSINESS_DATE)
    assert result.data["all"]["total_qty"] == 200
    assert result.metadata["snapshot_version"] == second["metadata"]["snapshot_version"]
    assert result.stale is False
    assert store.previous_version(BUSINESS_DATE) == first["metadata"]["snapshot_version"]


def test_failed_publish_preserves_previous_snapshot(monkeypatch):
    """新版本写入中途失败时，current 指针必须保持旧版本。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    first = _snapshot_payload(now - timedelta(seconds=30), total_qty=100)
    second = _snapshot_payload(now, total_qty=200)
    store.publish(first)

    original_set = cache.set

    def fail_on_detail(key, value, timeout=None, version=None):
        if ":detail" in key:
            raise ConnectionError("模拟 Redis 写入失败")
        return original_set(key, value, timeout=timeout, version=version)

    monkeypatch.setattr(cache, "set", fail_on_detail)
    with pytest.raises(ConnectionError, match="模拟 Redis 写入失败"):
        store.publish(second)

    monkeypatch.setattr(cache, "set", original_set)
    result = store.read("realtime", BUSINESS_DATE)
    assert result.data["all"]["total_qty"] == 100
    assert result.metadata["snapshot_version"] == first["metadata"]["snapshot_version"]


def test_inconsistent_realtime_totals_preserve_previous_snapshot():
    """跨视图汇总不一致时拒绝发布并继续提供上一版本。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    first = _snapshot_payload(now - timedelta(seconds=30), total_qty=100)
    second = _snapshot_payload(now, total_qty=200)
    second["views"]["realtime"]["all"].update({
        "process_flow_stats": [{"step": 70, "flow": "A", "qty": 200}],
        "monthly_total_trend": [
            {"date": BUSINESS_DATE.isoformat(), "qty": 201},
        ],
    })
    store.publish(first)

    with pytest.raises(SnapshotValidationError, match="实时总量与当日月趋势不一致"):
        store.publish(second)

    result = store.read("realtime", BUSINESS_DATE)
    assert result.data["all"]["total_qty"] == 100
    assert result.metadata["snapshot_version"] == first["metadata"]["snapshot_version"]


@pytest.mark.parametrize(
    ("field_name", "rows", "message"),
    [
        (
            "process_flow_stats",
            [{"step": 70, "flow": "A", "qty": 199}],
            "实时总量与 Flow 汇总不一致",
        ),
        (
            "monthly_process_stats",
            [{"date": BUSINESS_DATE.isoformat(), "step": 70, "qty": 199}],
            "实时总量与当日工序月统计不一致",
        ),
    ],
)
def test_inconsistent_process_totals_are_rejected(field_name, rows, message):
    """Flow 或工序月统计与实时总量不一致时不得发布。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    snapshot = _snapshot_payload(now, total_qty=200)
    snapshot["views"]["realtime"][70] = {
        "date": BUSINESS_DATE,
        "total_qty": 200,
        "process_flow_stats": [{"step": 70, "flow": "A", "qty": 200}],
        "monthly_total_trend": [
            {"date": BUSINESS_DATE.isoformat(), "qty": 200},
        ],
        "monthly_process_stats": [
            {"date": BUSINESS_DATE.isoformat(), "step": 70, "qty": 200},
        ],
    }
    snapshot["views"]["realtime"][70][field_name] = rows

    with pytest.raises(SnapshotValidationError, match=message):
        store.publish(snapshot)

    with pytest.raises(ReadModelNotReadyError):
        store.read("realtime", BUSINESS_DATE)


def test_all_view_allows_filtered_monthly_process_semantics():
    """all 视图不直接比较存在工序过滤语义的月工序统计。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    snapshot = _snapshot_payload(now, total_qty=200)
    snapshot["views"]["realtime"]["all"].update({
        "process_flow_stats": [{"step": 70, "flow": "A", "qty": 200}],
        "monthly_total_trend": [
            {"date": BUSINESS_DATE.isoformat(), "qty": 200},
        ],
        "monthly_process_stats": [
            {"date": BUSINESS_DATE.isoformat(), "step": 70, "qty": 199},
        ],
    })

    store.publish(snapshot)

    assert store.read("realtime", BUSINESS_DATE).data["all"]["total_qty"] == 200


def test_stale_snapshot_is_served_until_hard_limit():
    """软阈值后标记陈旧，硬阈值后明确拒绝且不回源。"""
    generated_at = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    current_time = generated_at + timedelta(seconds=121)
    store = SnapshotStore(cache_backend=cache, now=lambda: current_time)
    store.publish(_snapshot_payload(generated_at))

    assert store.read("realtime", BUSINESS_DATE).stale is True

    store = SnapshotStore(
        cache_backend=cache,
        now=lambda: generated_at + timedelta(seconds=601),
    )
    with pytest.raises(ReadModelNotReadyError, match="超过允许的最大陈旧时间"):
        store.read("realtime", BUSINESS_DATE)


def test_business_dates_are_isolated():
    """不同曼谷业务日期不得读取到彼此的 current 指针。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    store.publish(_snapshot_payload(now))

    with pytest.raises(ReadModelNotReadyError, match="尚未准备好"):
        store.read("realtime", date(2026, 7, 30))


def test_redis_read_failure_becomes_not_ready_error(monkeypatch):
    """Redis 暂时不可用时返回统一不可用错误且不会回源数据库。"""
    store = SnapshotStore(cache_backend=cache, now=lambda: datetime.now(BUSINESS_TIME_ZONE))
    monkeypatch.setattr(cache, "get", lambda _key: (_ for _ in ()).throw(ConnectionError("down")))

    with pytest.raises(ReadModelNotReadyError, match="Redis 实时读模型暂不可用"):
        store.read("realtime", BUSINESS_DATE)


def test_competing_publish_cannot_switch_current_version():
    """同日期发布锁被占用时，第二个发布任务不得切换版本。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    first = _snapshot_payload(now - timedelta(seconds=1), total_qty=100)
    store.publish(first)
    lock = cache.lock(
        "iwork:read:v1:2026-07-31:publish-lock",
        timeout=60,
        blocking_timeout=0,
        thread_local=False,
    )
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(SnapshotPublishInProgressError):
            store.publish(_snapshot_payload(now, total_qty=200))
    finally:
        lock.release()

    assert store.read("realtime", BUSINESS_DATE).data["all"]["total_qty"] == 100


def test_incompatible_schema_is_rejected_before_writing():
    """结构版本不兼容时不得写入任何 current 指针。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    snapshot = _snapshot_payload(now)
    snapshot["metadata"]["schema_version"] = 999

    with pytest.raises(SnapshotValidationError, match="结构版本不兼容"):
        store.publish(snapshot)
    with pytest.raises(ReadModelNotReadyError):
        store.read("realtime", BUSINESS_DATE)


def test_read_rejects_incompatible_published_schema():
    """读取时也必须拒绝被外部篡改或由旧程序留下的不兼容结构。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    snapshot = _snapshot_payload(now)
    store.publish(snapshot)

    version = snapshot["metadata"]["snapshot_version"]
    metadata_key = store._metadata_key(BUSINESS_DATE, version)
    metadata = cache.get(metadata_key)
    metadata["schema_version"] = 999
    cache.set(metadata_key, metadata)

    with pytest.raises(ReadModelNotReadyError, match="结构版本不兼容"):
        store.read("realtime", BUSINESS_DATE)


def test_cleanup_failure_after_switch_keeps_new_current_readable(monkeypatch):
    """current 切换后清理旧版本失败不得回删已经生效的新版本。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    store.publish(_snapshot_payload(now - timedelta(seconds=20), total_qty=100))
    store.publish(_snapshot_payload(now - timedelta(seconds=10), total_qty=200))

    monkeypatch.setattr(
        store,
        "_delete_version",
        lambda *_args: (_ for _ in ()).throw(ConnectionError("模拟旧版本清理失败")),
    )
    store.publish(_snapshot_payload(now, total_qty=300))

    assert store.read("realtime", BUSINESS_DATE).data["all"]["total_qty"] == 300


@pytest.mark.parametrize(
    ('mutate', 'message'),
    [
        (
            lambda snapshot: snapshot['views']['workorders'].pop('rows'),
            '工单视图结构无效',
        ),
        (
            lambda snapshot: snapshot['metadata'].__setitem__('record_count', 1),
            '记录数不一致',
        ),
        (
            lambda snapshot: snapshot['views']['detail'].pop('product_overview'),
            '生产详情视图不完整',
        ),
        (
            lambda snapshot: snapshot['views']['realtime']['all'].__setitem__(
                'date',
                date(2026, 7, 30),
            ),
            '业务日期不一致',
        ),
    ],
)
def test_publish_rejects_incomplete_nested_snapshot(mutate, message):
    """嵌套结构、事实记录数或业务日期不一致时不得发布。"""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=BUSINESS_TIME_ZONE)
    store = SnapshotStore(cache_backend=cache, now=lambda: now)
    snapshot = _snapshot_payload(now)
    mutate(snapshot)

    with pytest.raises(SnapshotValidationError, match=message):
        store.publish(snapshot)
