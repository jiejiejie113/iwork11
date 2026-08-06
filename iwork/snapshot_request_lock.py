"""历史快照后台请求的分布式所有权锁。"""

from threading import Event, Lock, Thread
from typing import Any, Self
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache

# ======
# Redis 请求锁续租脚本
_CAP_REQUEST_LOCK_TTL_SCRIPT = """
local current_token = redis.call('get', KEYS[1])
if not current_token or current_token ~= ARGV[1] then
    return 0
end
local current_ttl = redis.call('pttl', KEYS[1])
local target_ttl = tonumber(ARGV[2])
if current_ttl >= 0 and current_ttl < target_ttl then
    redis.call('pexpire', KEYS[1], target_ttl)
end
return 1
"""


def create_request_lock(target_date: str, timeout: int) -> Any:
    """创建指定日期的历史快照请求锁。

    Args:
        target_date (str): ISO 格式的目标日期。
        timeout (int): 锁的有效期秒数。

    Returns:
        Any: django-redis 或测试缓存提供的分布式锁对象。
    """
    return cache.lock(
        f'history:snapshot:request:{target_date}',
        timeout=timeout,
        blocking_timeout=0,
        thread_local=False,
    )


def acquire_request_lock(target_date: str, timeout: int) -> tuple[Any, str, bool]:
    """以唯一令牌非阻塞申请历史快照请求所有权。

    Args:
        target_date (str): ISO 格式的目标日期。
        timeout (int): 首次请求锁的有效期秒数。

    Returns:
        tuple[Any, str, bool]: 锁对象、所有权令牌和是否申请成功。
    """
    request_token = uuid4().hex
    request_lock = create_request_lock(target_date, timeout)
    acquired = request_lock.acquire(blocking=False, token=request_token)
    return request_lock, request_token, acquired


def restore_request_lock(target_date: str, request_token: str) -> Any:
    """在 Celery 任务中恢复由 Web 请求创建的锁所有权。

    Args:
        target_date (str): ISO 格式的目标日期。
        request_token (str): Web 请求生成并随任务传递的所有权令牌。

    Returns:
        Any: 已绑定令牌的分布式锁对象。
    """
    request_lock = create_request_lock(
        target_date,
        settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
    )
    if hasattr(request_lock, 'restore_token'):
        request_lock.restore_token(request_token)
    else:
        encoder = request_lock.redis.get_encoder()
        request_lock.local.token = encoder.encode(request_token)
    return request_lock


def renew_request_lock(request_lock: Any, timeout: int) -> bool:
    """确认所有权仍有效并把请求锁续租到指定时长。

    Args:
        request_lock (Any): 已持有或已恢复令牌的请求锁。
        timeout (int): 新的锁有效期秒数。

    Returns:
        bool: 当前令牌仍为所有者且续租成功时返回 True。
    """
    request_lock.timeout = timeout
    return bool(request_lock.reacquire())


def cap_request_lock_ttl(request_lock: Any, timeout: float) -> bool:
    """按所有权令牌把不足目标值的 TTL 原子补足，且不缩短长租约。

    Args:
        request_lock (Any): 当前持有令牌的请求锁。
        timeout (float): 需要维持的最小 TTL 秒数。

    Returns:
        bool: 当前令牌仍为所有者且检查或补足成功时返回 True。
    """
    if hasattr(request_lock, 'cap_ttl'):
        return bool(request_lock.cap_ttl(timeout))
    return bool(
        request_lock.redis.eval(
            _CAP_REQUEST_LOCK_TTL_SCRIPT,
            1,
            request_lock.name,
            request_lock.local.token,
            int(timeout * 1000),
        )
    )


class RequestLockLease:
    """在 Web 入队流程中持续维护短期请求锁租约。"""

    def __init__(
        self,
        request_lock: Any,
        timeout: int,
        renew_interval: float,
    ):
        """初始化请求锁续租器。

        Args:
            request_lock (Any): 当前 Web 请求持有的请求锁。
            timeout (int): 每次续租后的锁有效期秒数。
            renew_interval (float): 两次续租之间的等待秒数。
        """
        self.request_lock = request_lock
        self.timeout = timeout
        self.renew_interval = renew_interval
        self.stop_event = Event()
        self.lease_lost = Event()
        self.renewal_mutex = Lock()
        self.renewal_thread = Thread(
            target=self._renew_loop,
            name='history-snapshot-request-renewal',
            daemon=True,
        )

    @property
    def lost(self) -> bool:
        """返回续租期间是否已经失去请求锁所有权。"""
        return self.lease_lost.is_set()

    def start(self) -> Self:
        """先缩短为待确认租约，再启动后台续租并返回当前对象。"""
        try:
            if not renew_request_lock(self.request_lock, self.timeout):
                self.lease_lost.set()
                return self
        except Exception:
            self.lease_lost.set()
            return self
        self.renewal_thread.start()
        return self

    def stop(self) -> None:
        """停止续租，并在限定时间内等待正在执行的续租完成。"""
        self.stop_event.set()
        if self.renewal_thread.is_alive():
            self.renewal_thread.join(timeout=max(1.0, self.renew_interval * 2))
            if self.renewal_thread.is_alive():
                self.lease_lost.set()

    def _renew_loop(self) -> None:
        """定期续租请求锁，直到提交结束或所有权失效。"""
        while not self.stop_event.wait(self.renew_interval):
            with self.renewal_mutex:
                if self.stop_event.is_set():
                    return
                try:
                    if not cap_request_lock_ttl(
                        self.request_lock,
                        self.timeout,
                    ):
                        self.lease_lost.set()
                        return
                except Exception:
                    self.lease_lost.set()
                    return


def snapshot_build_in_progress(target_date: str) -> bool:
    """使用 Redis 锁原生语义检查真实历史快照构建锁。

    Args:
        target_date (str): ISO 格式的目标日期。

    Returns:
        bool: 真实构建锁存在时返回 True。
    """
    build_lock = cache.lock(
        f'history:snapshot:build:{target_date}',
        timeout=settings.HISTORY_SNAPSHOT_LOCK_TIMEOUT,
        blocking_timeout=0,
        thread_local=False,
    )
    return bool(build_lock.locked())
