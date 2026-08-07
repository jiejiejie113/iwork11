"""SSE 事件通知与有界负载队列测试。"""

import asyncio
import json
from datetime import date
from unittest.mock import patch

import pytest

from iwork.sse_events import (
    SSE_PAYLOAD_BUILD_CONCURRENCY,
    SerializedSSEEvent,
    SharedSSEPayloadCache,
    SnapshotNotification,
    SnapshotNotificationBroker,
    publish_snapshot_notification,
)


def test_notification_rejects_missing_business_date_or_version():
    """通知字段为 null 时不得被字符串化后误当作合法版本。"""
    assert SnapshotNotification.from_message(
        '{"protocol_version": 1, "business_date": null, "snapshot_version": "v1"}'
    ) is None


def test_publisher_sends_only_lightweight_version_metadata():
    """发布器不得把业务快照负载写入 Pub/Sub 消息。"""
    with patch("iwork.sse_events.get_redis_connection") as get_connection:
        get_connection.return_value.publish.return_value = 4

        subscribers = publish_snapshot_notification(date(2026, 8, 7), "v-test")

    channel, raw_message = get_connection.return_value.publish.call_args.args
    payload = json.loads(raw_message)
    assert channel
    assert payload == {
        "protocol_version": 1,
        "business_date": "2026-08-07",
        "snapshot_version": "v-test",
    }
    assert subscribers == 4
    assert SnapshotNotification.from_message(
        '{"protocol_version": 1, "business_date": "2026-08-07", "snapshot_version": null}'
    ) is None


@pytest.mark.asyncio
async def test_slow_client_keeps_only_latest_snapshot_notification():
    """慢客户端队列积压时应丢弃旧版本并只保留最新版本。"""
    broker = SnapshotNotificationBroker()

    async with broker.subscribe() as queue:
        broker.broadcast(SnapshotNotification("2026-08-07", "v1"))
        broker.broadcast(SnapshotNotification("2026-08-07", "v2"))

        notification = queue.get_nowait()

    assert notification["snapshot_version"] == "v2"
    assert queue.empty()

    broker.broadcast(SnapshotNotification("2026-08-07", "v3"))
    assert queue.empty()


@pytest.mark.asyncio
async def test_concurrent_clients_share_one_payload_build():
    """同日期同工序的突发连接应共享一次读取和序列化。"""
    payload_cache = SharedSSEPayloadCache()
    build_count = 0

    async def loader():
        """构造可统计调用次数的测试负载。"""
        nonlocal build_count
        build_count += 1
        await asyncio.sleep(0.01)
        return SerializedSSEEvent("v1", "2026-08-07T12:00:00+07:00", "data: {}\n\n")

    events = await asyncio.gather(*(
        payload_cache.get(("2026-08-07", (70,)), loader)
        for _ in range(100)
    ))

    assert build_count == 1
    assert {id(event) for event in events} == {id(events[0])}


@pytest.mark.asyncio
async def test_periodic_check_recovers_notification_loss_with_one_shared_build():
    """Pub/Sub 消息丢失后，过期共享缓存应从 current 补回最新版本。"""
    payload_cache = SharedSSEPayloadCache()
    state = {"version": "v1"}
    build_count = 0

    async def loader():
        """按测试状态返回 current 版本事件。"""
        nonlocal build_count
        build_count += 1
        return SerializedSSEEvent(
            state["version"],
            "2026-08-07T12:00:00+07:00",
            "data: {}\n\n",
        )

    first = await payload_cache.get(("2026-08-07", (70,)), loader)
    state["version"] = "v2"
    recovered = await asyncio.gather(*(
        payload_cache.get(
            ("2026-08-07", (70,)),
            loader,
            max_age_seconds=-1,
        )
        for _ in range(50)
    ))

    assert first.snapshot_version == "v1"
    assert {event.snapshot_version for event in recovered} == {"v2"}
    assert build_count == 2


@pytest.mark.asyncio
async def test_distinct_payload_builds_enter_bounded_queue():
    """不同工序的负载构建超过并发上限时应等待有界信号量。"""
    payload_cache = SharedSSEPayloadCache()
    active_builds = 0
    maximum_active_builds = 0

    async def loader():
        """记录同时进入实际构建区的任务数。"""
        nonlocal active_builds, maximum_active_builds
        active_builds += 1
        maximum_active_builds = max(maximum_active_builds, active_builds)
        await asyncio.sleep(0.02)
        active_builds -= 1
        return SerializedSSEEvent("v1", "2026-08-07T12:00:00+07:00", "data: {}\n\n")

    await asyncio.gather(*(
        payload_cache.get(("2026-08-07", (stepno,)), loader)
        for stepno in range(10)
    ))

    assert maximum_active_builds == SSE_PAYLOAD_BUILD_CONCURRENCY


@pytest.mark.asyncio
async def test_stale_notification_is_compensated_once_and_then_reused():
    """通知落后于 current 时最多补读两次，重复通知不得继续放大读取。"""
    payload_cache = SharedSSEPayloadCache()
    build_count = 0

    async def loader():
        """模拟 current 已经前进到 v3。"""
        nonlocal build_count
        build_count += 1
        return SerializedSSEEvent("v3", "2026-08-07T12:02:00+07:00", "data: {}\n\n")

    first = await payload_cache.get(
        ("2026-08-07", (70,)),
        loader,
        notification_version="v2",
    )
    second = await payload_cache.get(
        ("2026-08-07", (70,)),
        loader,
        notification_version="v2",
    )

    assert first.snapshot_version == "v3"
    assert second.snapshot_version == "v3"
    assert build_count == 2
