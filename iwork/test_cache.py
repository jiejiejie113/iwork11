from fnmatch import fnmatch
import pickle
import time
from types import SimpleNamespace
from uuid import uuid4

from django.core.cache.backends.locmem import LocMemCache
from redis.exceptions import LockNotOwnedError


class OwnedLocMemLock:
    """为测试提供带所有权令牌的非阻塞缓存锁。"""

    def __init__(self, backend, key: str, timeout: int):
        """初始化测试锁。

        Args:
            backend: Django 本地内存缓存后端。
            key: 锁使用的缓存键。
            timeout: 锁的存活秒数。
        """
        self.backend = backend
        self.key = key
        self.timeout = timeout
        self.local = SimpleNamespace(token=None)

    def acquire(self, blocking: bool = True, token: str | None = None) -> bool:
        """尝试获取锁。

        Args:
            blocking: 为兼容 Redis 锁保留；测试锁始终非阻塞。
            token: 可选的显式所有权令牌。

        Returns:
            成功写入所有权令牌时返回 True。
        """
        del blocking
        effective_token = token or uuid4().hex
        acquired = self.backend.add(
            self.key,
            effective_token,
            timeout=self.timeout,
        )
        if acquired:
            self.local.token = effective_token
        return acquired

    def release(self) -> None:
        """仅当当前实例仍持有令牌时释放锁。

        Raises:
            LockNotOwnedError: 锁已过期或所有权已发生变化。
        """
        with self.backend._lock:
            key = self.backend.make_and_validate_key(self.key)
            if not self._owned_unlocked(key):
                raise LockNotOwnedError('测试锁所有权已失效')
            self.backend._delete(key)
            self.local.token = None

    def _owned_unlocked(self, key: str) -> bool:
        """在已持有后端互斥锁时比较当前缓存令牌。"""
        if self.backend._has_expired(key):
            self.backend._delete(key)
            return False
        pickled_token = self.backend._cache.get(key)
        if pickled_token is None:
            return False
        return (
            self.local.token is not None
            and pickled_token
            == pickle.dumps(self.local.token, self.backend.pickle_protocol)
        )

    def owned(self) -> bool:
        """返回当前实例是否仍持有缓存锁。"""
        return (
            self.local.token is not None
            and self.backend.get(self.key) == self.local.token
        )

    def locked(self) -> bool:
        """返回当前缓存锁键是否由任意实例持有。"""
        return self.backend.get(self.key) is not None

    def restore_token(self, token: str) -> None:
        """为 Celery 测试任务恢复 Web 请求创建的所有权令牌。"""
        self.local.token = token

    def reacquire(self) -> bool:
        """按当前超时重新设置仍由本实例持有的锁租约。"""
        with self.backend._lock:
            key = self.backend.make_and_validate_key(self.key)
            if not self._owned_unlocked(key):
                raise LockNotOwnedError('测试锁所有权已失效')
            self.backend._expire_info[key] = self.backend.get_backend_timeout(
                self.timeout,
            )
            return True

    def cap_ttl(self, timeout: float) -> bool:
        """原子补足不足目标值的测试锁TTL，且不缩短更长租约。"""
        with self.backend._lock:
            key = self.backend.make_and_validate_key(self.key)
            if not self._owned_unlocked(key):
                raise LockNotOwnedError('测试锁所有权已失效')
            target_expiration = time.time() + timeout
            current_expiration = self.backend._expire_info.get(key)
            if (
                current_expiration is not None
                and current_expiration < target_expiration
            ):
                self.backend._expire_info[key] = target_expiration
            return True

    def extend(self, additional_time: int, replace_ttl: bool = False) -> bool:
        """延长当前测试锁的过期时间。

        Args:
            additional_time: 新增或替换的锁存活秒数。
            replace_ttl: 为 True 时直接替换剩余存活时间。

        Returns:
            成功延长锁时返回 True。

        Raises:
            LockNotOwnedError: 当前实例已失去锁所有权。
        """
        with self.backend._lock:
            key = self.backend.make_and_validate_key(self.key)
            if not self._owned_unlocked(key):
                raise LockNotOwnedError('测试锁所有权已失效')
            timeout = (
                additional_time
                if replace_ttl
                else None
            )
            if replace_ttl:
                self.backend._expire_info[key] = self.backend.get_backend_timeout(
                    timeout,
                )
            else:
                current_expiration = self.backend._expire_info.get(key)
                if current_expiration is None:
                    current_expiration = time.time()
                self.backend._expire_info[key] = (
                    current_expiration + additional_time
                )
            return True


class PatternLocMemCache(LocMemCache):
    """测试缓存适配器，提供 django-redis 兼容的 keys 接口。"""

    def keys(self, pattern: str) -> list[str]:
        """返回匹配模式的未版本化缓存键。"""
        versioned_pattern = self.make_key(pattern)
        versioned_prefix = self.make_key('')
        with self._lock:
            return [
                key.removeprefix(versioned_prefix)
                for key in self._cache
                if fnmatch(key, versioned_pattern)
            ]

    def lock(
        self,
        key: str,
        timeout: int,
        blocking_timeout: int = 0,
        thread_local: bool = True,
    ) -> OwnedLocMemLock:
        """创建与 django-redis 接口兼容的测试锁。

        Args:
            key: 锁使用的缓存键。
            timeout: 锁的存活秒数。
            blocking_timeout: 为接口兼容保留，测试锁不执行阻塞等待。
            thread_local: 为接口兼容保留，测试锁令牌存储在实例上。

        Returns:
            可执行非阻塞获取的测试锁对象。
        """
        del blocking_timeout
        del thread_local
        return OwnedLocMemLock(self, key, timeout)
