from fnmatch import fnmatch
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
        self.token = uuid4().hex

    def acquire(self, blocking: bool = True) -> bool:
        """尝试获取锁。

        Args:
            blocking: 为兼容 Redis 锁保留；测试锁始终非阻塞。

        Returns:
            成功写入所有权令牌时返回 True。
        """
        del blocking
        return self.backend.add(self.key, self.token, timeout=self.timeout)

    def release(self) -> None:
        """仅当当前实例仍持有令牌时释放锁。

        Raises:
            LockNotOwnedError: 锁已过期或所有权已发生变化。
        """
        if self.backend.get(self.key) != self.token:
            raise LockNotOwnedError('测试锁所有权已失效')
        self.backend.delete(self.key)

    def owned(self) -> bool:
        """返回当前实例是否仍持有缓存锁。"""
        return self.backend.get(self.key) == self.token

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
        if not self.owned():
            raise LockNotOwnedError('测试锁所有权已失效')
        timeout = additional_time if replace_ttl else self.timeout + additional_time
        self.timeout = timeout
        return self.backend.touch(self.key, timeout=timeout)


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
