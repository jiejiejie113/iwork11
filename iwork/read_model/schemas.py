"""实时读模型快照结构与校验规则。"""

from datetime import date, datetime

from django.conf import settings

from iwork.target_analysis import (
    TARGET_ANALYSIS_STEP_NO,
    TARGET_ANALYSIS_TIME_ZONE,
    get_period_metadata,
)

from .errors import SnapshotConsistencyError, SnapshotValidationError


# ======
# 快照结构配置
READ_MODEL_SCHEMA_VERSION = settings.READ_MODEL_SCHEMA_VERSION
REQUIRED_VIEW_NAMES = frozenset({
    "realtime",
    "processes",
    "workorders",
    "workorder_details",
    "detail",
    "kanban",
    "target_analysis",
})
REQUIRED_DETAIL_NAMES = frozenset({
    "flow_overview",
    "flow_hourly",
    "flow_employees",
    "stepno_employees",
    "product_overview",
})


def _sum_qty_for_business_date(
    rows: list[dict],
    business_date: date,
    field_name: str,
) -> int:
    """汇总指定业务日期的产量并校验明细结构。

    Args:
        rows: 包含 ``date`` 与 ``qty`` 的统计明细。
        business_date: 需要汇总的缅甸业务日期。
        field_name: 用于错误提示的字段名称。

    Returns:
        指定业务日期的产量合计。

    Raises:
        SnapshotValidationError: 明细不是字典列表或产量不是整数。
    """
    if not isinstance(rows, list):
        raise SnapshotValidationError(f"实时视图字段结构无效: {field_name}")

    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise SnapshotValidationError(f"实时视图字段结构无效: {field_name}")
        row_date = row.get("date")
        if isinstance(row_date, date):
            row_date = row_date.isoformat()
        if row_date != business_date.isoformat():
            continue
        qty = row.get("qty")
        if not isinstance(qty, int):
            raise SnapshotValidationError(f"实时视图产量无效: {field_name}")
        total += qty
    return total


def _validate_realtime_totals(realtime: dict, business_date: date) -> None:
    """校验实时、Flow 与当日月统计的同语义产量一致性。

    Args:
        realtime: 按 ``all`` 和工序号组织的实时统计视图。
        business_date: 当前快照对应的缅甸业务日期。

    Raises:
        SnapshotValidationError: 任一可比较汇总与实时总量不一致。
    """
    for view_name, item in realtime.items():
        if not isinstance(item, dict) or "total_qty" not in item:
            continue
        total_qty = item["total_qty"]
        if not isinstance(total_qty, int):
            raise SnapshotValidationError(
                f"实时视图总产量无效: view={view_name}"
            )

        process_flow_stats = item.get("process_flow_stats")
        if process_flow_stats is not None:
            if not isinstance(process_flow_stats, list):
                raise SnapshotValidationError("实时视图字段结构无效: process_flow_stats")
            flow_total = 0
            for row in process_flow_stats:
                if not isinstance(row, dict) or not isinstance(row.get("qty"), int):
                    raise SnapshotValidationError("实时视图产量无效: process_flow_stats")
                flow_total += row["qty"]
            if flow_total != total_qty:
                raise SnapshotConsistencyError(
                    "实时总量与 Flow 汇总不一致: "
                    f"view={view_name} total={total_qty} flow={flow_total}"
                )

        monthly_total_trend = item.get("monthly_total_trend")
        if monthly_total_trend is not None:
            monthly_total = _sum_qty_for_business_date(
                monthly_total_trend,
                business_date,
                "monthly_total_trend",
            )
            if monthly_total != total_qty:
                raise SnapshotConsistencyError(
                    "实时总量与当日月趋势不一致: "
                    f"view={view_name} total={total_qty} monthly={monthly_total}"
                )

        monthly_process_stats = item.get("monthly_process_stats")
        if view_name != "all" and monthly_process_stats is not None:
            process_total = _sum_qty_for_business_date(
                monthly_process_stats,
                business_date,
                "monthly_process_stats",
            )
            if process_total != total_qty:
                raise SnapshotConsistencyError(
                    "实时总量与当日工序月统计不一致: "
                    f"view={view_name} total={total_qty} process={process_total}"
                )


def _validate_target_analysis(target_analysis: dict) -> None:
    """校验今日目标分析视图的固定元数据和嵌套产量结构。

    Args:
        target_analysis (dict): 待写入或读取的今日目标分析视图。

    Raises:
        SnapshotValidationError: 分析时段或 Flow 产量结构不符合约定。
    """
    if target_analysis.get("step_no") != TARGET_ANALYSIS_STEP_NO:
        raise SnapshotValidationError(
            f"今日目标分析工序必须为{TARGET_ANALYSIS_STEP_NO}"
        )
    if target_analysis.get("time_zone") != TARGET_ANALYSIS_TIME_ZONE:
        raise SnapshotValidationError(
            "今日目标分析时区必须为" + TARGET_ANALYSIS_TIME_ZONE
        )

    periods = target_analysis.get("periods")
    if periods != get_period_metadata():
        raise SnapshotValidationError("今日目标分析时段结构无效")

    flows = target_analysis.get("flows")
    if not isinstance(flows, dict):
        raise SnapshotValidationError("今日目标分析Flow结构无效")
    period_keys = {period["key"] for period in get_period_metadata()}
    for flow, period_totals in flows.items():
        if not isinstance(flow, str) or not flow.strip():
            raise SnapshotValidationError("今日目标分析Flow名称无效")
        if not isinstance(period_totals, dict) or set(period_totals) != period_keys:
            raise SnapshotValidationError(
                f"今日目标分析Flow时段结构无效: {flow}"
            )
        for period_key in period_keys:
            quantity = period_totals[period_key]
            if not isinstance(quantity, int) or isinstance(quantity, bool):
                raise SnapshotValidationError(
                    f"今日目标分析产量无效: {flow}/{period_key}"
                )


def validate_snapshot(snapshot: dict) -> tuple[dict, dict]:
    """校验完整快照并返回元数据与视图。

    Args:
        snapshot: 包含 ``metadata`` 和 ``views`` 的待发布快照。

    Returns:
        校验后的元数据和视图字典。

    Raises:
        SnapshotValidationError: 快照结构、版本或业务日期无效。
    """
    if not isinstance(snapshot, dict):
        raise SnapshotValidationError("快照必须是字典")
    metadata = snapshot.get("metadata")
    views = snapshot.get("views")
    if not isinstance(metadata, dict) or not isinstance(views, dict):
        raise SnapshotValidationError("快照必须包含 metadata 和 views 字典")

    missing_views = REQUIRED_VIEW_NAMES.difference(views)
    if missing_views:
        names = ", ".join(sorted(missing_views))
        raise SnapshotValidationError(f"快照缺少必要视图: {names}")

    if metadata.get("schema_version") != READ_MODEL_SCHEMA_VERSION:
        raise SnapshotValidationError("快照结构版本不兼容")
    if metadata.get("source_status") != "success":
        raise SnapshotValidationError("远程数据源未成功完成，禁止发布")

    snapshot_version = metadata.get("snapshot_version")
    if not isinstance(snapshot_version, str) or not snapshot_version:
        raise SnapshotValidationError("快照版本不能为空")

    try:
        business_date = date.fromisoformat(metadata["business_date"])
        generated_at = datetime.fromisoformat(metadata["generated_at"])
        datetime.fromisoformat(metadata["source_completed_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotValidationError("快照日期或时间格式无效") from exc
    if generated_at.tzinfo is None:
        raise SnapshotValidationError("快照生成时间必须包含时区")

    record_count = metadata.get("record_count")
    if not isinstance(record_count, int) or record_count < 0:
        raise SnapshotValidationError("快照记录数必须是非负整数")

    expected_types = {
        "realtime": dict,
        "processes": list,
        "workorders": dict,
        "workorder_details": dict,
        "detail": dict,
        "kanban": list,
        "target_analysis": dict,
    }
    for view_name, expected_type in expected_types.items():
        if not isinstance(views[view_name], expected_type):
            raise SnapshotValidationError(f"快照视图结构无效: {view_name}")

    _validate_target_analysis(views["target_analysis"])

    workorders = views["workorders"]
    if not isinstance(workorders.get("rows"), list) or not isinstance(
        workorders.get("products"),
        dict,
    ):
        raise SnapshotValidationError("工单视图结构无效")

    missing_detail = REQUIRED_DETAIL_NAMES.difference(views["detail"])
    if missing_detail:
        raise SnapshotValidationError(
            "生产详情视图不完整: " + ", ".join(sorted(missing_detail))
        )

    realtime = views["realtime"]
    if not isinstance(realtime.get("all"), dict):
        raise SnapshotValidationError("实时视图缺少 all 汇总")
    for item in realtime.values():
        if not isinstance(item, dict) or "date" not in item:
            continue
        item_date = item["date"]
        if isinstance(item_date, date):
            item_date = item_date.isoformat()
        if item_date != business_date.isoformat():
            raise SnapshotValidationError("实时视图业务日期不一致")
    _validate_realtime_totals(realtime, business_date)

    fact_record_count = 0
    for fact in views["kanban"]:
        if not isinstance(fact, dict):
            raise SnapshotValidationError("Kanban 事实结构无效")
        fact_count = fact.get("record_count")
        if not isinstance(fact_count, int) or fact_count < 0:
            raise SnapshotValidationError("Kanban 事实记录数无效")
        fact_record_count += fact_count
    if fact_record_count != record_count:
        raise SnapshotValidationError(
            "快照记录数不一致: "
            f"metadata={record_count} facts={fact_record_count}"
        )
    return metadata, views
