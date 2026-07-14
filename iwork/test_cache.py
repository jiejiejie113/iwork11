from fnmatch import fnmatch

from django.core.cache.backends.locmem import LocMemCache


class PatternLocMemCache(LocMemCache):
    """测试缓存适配器，提供 django-redis 兼容的 keys 接口。"""

    def keys(self, pattern: str) -> list[str]:
        versioned_pattern = self.make_key(pattern)
        versioned_prefix = self.make_key('')
        with self._lock:
            return [
                key.removeprefix(versioned_prefix)
                for key in self._cache
                if fnmatch(key, versioned_pattern)
            ]
