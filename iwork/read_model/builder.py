"""从受控远程查询构建完整实时快照。"""

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

from django.conf import settings

from iwork.statistics import get_batch_detail_stats, get_batch_stats

from .fact_source import ReadModelFactSource
from .schemas import READ_MODEL_SCHEMA_VERSION, validate_snapshot


# ======
# 构建器配置
BUSINESS_TIME_ZONE = ZoneInfo(settings.IWORK_BUSINESS_TIME_ZONE)


def build_snapshot(
    business_date: date,
    source=None,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """为单个曼谷业务日期构建完整快照。

    Args:
        business_date: 需要构建的曼谷业务日期。
        source: 远程查询模块兼容适配器；默认使用 ``iwork.queries``。
        now: 返回当前时间的函数；主要用于稳定测试版本信息。

    Returns:
        可交给 ``SnapshotStore.publish`` 的完整快照。
    """
    source = source or ReadModelFactSource.collect(business_date)
    current_time = (now or (lambda: datetime.now(BUSINESS_TIME_ZONE)))()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=BUSINESS_TIME_ZONE)

    realtime = get_batch_stats(q=source, target_date=business_date)
    detail = get_batch_detail_stats(q=source, target_date=business_date)
    fact_payload = source.get_read_model_facts(business_date)
    facts = fact_payload.get("facts", [])
    products = fact_payload.get("products", {})
    workorders, workorder_details = _build_workorder_views(facts, products)
    completed_at = (now or (lambda: datetime.now(BUSINESS_TIME_ZONE)))()
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=BUSINESS_TIME_ZONE)

    snapshot = {
        "metadata": {
            "schema_version": READ_MODEL_SCHEMA_VERSION,
            "snapshot_version": (
                f'{completed_at.strftime("%Y%m%d-%H%M%S-%f")}-{uuid4().hex[:8]}'
            ),
            "business_date": business_date.isoformat(),
            "generated_at": completed_at.isoformat(),
            "source_completed_at": completed_at.isoformat(),
            "source_status": "success",
            "record_count": sum(int(item.get("record_count", 0)) for item in facts),
        },
        "views": {
            "realtime": realtime,
            "processes": sorted(
                (stepno for stepno in realtime if stepno != "all"),
                reverse=True,
            ),
            "workorders": workorders,
            "workorder_details": workorder_details,
            "detail": detail,
            "kanban": facts,
        },
    }
    validate_snapshot(snapshot)
    return snapshot


def _build_workorder_views(facts: list[dict], products: dict) -> tuple[dict, dict]:
    """从最低粒度事实构建可筛选工单行和详情映射。

    Args:
        facts: 员工、工序、工单和 Flow 粒度的聚合事实。
        products: 按完整工单号组织的产品信息。

    Returns:
        工单查询视图和工单详情映射。
    """
    row_groups: dict[tuple[str, int, str], dict] = {}
    detail_groups: dict[str, dict[int, dict]] = defaultdict(dict)
    for fact in facts:
        wrk_order = str(fact.get("wrk_order") or "")
        stepno = int(fact.get("stepno") or 0)
        qty = int(fact.get("qty") or 0)
        employee_id = fact.get("reg_per_sys_id")
        flow = str(fact.get("flow") or "")
        row = row_groups.setdefault(
            (wrk_order, stepno, flow),
            {
                "wrk_order": wrk_order,
                "stepno": stepno,
                "total_qty": 0,
                "employee_ids": set(),
                "flows": set(),
            },
        )
        row["total_qty"] += qty
        if employee_id is not None:
            row["employee_ids"].add(employee_id)
        if flow:
            row["flows"].add(flow)

        step = detail_groups[wrk_order].setdefault(
            stepno,
            {"StepNo": stepno, "qty": 0, "count": 0},
        )
        step["qty"] += qty
        step["count"] += int(fact.get("record_count", 0))

    rows = []
    for row in row_groups.values():
        rows.append({
            **row,
            "employee_ids": sorted(row["employee_ids"], key=str),
            "flows": sorted(row["flows"]),
        })
    rows.sort(key=lambda item: (item["wrk_order"], item["stepno"]))

    details = {}
    for wrk_order, steps in detail_groups.items():
        ordered_steps = [steps[key] for key in sorted(steps)]
        details[wrk_order] = {
            "wrk_order": wrk_order,
            "total_qty": sum(item["qty"] for item in ordered_steps),
            "steps": ordered_steps,
        }
    return {"rows": rows, "products": products}, details
