"""实时读模型 50 用户并发读取验证。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.core.cache import cache

from iwork.read_model.queries import ReadModelQueries
from iwork.read_model.store import SnapshotStore


BUSINESS_DATE = date(2026, 7, 31)
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Asia/Yangon"))


def _snapshot() -> dict:
    """构造 50 用户并发读取使用的完整快照。"""
    realtime_view = {
        "date": BUSINESS_DATE,
        "total_qty": 100,
        "workorder_count": 1,
        "hourly_stats": [{"hour": 8, "qty": 100}],
        "process_flow_stats": [{"step": 70, "flow": "Sewing-A1", "qty": 100}],
        "monthly_total_trend": [
            {"date": BUSINESS_DATE.isoformat(), "qty": 100},
        ],
        "monthly_process_stats": [
            {"date": BUSINESS_DATE.isoformat(), "step": 70, "qty": 100},
        ],
        "monthly_hourly_stats": [],
        "station_ranking": [],
        "station_stats": [],
        "top_processes": [{"step": 70, "qty": 100}],
        "workorders": [{"wrk_order": "WO1", "total_qty": 100, "flows": ["Sewing-A1"]}],
        "all_stepnos": [70],
        "heatmap_matrix": {"hours": [], "flows": [], "data": []},
    }
    return {
        "metadata": {
            "schema_version": 1,
            "snapshot_version": "concurrency-v1",
            "business_date": BUSINESS_DATE.isoformat(),
            "generated_at": NOW.isoformat(),
            "source_completed_at": NOW.isoformat(),
            "source_status": "success",
            "record_count": 1,
        },
        "views": {
            "realtime": {70: realtime_view, "all": realtime_view},
            "processes": [70],
            "workorders": {
                "rows": [{
                    "wrk_order": "WO1",
                    "stepno": 70,
                    "total_qty": 100,
                    "employee_ids": [1],
                    "flows": ["Sewing-A1"],
                }],
                "products": {},
            },
            "workorder_details": {
                "WO1": {"wrk_order": "WO1", "total_qty": 100, "steps": []}
            },
            "detail": {
                "flow_overview": {},
                "flow_employees": {},
                "flow_hourly": {},
                "stepno_employees": {},
                "product_overview": {},
            },
            "kanban": [{
                "reg_per_sys_id": 1,
                "stepno": 70,
                "wrk_order": "WO1",
                "flow": "Sewing-A1",
                "qty": 100,
                "record_count": 1,
            }],
        },
    }


def test_fifty_users_read_identical_snapshot_without_errors():
    """50 用户同时读取 SSE、工单和看板时结果版本及总量一致。"""
    cache.clear()
    store = SnapshotStore(cache_backend=cache, now=lambda: NOW)
    store.publish(_snapshot())
    queries = ReadModelQueries(store=store)

    def load_user_page(_user_number: int) -> tuple[str, int, int, int]:
        """模拟一个用户加载三个只读模块。"""
        stream = queries.stream_payload(BUSINESS_DATE, [70])
        workorders = queries.workorders(BUSINESS_DATE, stepnos=[70])
        kanban = queries.kanban_stats(BUSINESS_DATE, stepnos=["70"])
        return (
            stream.metadata["snapshot_version"],
            stream.data["data"]["total_qty"],
            workorders.data["items"][0]["total_qty"],
            kanban.data["total_production"],
        )

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(load_user_page, range(50)))

    assert len(results) == 50
    assert set(results) == {("concurrency-v1", 100, 100, 100)}
