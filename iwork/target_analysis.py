"""今日目标分析的时段产量聚合与目标达成计算。"""

from collections.abc import Collection, Iterable, Mapping
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


# ======
# 今日目标分析配置
TARGET_ANALYSIS_STEP_NO = settings.TARGET_ANALYSIS_STEP_NO
TARGET_ANALYSIS_TIME_ZONE = settings.IWORK_BUSINESS_TIME_ZONE
NORMAL_TARGET_WORK_MINUTES = settings.TARGET_ANALYSIS_NORMAL_WORK_MINUTES
TARGET_ANALYSIS_PERIODS = settings.TARGET_ANALYSIS_PERIODS


def get_period_metadata() -> list[dict[str, object]]:
    """返回今日目标分析的固定时段元数据。

    Returns:
        list[dict[str, object]]: 按早上、下午、晚上排列的时段配置副本。
    """
    return [
        {
            "key": period["key"],
            "label": period["label"],
            "time_range": period["time_range"],
            "duration_minutes": period["duration_minutes"],
        }
        for period in TARGET_ANALYSIS_PERIODS
    ]


def aggregate_target_analysis(
    facts: Iterable[Mapping[str, object]],
    allowed_flows: Collection[str] | None = None,
) -> dict[str, dict[str, int]]:
    """按 Flow 汇总70号工序在三个时间段内的实际产量。

    Args:
        facts: 包含 ``stepno``、``flow``、``event_hour`` 和 ``qty`` 的事实行。
        allowed_flows: 可选的 Flow 白名单；为空时保留事实中的全部非空 Flow。

    Returns:
        dict[str, dict[str, int]]: ``{Flow: {morning, afternoon, night}}``。
    """
    flow_filter = {str(flow) for flow in allowed_flows} if allowed_flows is not None else None
    result: dict[str, dict[str, int]] = {}
    for fact in facts:
        if _as_int(fact.get("stepno")) != TARGET_ANALYSIS_STEP_NO:
            continue
        flow = str(fact.get("flow") or "").strip()
        if not flow or (flow_filter is not None and flow not in flow_filter):
            continue
        period_key = _period_key(_as_int_or_none(fact.get("event_hour")))
        if period_key is None:
            continue
        period_totals = result.setdefault(
            flow,
            {period["key"]: 0 for period in TARGET_ANALYSIS_PERIODS},
        )
        period_totals[period_key] += _as_int(fact.get("qty"))
    return result


def build_target_analysis_snapshot(
    facts: Iterable[Mapping[str, object]],
    allowed_flows: Collection[str] | None = None,
) -> dict[str, object]:
    """构建可写入实时读模型的今日目标分析视图。

    Args:
        facts: 当前缅甸业务日的生产事实。
        allowed_flows: 可选的生产组白名单。

    Returns:
        dict[str, object]: 包含工序、时区、时段和各 Flow 实际产量的快照视图。
    """
    return {
        "step_no": TARGET_ANALYSIS_STEP_NO,
        "time_zone": TARGET_ANALYSIS_TIME_ZONE,
        "periods": get_period_metadata(),
        "flows": aggregate_target_analysis(facts, allowed_flows),
    }


def build_period_analysis(
    actuals: Mapping[str, object] | None,
    *,
    target_qty: int | None,
    planned_work_minutes: int | None,
) -> list[dict[str, object]]:
    """为单个生产组生成三个时段的实际、目标和达成率。

    Args:
        actuals: 单个 Flow 的时段实际产量；缺失时按0处理。
        target_qty: 已提交的整组目标产量。
        planned_work_minutes: 已提交的计划工作分钟。

    Returns:
        list[dict[str, object]]: 按早上、下午、晚上排列的分析行。
    """
    safe_actuals = actuals or {}
    regular_minutes = _regular_target_work_minutes(planned_work_minutes)
    can_calculate_target = (
        target_qty is not None
        and target_qty > 0
        and regular_minutes > 0
    )
    normal_period_minutes = _normal_period_minutes(regular_minutes)
    rows = []
    for period in TARGET_ANALYSIS_PERIODS:
        key = str(period["key"])
        actual_qty = _as_int(safe_actuals.get(key))
        target_value = None
        achievement_rate = None
        target_minutes = normal_period_minutes.get(key, 0)
        if can_calculate_target and target_minutes > 0:
            target_decimal = (
                Decimal(target_qty)
                * Decimal(target_minutes)
                / Decimal(regular_minutes)
            )
            target_value = _round_decimal(target_decimal, 2)
            achievement_rate = _round_decimal(
                Decimal(actual_qty) / target_decimal * Decimal(100),
                1,
            )
        rows.append({
            "key": key,
            "label": period["label"],
            "time_range": period["time_range"],
            "actual_qty": actual_qty,
            "target_qty": target_value,
            "achievement_rate": achievement_rate,
        })
    return rows


def _period_key(event_hour: int | None) -> str | None:
    """根据小时值返回所属时段键。

    Args:
        event_hour (int | None): 生产事实的本地小时值。

    Returns:
        str | None: 对应的时段键；不在统计窗口内时返回 ``None``。
    """
    if event_hour is None:
        return None
    for period in TARGET_ANALYSIS_PERIODS:
        if period["start_hour"] <= event_hour < period["end_hour"]:
            return str(period["key"])
    return None


def _normal_period_minutes(regular_minutes: int) -> dict[str, int]:
    """按作息时段顺序分配正常工时对应的目标分钟数。

    各时段最多分配到自身时长，超出的正常工时不再向后顺延；
    这样缅甸作息（4/4/2 小时）下 10 小时正常工时可完整覆盖三个时段。

    Args:
        regular_minutes (int): 已限制在正常工作时长范围内的分钟数。

    Returns:
        dict[str, int]: 各统计时段应分配目标的分钟数。
    """
    remaining = max(int(regular_minutes), 0)
    allocation: dict[str, int] = {}
    for period in TARGET_ANALYSIS_PERIODS:
        key = str(period["key"])
        minutes = min(remaining, int(period["duration_minutes"]))
        allocation[key] = minutes
        remaining -= minutes
    return allocation


def _regular_target_work_minutes(planned_work_minutes: int | None) -> int:
    """将计划工时限制在不含加班的最多10小时内。

    Args:
        planned_work_minutes (int | None): 已提交的计划工作分钟数。

    Returns:
        int: 可用于正常目标分配的非负分钟数。
    """
    if planned_work_minutes is None:
        return 0
    try:
        return min(max(int(planned_work_minutes), 0), NORMAL_TARGET_WORK_MINUTES)
    except (TypeError, ValueError):
        return 0


def _as_int(value: object) -> int:
    """将事实或产量值转换为整数，无法转换时返回0。

    Args:
        value (object): 待转换的事实字段或产量值。

    Returns:
        int: 转换后的整数，空值或非法值返回0。
    """
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_int_or_none(value: object) -> int | None:
    """将小时值转换为整数，空值或非法值返回None。

    Args:
        value (object): 待转换的小时值。

    Returns:
        int | None: 转换后的整数，空值或非法值返回``None``。
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round_decimal(value: Decimal, places: int) -> float:
    """按指定小数位使用四舍五入并转换为JSON可序列化浮点数。

    Args:
        value (Decimal): 待舍入的十进制定点数。
        places (int): 需要保留的小数位数。

    Returns:
        float: 使用 ``ROUND_HALF_UP`` 舍入后的浮点数。
    """
    quantizer = Decimal("1") if places == 0 else Decimal(f"1.{'0' * places}")
    return float(value.quantize(quantizer, rounding=ROUND_HALF_UP))
