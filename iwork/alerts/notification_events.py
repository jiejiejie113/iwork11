"""站内通知SSE的进程内隔离与背压。"""

import asyncio
import json
import random
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from django.conf import settings
from django_redis import get_redis_connection
from loguru import logger
from redis import asyncio as redis_async


NOTIFICATION_CHANGED_EVENT = {"type": "notification_changed"}
NOTIFICATION_PROTOCOL_VERSION = 1
NOTIFICATION_CHANNEL = settings.ALERT_NOTIFICATION_CHANNEL


@dataclass(frozen=True)
class _Subscriber:
    """记录一个连接的可信身份与容量一队列。"""

    subject: str
    is_admin: bool
    queue: asyncio.Queue


class NotificationWakeupBroker:
    """只向匹配身份发送不含业务数据的最新通知唤醒。"""

    def __init__(self) -> None:
        """初始化当前ASGI进程的订阅者集合。"""
        self._subscribers: set[_Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener_task: asyncio.Task | None = None
        self._redis_enabled = "redis" in settings.CACHES["default"]["BACKEND"].lower()

    @asynccontextmanager
    async def subscribe(
        self,
        subject: str,
        *,
        is_admin: bool,
    ) -> AsyncIterator[asyncio.Queue]:
        """登记一个已经通过身份校验的SSE连接。

        Args:
            subject: Keycloak稳定账号标识。
            is_admin: 当前连接是否拥有管理员角色。

        Yields:
            asyncio.Queue: 容量为一的通知唤醒队列。
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._bind_running_loop()
        subscriber = _Subscriber(subject=subject, is_admin=is_admin, queue=queue)
        self._subscribers.add(subscriber)
        self._ensure_listener_started()
        try:
            yield queue
        finally:
            self._subscribers.discard(subscriber)
            if not self._subscribers and self._listener_task is not None:
                listener = self._listener_task
                self._listener_task = None
                listener.cancel()
                with suppress(asyncio.CancelledError):
                    await listener

    def broadcast(
        self,
        *,
        subjects: Collection[str] = (),
        include_admins: bool = False,
    ) -> None:
        """向匹配受众覆盖式写入一条通用唤醒。

        Args:
            subjects: 允许收到唤醒的Keycloak subject集合。
            include_admins: 是否同时唤醒当前管理员连接。
        """
        allowed_subjects = set(subjects)
        for subscriber in tuple(self._subscribers):
            if subscriber.subject not in allowed_subjects and not (
                include_admins and subscriber.is_admin
            ):
                continue
            if subscriber.queue.full():
                with suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
            with suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(dict(NOTIFICATION_CHANGED_EVENT))

    def _bind_running_loop(self) -> None:
        """把订阅器状态绑定到当前ASGI事件循环。"""
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
        self._loop = loop
        self._subscribers = set()
        self._listener_task = None

    def _ensure_listener_started(self) -> None:
        """在Redis环境为当前Worker启动至多一个频道监听器。"""
        if self._redis_enabled and (self._listener_task is None or self._listener_task.done()):
            self._listener_task = asyncio.create_task(self._listen_forever())

    async def _listen_forever(self) -> None:
        """监听跨容器唤醒并在Redis断线后自动重连。

        Raises:
            asyncio.CancelledError: 监听任务被取消时向上抛出。
        """
        retry_delay = 1.0
        while True:
            client = None
            pubsub = None
            try:
                client = redis_async.from_url(
                    settings.CACHES["default"]["LOCATION"],
                    decode_responses=True,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                )
                pubsub = client.pubsub()
                await pubsub.subscribe(NOTIFICATION_CHANNEL)
                retry_delay = 1.0
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    payload = _parse_wakeup(message.get("data"))
                    if payload is None:
                        logger.warning("忽略无效的站内通知唤醒")
                        continue
                    self.broadcast(
                        subjects=payload["subjects"],
                        include_admins=payload["include_admins"],
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("站内通知Redis订阅中断，将自动重连: {}", exc)
                await asyncio.sleep(retry_delay + random.uniform(0, retry_delay * 0.2))
                retry_delay = min(15.0, retry_delay * 2)
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.aclose()
                if client is not None:
                    with suppress(Exception):
                        await client.aclose()


def _parse_wakeup(message: object) -> dict[str, object] | None:
    """校验Redis内部通知唤醒负载。

    Args:
        message (object): Redis频道收到的原始消息体。

    Returns:
        dict[str, object] | None: 标准化唤醒负载；无效时返回 ``None``。
    """
    try:
        payload = json.loads(message) if isinstance(message, (str, bytes)) else message
        if not isinstance(payload, dict) or payload.get("protocol_version") != NOTIFICATION_PROTOCOL_VERSION:
            return None
        subjects = payload.get("subjects", [])
        include_admins = payload.get("include_admins", False)
        if not isinstance(subjects, list) or not all(isinstance(item, str) for item in subjects):
            return None
        if not isinstance(include_admins, bool):
            return None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return {"subjects": subjects, "include_admins": include_admins}


def publish_notification_wakeup(
    *,
    subjects: Collection[str] = (),
    include_admins: bool = False,
) -> int:
    """向所有Web Worker发布不含警报正文的身份定向唤醒。

    Args:
        subjects: 需要唤醒的具体subject。
        include_admins: 是否唤醒当前管理员连接。

    Returns:
        int: Redis报告的订阅者数量。
    """
    payload = {
        "protocol_version": NOTIFICATION_PROTOCOL_VERSION,
        "subjects": sorted(set(subjects)),
        "include_admins": include_admins,
    }
    connection = get_redis_connection("default")
    return int(connection.publish(NOTIFICATION_CHANNEL, json.dumps(payload, ensure_ascii=False)))


notification_wakeup_broker = NotificationWakeupBroker()
