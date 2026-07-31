"""实时读模型快照结构与校验规则。"""

from datetime import date, datetime

from django.conf import settings

from .errors import SnapshotValidationError


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
})
REQUIRED_DETAIL_NAMES = frozenset({
    "flow_overview",
    "flow_hourly",
    "flow_employees",
    "stepno_employees",
    "product_overview",
})


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
    }
    for view_name, expected_type in expected_types.items():
        if not isinstance(views[view_name], expected_type):
            raise SnapshotValidationError(f"快照视图结构无效: {view_name}")

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
