"""SSE 快照通知、最新事件队列和共享负载构建。"""

import asyncio
import json
import random
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django_redis import get_redis_connection
from loguru import logger
from redis import asyncio as redis_async


# ======
# SSE 通知与背压配置
SSE_NOTIFICATION_PROTOCOL_VERSION = 1
SSE_NOTIFICATION_CHANNEL = settings.SSE_NOTIFICATION_CHANNEL
SSE_CLIENT_QUEUE_SIZE = settings.SSE_CLIENT_QUEUE_SIZE
SSE_PAYLOAD_CACHE_SIZE = settings.SSE_PAYLOAD_CACHE_SIZE
SSE_PAYLOAD_BUILD_CONCURRENCY = settings.SSE_PAYLOAD_BUILD_CONCURRENCY
SSE_NOTIFICATION_RETRY_MIN_SECONDS = settings.SSE_NOTIFICATION_RETRY_MIN_SECONDS
SSE_NOTIFICATION_RETRY_MAX_SECONDS = settings.SSE_NOTIFICATION_RETRY_MAX_SECONDS
SSE_NOTIFICATION_POLL_SECONDS = settings.SSE_NOTIFICATION_POLL_SECONDS


@dataclass(frozen=True)
class SerializedSSEEvent:
    """可供多个 SSE 客户端复用的已序列化事件。"""

    snapshot_version: str
    generated_at: str
    content: str


@dataclass(frozen=True)
class SnapshotNotification:
    """Redis Pub/Sub 中传递的轻量快照版本通知。"""

    business_date: str
    snapshot_version: str
    protocol_version: int = SSE_NOTIFICATION_PROTOCOL_VERSION

    def as_dict(self) -> dict:
        """转换为 JSON 可序列化字典。

        Returns:
            dict: 版本通知字段。
        """
        return {
            "protocol_version": self.protocol_version,
            "business_date": self.business_date,
            "snapshot_version": self.snapshot_version,
        }

    @classmethod
    def from_message(cls, message: object) -> "SnapshotNotification | None":
        """校验并解析 Redis 消息。

        Args:
            message: Redis 返回的消息正文。

        Returns:
            SnapshotNotification | None: 合法通知；无效消息返回 None。
        """
        try:
            payload = json.loads(message) if isinstance(message, (str, bytes)) else message
            if not isinstance(payload, dict):
                return None
            business_date_value = payload["business_date"]
            snapshot_version_value = payload["snapshot_version"]
            if (
                not isinstance(business_date_value, str)
                or not business_date_value
                or not isinstance(snapshot_version_value, str)
                or not snapshot_version_value
            ):
                return None
            date.fromisoformat(business_date_value)
            notification = cls(
                protocol_version=int(payload["protocol_version"]),
                business_date=business_date_value,
                snapshot_version=snapshot_version_value,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            notification.protocol_version != SSE_NOTIFICATION_PROTOCOL_VERSION
            or not notification.business_date
            or not notification.snapshot_version
        ):
            return None
        return notification


def publish_snapshot_notification(business_date: date, snapshot_version: str) -> int:
    """向 Redis 发布已完成快照的版本通知。

    Args:
        business_date: 已完成发布的业务日期。
        snapshot_version: 已切换为 current 的快照版本。

    Returns:
        int: 收到通知的 Redis 订阅者数量。
    """
    notification = SnapshotNotification(
        business_date=business_date.isoformat(),
        snapshot_version=snapshot_version,
    )
    connection = get_redis_connection("default")
    return int(connection.publish(
        SSE_NOTIFICATION_CHANNEL,
        json.dumps(notification.as_dict(), ensure_ascii=False),
    ))


class SnapshotNotificationBroker:
    """每个 Web Worker 共享一个 Redis 订阅并广播到最新事件队列。"""

    def __init__(self) -> None:
        """初始化延迟绑定到事件循环的订阅状态。"""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._listener_task: asyncio.Task | None = None
        self._redis_enabled = "redis" in settings.CACHES["default"]["BACKEND"].lower()

    def _bind_running_loop(self) -> None:
        """确保运行状态只属于当前 ASGI 事件循环。"""
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
        self._loop = loop
        self._subscribers = set()
        self._listener_task = None

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        """为单个 SSE 连接注册容量为 1 的最新通知队列。

        Yields:
            asyncio.Queue: 只保留最新版本通知的客户端队列。
        """
        self._bind_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=SSE_CLIENT_QUEUE_SIZE)
        self._subscribers.add(queue)
        self._ensure_listener_started()
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def broadcast(self, notification: SnapshotNotification | dict) -> None:
        """向所有本 Worker 客户端投递最新通知并覆盖积压旧通知。

        Args:
            notification: 已校验通知或等价字典。
        """
        payload = (
            notification.as_dict()
            if isinstance(notification, SnapshotNotification)
            else notification
        )
        for queue in tuple(self._subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("SSE 最新通知队列仍然繁忙，本轮通知跳过")

    def _ensure_listener_started(self) -> None:
        """保证当前 Worker 最多运行一个 Redis 订阅任务。"""
        if not self._redis_enabled:
            return
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._listen_forever())

    async def _listen_forever(self) -> None:
        """订阅 Redis 通知并在断线后按指数退避自动恢复。"""
        retry_delay = SSE_NOTIFICATION_RETRY_MIN_SECONDS
        redis_location = settings.CACHES["default"]["LOCATION"]
        while True:
            client = None
            pubsub = None
            try:
                client = redis_async.from_url(
                    redis_location,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                )
                pubsub = client.pubsub()
                await pubsub.subscribe(SSE_NOTIFICATION_CHANNEL)
                retry_delay = SSE_NOTIFICATION_RETRY_MIN_SECONDS
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    notification = SnapshotNotification.from_message(message.get("data"))
                    if notification is None:
                        logger.warning("忽略无效的 SSE 快照通知")
                        continue
                    self.broadcast(notification)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("SSE Redis 通知订阅中断，将自动重连: {}", exc)
                jitter = random.uniform(0, retry_delay * 0.2)
                await asyncio.sleep(retry_delay + jitter)
                retry_delay = min(
                    SSE_NOTIFICATION_RETRY_MAX_SECONDS,
                    retry_delay * 2,
                )
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.aclose()
                if client is not None:
                    with suppress(Exception):
                        await client.aclose()


class SharedSSEPayloadCache:
    """按日期和工序单飞构建负载，并限制不同负载的并行构建数。"""

    def __init__(self) -> None:
        """初始化延迟绑定到事件循环的缓存状态。"""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._cache: OrderedDict[tuple, tuple[SerializedSSEEvent, float]] = OrderedDict()
        self._build_tasks: dict[tuple, asyncio.Task] = {}
        self._handled_notifications: dict[tuple, str] = {}

    def _bind_running_loop(self) -> None:
        """为当前事件循环建立独立的锁、信号量和单飞任务表。"""
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        for task in self._build_tasks.values():
            if not task.done():
                task.cancel()
        self._loop = loop
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(SSE_PAYLOAD_BUILD_CONCURRENCY)
        self._cache.clear()
        self._build_tasks.clear()
        self._handled_notifications.clear()

    async def get(
        self,
        key: tuple,
        loader: Callable[[], Awaitable[SerializedSSEEvent]],
        *,
        notification_version: str | None = None,
        max_age_seconds: float = SSE_NOTIFICATION_POLL_SECONDS,
    ) -> SerializedSSEEvent:
        """读取共享事件，必要时进入有界单飞构建队列。

        Args:
            key: 业务日期和工序组成的稳定缓存键。
            loader: 异步读取并序列化当前快照的函数。
            notification_version: 触发本次读取的通知版本。
            max_age_seconds: 无通知时允许复用缓存的最长秒数。

        Returns:
            SerializedSSEEvent: 当前可发送的共享事件。
        """
        self._bind_running_loop()
        attempts = 0
        while True:
            attempts += 1
            event = await self._get_once(
                key,
                loader,
                notification_version=notification_version,
                max_age_seconds=max_age_seconds,
            )
            if (
                notification_version is None
                or event.snapshot_version == notification_version
                or attempts >= 2
            ):
                if notification_version is not None and attempts >= 2:
                    assert self._lock is not None
                    async with self._lock:
                        self._handled_notifications[key] = notification_version
                return event

    async def _get_once(
        self,
        key: tuple,
        loader: Callable[[], Awaitable[SerializedSSEEvent]],
        *,
        notification_version: str | None,
        max_age_seconds: float,
    ) -> SerializedSSEEvent:
        """执行一次缓存命中或单飞构建。

        Args:
            key: 业务日期和工序组成的稳定缓存键。
            loader: 异步负载构建函数。
            notification_version: 触发本次读取的通知版本。
            max_age_seconds: 无通知时允许复用缓存的最长秒数。

        Returns:
            SerializedSSEEvent: 当前可发送的共享事件。
        """
        assert self._lock is not None
        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                event, cached_at = cached
                notification_handled = (
                    notification_version is not None
                    and self._handled_notifications.get(key) == notification_version
                )
                cache_fresh = time.monotonic() - cached_at <= max_age_seconds
                if notification_handled or (
                    notification_version is None and cache_fresh
                ):
                    self._cache.move_to_end(key)
                    return event
                if (
                    notification_version is not None
                    and event.snapshot_version == notification_version
                ):
                    self._handled_notifications[key] = notification_version
                    self._cache.move_to_end(key)
                    return event

            task = self._build_tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._build(loader))
                self._build_tasks[key] = task

        try:
            event = await asyncio.shield(task)
        finally:
            async with self._lock:
                if self._build_tasks.get(key) is task and task.done():
                    self._build_tasks.pop(key, None)

        async with self._lock:
            self._cache[key] = (event, time.monotonic())
            self._cache.move_to_end(key)
            while len(self._cache) > SSE_PAYLOAD_CACHE_SIZE:
                removed_key, _ = self._cache.popitem(last=False)
                self._handled_notifications.pop(removed_key, None)
            if (
                notification_version is not None
                and event.snapshot_version == notification_version
            ):
                self._handled_notifications[key] = notification_version
        return event

    async def _build(
        self,
        loader: Callable[[], Awaitable[SerializedSSEEvent]],
    ) -> SerializedSSEEvent:
        """在全 Worker 有界信号量内构建一次负载。

        Args:
            loader: 异步负载构建函数。

        Returns:
            SerializedSSEEvent: 新构建的共享事件。
        """
        assert self._semaphore is not None
        async with self._semaphore:
            return await loader()


_SNAPSHOT_NOTIFICATION_BROKER = SnapshotNotificationBroker()
_SSE_PAYLOAD_CACHE = SharedSSEPayloadCache()


def get_snapshot_notification_broker() -> SnapshotNotificationBroker:
    """返回当前进程共享的快照通知代理。

    Returns:
        SnapshotNotificationBroker: Worker 级单例。
    """
    return _SNAPSHOT_NOTIFICATION_BROKER


def get_sse_payload_cache() -> SharedSSEPayloadCache:
    """返回当前进程共享的 SSE 负载缓存。

    Returns:
        SharedSSEPayloadCache: Worker 级单例。
    """
    return _SSE_PAYLOAD_CACHE
