"""版本化 Redis 快照的发布与读取。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from loguru import logger
from redis.exceptions import LockNotOwnedError

from .errors import (
    ReadModelNotReadyError,
    SnapshotPublishInProgressError,
    SnapshotValidationError,
)
from .schemas import (
    READ_MODEL_SCHEMA_VERSION,
    REQUIRED_VIEW_NAMES,
    validate_snapshot,
)


# ======
# 读模型配置引用
READ_MODEL_CACHE_PREFIX = settings.READ_MODEL_CACHE_PREFIX
READ_MODEL_RETENTION_SECONDS = settings.READ_MODEL_RETENTION_SECONDS
READ_MODEL_STALE_AFTER_SECONDS = settings.READ_MODEL_STALE_AFTER_SECONDS
READ_MODEL_MAX_STALE_SECONDS = settings.READ_MODEL_MAX_STALE_SECONDS
READ_MODEL_PUBLISH_LOCK_SECONDS = settings.READ_MODEL_PUBLISH_LOCK_SECONDS
BUSINESS_TIME_ZONE = ZoneInfo(settings.IWORK_BUSINESS_TIME_ZONE)


@dataclass(frozen=True)
class SnapshotReadResult:
    """单个快照视图的读取结果。"""

    data: object
    metadata: dict
    stale: bool


class SnapshotStore:
    """隐藏 Redis 键、版本指针、完整性检查和陈旧策略。"""

    def __init__(
        self,
        cache_backend=None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化快照存储。

        Args:
            cache_backend: Django Cache 兼容后端；默认使用全局 Redis Cache。
            now: 返回当前时间的函数；用于测试陈旧边界。
        """
        self.cache = cache_backend or cache
        self.now = now or (lambda: datetime.now(BUSINESS_TIME_ZONE))

    def publish(self, snapshot: dict) -> str:
        """完整写入新版本后原子切换 current 指针。

        Args:
            snapshot: 经构建器生成的完整快照。

        Returns:
            发布成功的快照版本。

        Raises:
            SnapshotPublishInProgressError: 同日期已有发布任务。
            SnapshotValidationError: 快照不完整或元数据无效。
            Exception: 缓存写入失败。
        """
        metadata, views = validate_snapshot(snapshot)
        business_date = date.fromisoformat(metadata["business_date"])
        version = metadata["snapshot_version"]
        lock = self.cache.lock(
            self._lock_key(business_date),
            timeout=READ_MODEL_PUBLISH_LOCK_SECONDS,
            blocking_timeout=0,
            thread_local=False,
        )
        if not lock.acquire(blocking=False):
            raise SnapshotPublishInProgressError(f"{business_date} 的实时快照正在发布")

        written_keys: list[str] = []
        try:
            old_current = self.cache.get(self._current_key(business_date))
            if old_current == version:
                raise SnapshotValidationError(
                    f"快照版本 {version} 已经发布，禁止覆盖当前版本"
                )
            metadata_key = self._metadata_key(business_date, version)
            self.cache.set(metadata_key, metadata, READ_MODEL_RETENTION_SECONDS)
            written_keys.append(metadata_key)
            for view_name in sorted(REQUIRED_VIEW_NAMES):
                view_key = self._view_key(business_date, version, view_name)
                self.cache.set(
                    view_key,
                    views[view_name],
                    READ_MODEL_RETENTION_SECONDS,
                )
                written_keys.append(view_key)

            self._verify_written_snapshot(business_date, version)
            current_key = self._current_key(business_date)
            previous_key = self._previous_key(business_date)
            old_previous = self.cache.get(previous_key)
            if old_current and old_current != version:
                self.cache.set(
                    previous_key,
                    old_current,
                    READ_MODEL_RETENTION_SECONDS,
                )
            self.cache.set(current_key, version, READ_MODEL_RETENTION_SECONDS)
            if old_previous and old_previous not in {old_current, version}:
                try:
                    self._delete_version(business_date, old_previous)
                except Exception as cleanup_error:
                    logger.warning(
                        "清理过期实时快照失败，保留已切换的新版本: date={} "
                        "version={} error={}",
                        business_date,
                        old_previous,
                        cleanup_error,
                    )
            logger.success("实时读模型发布完成: date={} version={}", business_date, version)
            return version
        except Exception:
            try:
                self.cache.delete_many(written_keys)
            except Exception as cleanup_error:
                logger.warning('清理失败版本键时 Redis 不可用: {}', cleanup_error)
            logger.exception("实时读模型发布失败，current 指针保持不变: {}", business_date)
            raise
        finally:
            try:
                lock.release()
            except LockNotOwnedError:
                logger.warning("实时读模型发布锁已失效: {}", business_date)
            except Exception as release_error:
                logger.warning("实时读模型发布锁释放失败: {}", release_error)

    def read(self, view_name: str, business_date: date) -> SnapshotReadResult:
        """读取当前完整版本的指定视图且执行陈旧判断。

        Args:
            view_name: 快照视图名称。
            business_date: 缅甸业务日期。

        Returns:
            数据、元数据和陈旧标记。

        Raises:
            ReadModelNotReadyError: 当前版本、视图或元数据不可用或过旧。
        """
        if view_name not in REQUIRED_VIEW_NAMES:
            raise ReadModelNotReadyError(f"未知实时视图: {view_name}")
        version = self._safe_get(self._current_key(business_date))
        if not version:
            raise ReadModelNotReadyError(f"{business_date} 的实时数据尚未准备好")
        metadata = self._safe_get(self._metadata_key(business_date, version))
        data = self._safe_get(self._view_key(business_date, version, view_name))
        if not isinstance(metadata, dict) or data is None:
            raise ReadModelNotReadyError(f"{business_date} 的实时快照不完整")
        stale = self._validate_read_metadata(metadata, business_date)
        return SnapshotReadResult(
            data=data,
            metadata=metadata,
            stale=stale,
        )

    def read_metadata(self, business_date: date) -> SnapshotReadResult:
        """只读取当前完整版本的元数据。

        Args:
            business_date: 缅甸业务日期。

        Returns:
            空业务数据、当前版本元数据和陈旧标记。

        Raises:
            ReadModelNotReadyError: 当前版本或元数据不可用、无效或过旧。
        """
        version = self._safe_get(self._current_key(business_date))
        if not version:
            raise ReadModelNotReadyError(f"{business_date} 的实时数据尚未准备好")
        metadata = self._safe_get(self._metadata_key(business_date, version))
        if not isinstance(metadata, dict):
            raise ReadModelNotReadyError(f"{business_date} 的实时快照元数据缺失")
        stale = self._validate_read_metadata(metadata, business_date)
        return SnapshotReadResult(
            data={},
            metadata=metadata,
            stale=stale,
        )

    def read_many(
        self,
        view_names: list[str] | tuple[str, ...],
        business_date: date,
    ) -> SnapshotReadResult:
        """固定一次 current 指针并读取多个同版本视图。

        Args:
            view_names: 需要同时读取的视图名称。
            business_date: 缅甸业务日期。

        Returns:
            以视图名为键的数据字典、共同元数据和陈旧标记。

        Raises:
            ReadModelNotReadyError: 任一视图缺失或版本过旧。
        """
        unknown = set(view_names).difference(REQUIRED_VIEW_NAMES)
        if unknown:
            raise ReadModelNotReadyError(f"未知实时视图: {', '.join(sorted(unknown))}")
        version = self._safe_get(self._current_key(business_date))
        if not version:
            raise ReadModelNotReadyError(f"{business_date} 的实时数据尚未准备好")
        metadata = self._safe_get(self._metadata_key(business_date, version))
        if not isinstance(metadata, dict):
            raise ReadModelNotReadyError(f"{business_date} 的实时快照元数据缺失")
        data = {
            view_name: self._safe_get(
                self._view_key(business_date, version, view_name)
            )
            for view_name in view_names
        }
        missing = [name for name, value in data.items() if value is None]
        if missing:
            raise ReadModelNotReadyError(
                f"实时快照缺少同版本视图: {', '.join(sorted(missing))}"
            )
        stale = self._validate_read_metadata(metadata, business_date)
        return SnapshotReadResult(
            data=data,
            metadata=metadata,
            stale=stale,
        )

    def previous_version(self, business_date: date) -> str | None:
        """返回指定日期保留的上一版本号。"""
        return self.cache.get(self._previous_key(business_date))

    def _safe_get(self, key: str):
        """读取缓存并将 Redis 故障转换为统一不可用异常。

        Args:
            key: 需要读取的逻辑缓存键。

        Returns:
            缓存值。

        Raises:
            ReadModelNotReadyError: 缓存后端暂时不可用。
        """
        try:
            return self.cache.get(key)
        except Exception as exc:
            raise ReadModelNotReadyError("Redis 实时读模型暂不可用") from exc

    def _validate_read_metadata(
        self,
        metadata: dict,
        business_date: date,
    ) -> bool:
        """校验已发布元数据并返回陈旧标记。

        Args:
            metadata: 当前版本的快照元数据。
            business_date: 请求的缅甸业务日期。

        Returns:
            快照是否超过软陈旧阈值。

        Raises:
            ReadModelNotReadyError: 元数据不兼容、无效或超过硬阈值。
        """
        if metadata.get("schema_version") != READ_MODEL_SCHEMA_VERSION:
            raise ReadModelNotReadyError("实时快照结构版本不兼容")
        if metadata.get("business_date") != business_date.isoformat():
            raise ReadModelNotReadyError("实时快照业务日期不匹配")
        try:
            generated_at = datetime.fromisoformat(metadata["generated_at"])
            age_seconds = max(0.0, (self.now() - generated_at).total_seconds())
        except (KeyError, TypeError, ValueError) as exc:
            raise ReadModelNotReadyError("实时快照生成时间无效") from exc
        if generated_at.tzinfo is None:
            raise ReadModelNotReadyError("实时快照生成时间缺少时区")
        if age_seconds > READ_MODEL_MAX_STALE_SECONDS:
            raise ReadModelNotReadyError(
                f"实时快照已超过允许的最大陈旧时间: {age_seconds:.0f} 秒"
            )
        return age_seconds > READ_MODEL_STALE_AFTER_SECONDS

    def _verify_written_snapshot(self, business_date: date, version: str) -> None:
        """回读全部必要键，阻止半成品切换为 current。"""
        if self.cache.get(self._metadata_key(business_date, version)) is None:
            raise ConnectionError("快照元数据写入后不可读取")
        missing = [
            view_name
            for view_name in REQUIRED_VIEW_NAMES
            if self.cache.get(self._view_key(business_date, version, view_name)) is None
        ]
        if missing:
            raise ConnectionError(f"快照视图写入不完整: {', '.join(sorted(missing))}")

    def _delete_version(self, business_date: date, version: str) -> None:
        """删除已经超出当前和上一版本范围的键。"""
        keys = [self._metadata_key(business_date, version)]
        keys.extend(
            self._view_key(business_date, version, view_name)
            for view_name in REQUIRED_VIEW_NAMES
        )
        self.cache.delete_many(keys)

    @staticmethod
    def _date_prefix(business_date: date) -> str:
        """生成指定业务日期的键前缀。"""
        return f"{READ_MODEL_CACHE_PREFIX}:{business_date.isoformat()}"

    def _current_key(self, business_date: date) -> str:
        """生成 current 指针键。"""
        return f"{self._date_prefix(business_date)}:current"

    def _previous_key(self, business_date: date) -> str:
        """生成 previous 指针键。"""
        return f"{self._date_prefix(business_date)}:previous"

    def _lock_key(self, business_date: date) -> str:
        """生成发布锁键。"""
        return f"{self._date_prefix(business_date)}:publish-lock"

    def _metadata_key(self, business_date: date, version: str) -> str:
        """生成版本元数据键。"""
        return f"{self._date_prefix(business_date)}:{version}:meta"

    def _view_key(self, business_date: date, version: str, view_name: str) -> str:
        """生成版本视图键。"""
        return f"{self._date_prefix(business_date)}:{version}:{view_name}"
