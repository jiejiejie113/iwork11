"""警报检测与通知渠道的公共契约。"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


@dataclass(frozen=True)
class AlertCandidate:
    """描述一个检测器发现的稳定业务异常。"""

    rule_code: str
    business_date: date
    dimension_key: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class EvaluationContext:
    """向检测器提供不会污染快照的评估上下文。"""

    business_date: date
    snapshot_version: str


class AlertDetector(Protocol):
    """评估当前与上一份快照并返回警报候选。"""

    def evaluate(
        self,
        current_snapshot: dict[str, Any],
        previous_snapshot: dict[str, Any] | None,
        context: EvaluationContext,
    ) -> list[AlertCandidate]:
        """评估快照并返回警报候选。

        Args:
            current_snapshot: 当前已发布快照。
            previous_snapshot: 上一份可用快照；不存在时为 ``None``。
            context: 本轮业务日期和快照版本。

        Returns:
            list[AlertCandidate]: 本轮发现的警报候选。
        """
        ...


class NotificationChannel(Protocol):
    """将警报事件投递给已解析受众。"""

    def publish(self, event: object, audience: object) -> object:
        """投递一条通知。

        Args:
            event: 待投递的警报事件。
            audience: 已经过权限校验的受众。

        Returns:
            object: 渠道特定的投递结果。
        """
        ...
