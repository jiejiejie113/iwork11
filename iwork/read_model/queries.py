"""Web 层使用的统一实时读模型查询接口。"""

from collections import defaultdict
from datetime import date
from math import ceil

from django.conf import settings

from .errors import ReadModelNotReadyError
from .store import SnapshotReadResult, SnapshotStore


# ======
# 查询配置
HIDDEN_FLOWS = frozenset(settings.HIDDEN_FLOWS)
ALLOWED_FLOWS = frozenset(settings.ALLOWED_FLOWS)
ALLOWED_FLOWS_STEPNO = settings.ALLOWED_FLOWS_STEPNO


class ReadModelQueries:
    """从同一版本快照提供实时 API 所需的筛选和分页。"""

    def __init__(self, store: SnapshotStore | None = None) -> None:
        """初始化查询门面。

        Args:
            store: 快照存储；默认使用生产 Redis 后端。
        """
        self.store = store or SnapshotStore()

    def realtime(
        self,
        business_date: date,
        stepnos: list[int] | None = None,
    ) -> SnapshotReadResult:
        """读取单工序、全工序或合并后的多工序统计。"""
        result = self.store.read("realtime", business_date)
        if not stepnos:
            data = result.data.get("all")
        elif len(stepnos) == 1:
            data = result.data.get(stepnos[0]) or result.data.get(str(stepnos[0]))
        else:
            selected = [
                result.data.get(stepno) or result.data.get(str(stepno))
                for stepno in stepnos
            ]
            data = _merge_realtime_views([item for item in selected if item])
        if data is None:
            data = _empty_realtime(business_date, result.data.get("all", {}))
        return _replace_data(result, data)

    def processes(self, business_date: date) -> SnapshotReadResult:
        """读取当前快照的工序列表。"""
        return self.store.read("processes", business_date)

    def workorders(
        self,
        business_date: date,
        page: int = 1,
        page_size: int = 20,
        stepnos: list[int] | None = None,
    ) -> SnapshotReadResult:
        """从快照事实稳定聚合并分页工单。"""
        result = self.store.read("workorders", business_date)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 1000))
        requested_steps = set(stepnos or [])
        grouped: dict[str, dict] = {}
        for row in result.data.get("rows", []):
            if requested_steps and row["stepno"] not in requested_steps:
                continue
            if (
                requested_steps
                and ALLOWED_FLOWS_STEPNO in requested_steps
                and not ALLOWED_FLOWS.intersection(row.get("flows", []))
            ):
                continue
            item = grouped.setdefault(
                row["wrk_order"],
                {"total_qty": 0, "employee_ids": set(), "flows": set()},
            )
            item["total_qty"] += int(row.get("total_qty", 0))
            item["employee_ids"].update(row.get("employee_ids", []))
            item["flows"].update(row.get("flows", []))

        products = result.data.get("products", {})
        items = []
        for wrk_order, values in grouped.items():
            product = products.get(wrk_order, {})
            items.append({
                "wrk_order": wrk_order,
                "total_qty": values["total_qty"],
                "worker_count": len(values["employee_ids"]),
                "flows": sorted(values["flows"]),
                "product_name": product.get("product_name", ""),
                "order_no": product.get("order_no", ""),
            })
        items.sort(key=lambda item: (-item["total_qty"], item["wrk_order"]))
        total = len(items)
        start = (page - 1) * page_size
        data = {
            "items": items[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, ceil(total / page_size)),
        }
        return _replace_data(result, data)

    def workorder_detail(
        self,
        business_date: date,
        wrk_order: str,
    ) -> SnapshotReadResult:
        """读取工单详情；不存在时返回兼容的空详情。"""
        result = self.store.read("workorder_details", business_date)
        data = result.data.get(wrk_order, {
            "wrk_order": wrk_order,
            "total_qty": 0,
            "steps": [],
        })
        return _replace_data(result, data)

    def detail(self, business_date: date, name: str) -> SnapshotReadResult:
        """读取生产详情批次中的指定命名视图。"""
        result = self.store.read("detail", business_date)
        if name not in result.data:
            raise ReadModelNotReadyError(f"实时详情视图不存在: {name}")
        return _replace_data(result, result.data[name])

    def details(self, business_date: date) -> SnapshotReadResult:
        """读取当前版本的完整生产详情批次。"""
        return self.store.read("detail", business_date)

    def snapshot_metadata(self, business_date: date) -> SnapshotReadResult:
        """读取当前快照版本元数据，不加载任何业务视图。"""
        return self.store.read_metadata(business_date)

    def stream_payload(
        self,
        business_date: date,
        stepnos: list[int] | None = None,
    ) -> SnapshotReadResult:
        """固定同一版本读取 SSE 所需的统计、工序和详情概览。"""
        result = self.store.read_many(
            ("realtime", "processes", "detail"),
            business_date,
        )
        realtime_result = SnapshotReadResult(
            data=result.data["realtime"],
            metadata=result.metadata,
            stale=result.stale,
        )
        if not stepnos:
            stats = realtime_result.data.get("all")
        elif len(stepnos) == 1:
            stats = (
                realtime_result.data.get(stepnos[0])
                or realtime_result.data.get(str(stepnos[0]))
            )
        else:
            selected = [
                realtime_result.data.get(stepno)
                or realtime_result.data.get(str(stepno))
                for stepno in stepnos
            ]
            stats = _merge_realtime_views([item for item in selected if item])
        stats = stats or _empty_realtime(business_date, realtime_result.data.get("all", {}))
        payload = {
            "data": stats,
            "process_list": result.data["processes"],
            "detail_overview": result.data["detail"].get("flow_overview", {}),
        }
        return _replace_data(result, payload)

    def kanban_stats(self, business_date: date, **filters) -> SnapshotReadResult:
        """从最低粒度事实计算看板汇总。"""
        result = self.store.read("kanban", business_date)
        facts = _filter_kanban_facts(result.data, **filters)
        totals = _worker_totals(facts)
        ranked = sorted(totals.items(), key=lambda item: (-item[1], str(item[0])))
        total = sum(totals.values())
        count = len(totals)
        data = {
            "worker_count": count,
            "total_production": total,
            "avg_production": round(total / count) if count else 0,
            "max_production": ranked[0][1] if ranked else 0,
            "max_worker_name": str(ranked[0][0]) if ranked else "",
        }
        return _replace_data(result, data)

    def kanban_ranking(
        self,
        business_date: date,
        page: int = 1,
        page_size: int = 50,
        **filters,
    ) -> SnapshotReadResult:
        """从同一份筛选事实生成稳定员工排行。"""
        result = self.store.read("kanban", business_date)
        facts = _filter_kanban_facts(result.data, **filters)
        worker_map: dict[object, dict] = {}
        for fact in facts:
            employee_id = fact.get("reg_per_sys_id")
            worker = worker_map.setdefault(
                employee_id,
                {"production": 0, "stepnos": set(), "wrk_orders": set(), "flows": set()},
            )
            worker["production"] += int(fact.get("qty", 0))
            worker["stepnos"].add(str(fact.get("stepno", "")))
            if fact.get("wrk_order"):
                worker["wrk_orders"].add(fact["wrk_order"])
            if fact.get("flow"):
                worker["flows"].add(fact["flow"])
        workers = [
            {
                "reg_per_sys_id": employee_id,
                "worker_name": str(employee_id),
                "stepno": "、".join(sorted(values["stepnos"])),
                "wrk_orders": sorted(values["wrk_orders"]),
                "flow": "、".join(sorted(values["flows"])),
                "production": values["production"],
            }
            for employee_id, values in worker_map.items()
        ]
        workers.sort(key=lambda item: (-item["production"], str(item["reg_per_sys_id"])))
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 1000))
        total = len(workers)
        start = (page - 1) * page_size
        page_data = workers[start:start + page_size]
        for index, worker in enumerate(page_data, start=start + 1):
            worker["rank"] = index
        data = {
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, ceil(total / page_size)),
                "total_count": total,
            },
            "workers": page_data,
        }
        return _replace_data(result, data)

    def kanban_filter_options(self, business_date: date, **filters) -> SnapshotReadResult:
        """基于最低粒度事实生成级联筛选项。"""
        result = self.store.read("kanban", business_date)
        selected = {
            "stepnos": filters.get("stepnos"),
            "wrk_orders": filters.get("wrk_orders"),
            "flows": filters.get("flows"),
            "reg_per_sys_ids": filters.get("reg_per_sys_ids"),
            "show_all_flows": filters.get("show_all_flows", False),
        }

        def without(name: str) -> list[dict]:
            current = dict(selected)
            current[name] = None
            return _filter_kanban_facts(result.data, **current)

        employee_ids = sorted(
            {item.get("reg_per_sys_id") for item in without("reg_per_sys_ids")},
            key=str,
        )
        data = {
            "stepnos": sorted({item.get("stepno") for item in without("stepnos")}),
            "wrk_orders": sorted({item.get("wrk_order") for item in without("wrk_orders") if item.get("wrk_order")}),
            "flows": sorted({item.get("flow") for item in without("flows") if item.get("flow")}),
            "employees": [
                {"reg_per_sys_id": employee_id, "name": str(employee_id)}
                for employee_id in employee_ids
            ],
        }
        return _replace_data(result, data)


def _replace_data(result: SnapshotReadResult, data: object) -> SnapshotReadResult:
    """保留元数据和陈旧标记，仅替换查询结果数据。"""
    return SnapshotReadResult(data=data, metadata=result.metadata, stale=result.stale)


def _empty_realtime(business_date: date, all_view: dict) -> dict:
    """构造不存在工序的兼容空响应。"""
    return {
        "workorder_count": 0,
        "total_qty": 0,
        "date": business_date,
        "hourly_stats": [],
        "process_flow_stats": [],
        "monthly_process_stats": [],
        "monthly_total_trend": [],
        "monthly_hourly_stats": [],
        "station_stats": [],
        "heatmap_matrix": {"hours": [], "flows": [], "data": []},
        "station_ranking": [],
        "top_processes": [],
        "workorders": [],
        "all_stepnos": all_view.get("all_stepnos", []),
    }


def _merge_realtime_views(views: list[dict]) -> dict:
    """合并同一版本内的多个工序视图。"""
    if not views:
        return {}
    hourly = _sum_rows(views, "hourly_stats", "hour")
    monthly_total = _sum_rows(views, "monthly_total_trend", "date")
    station_ranking = _sum_rows(views, "station_ranking", "station")
    workorders: dict[str, dict] = {}
    for view in views:
        for item in view.get("workorders", []):
            row = workorders.setdefault(
                item["wrk_order"],
                {"wrk_order": item["wrk_order"], "total_qty": 0, "flows": set()},
            )
            row["total_qty"] += int(item.get("total_qty", 0))
            row["flows"].update(item.get("flows", []))
    merged_workorders = [
        {**item, "flows": sorted(item["flows"])} for item in workorders.values()
    ]
    merged_workorders.sort(key=lambda item: (-item["total_qty"], item["wrk_order"]))
    return {
        "workorder_count": len(workorders),
        "total_qty": sum(int(view.get("total_qty", 0)) for view in views),
        "date": views[0].get("date"),
        "hourly_stats": hourly,
        "process_flow_stats": [item for view in views for item in view.get("process_flow_stats", [])],
        "monthly_process_stats": [item for view in views for item in view.get("monthly_process_stats", [])],
        "monthly_total_trend": monthly_total,
        "monthly_hourly_stats": [item for view in views for item in view.get("monthly_hourly_stats", [])],
        "station_stats": station_ranking[:10],
        "heatmap_matrix": _merge_heatmaps([view.get("heatmap_matrix", {}) for view in views]),
        "station_ranking": station_ranking,
        "top_processes": [item for view in views for item in view.get("top_processes", [])],
        "workorders": merged_workorders[:20],
        "all_stepnos": views[0].get("all_stepnos", []),
    }


def _sum_rows(views: list[dict], field: str, key: str) -> list[dict]:
    """按指定字段合并包含 qty 的列表。"""
    totals: dict[object, int] = defaultdict(int)
    for view in views:
        for item in view.get(field, []):
            totals[item.get(key)] += int(item.get("qty", 0))
    return [{key: value, "qty": totals[value]} for value in sorted(totals)]


def _merge_heatmaps(matrices: list[dict]) -> dict:
    """按小时和 Flow 合并多个热力图矩阵。"""
    totals: dict[tuple[object, object], int] = defaultdict(int)
    hours = set()
    flows = set()
    for matrix in matrices:
        matrix_hours = matrix.get("hours", [])
        matrix_flows = matrix.get("flows", [])
        hours.update(matrix_hours)
        flows.update(matrix_flows)
        for hour_index, hour in enumerate(matrix_hours):
            row = matrix.get("data", [])[hour_index]
            for flow_index, flow in enumerate(matrix_flows):
                totals[(hour, flow)] += int(row[flow_index])
    ordered_hours = sorted(hours)
    ordered_flows = sorted(flows)
    return {
        "hours": ordered_hours,
        "flows": ordered_flows,
        "data": [
            [totals[(hour, flow)] for flow in ordered_flows]
            for hour in ordered_hours
        ],
    }


def _filter_kanban_facts(
    facts: list[dict],
    stepnos=None,
    wrk_orders=None,
    flows=None,
    reg_per_sys_ids=None,
    show_all_flows: bool = False,
) -> list[dict]:
    """统一应用看板多选筛选和隐藏 Flow 规则。"""
    step_set = {int(value) for value in stepnos or []}
    workorder_set = {str(value) for value in wrk_orders or []}
    flow_set = {str(value) for value in flows or []}
    employee_set = {str(value) for value in reg_per_sys_ids or []}
    result = []
    for fact in facts:
        if not show_all_flows and fact.get("flow") in HIDDEN_FLOWS:
            continue
        if step_set and int(fact.get("stepno") or 0) not in step_set:
            continue
        if workorder_set and str(fact.get("wrk_order") or "") not in workorder_set:
            continue
        if flow_set and str(fact.get("flow") or "") not in flow_set:
            continue
        if employee_set and str(fact.get("reg_per_sys_id")) not in employee_set:
            continue
        result.append(fact)
    return result


def _worker_totals(facts: list[dict]) -> dict[object, int]:
    """按员工汇总最低粒度事实的产量。"""
    totals: dict[object, int] = defaultdict(int)
    for fact in facts:
        totals[fact.get("reg_per_sys_id")] += int(fact.get("qty", 0))
    return dict(totals)
