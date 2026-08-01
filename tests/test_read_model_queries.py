"""实时读模型构建与查询行为测试。"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache

from iwork.read_model.builder import build_snapshot
from iwork.read_model.queries import ReadModelQueries
from iwork.read_model.store import SnapshotStore


BUSINESS_DATE = date(2026, 7, 31)
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Asia/Bangkok"))


@pytest.fixture(autouse=True)
def clear_cache():
    """隔离读模型查询测试的缓存。"""
    cache.clear()
    yield
    cache.clear()


def _publish_snapshot() -> ReadModelQueries:
    """发布覆盖工单、详情和看板筛选的测试快照。"""
    metadata = {
        "schema_version": 1,
        "snapshot_version": "20260731-120000-000001",
        "business_date": BUSINESS_DATE.isoformat(),
        "generated_at": NOW.isoformat(),
        "source_completed_at": NOW.isoformat(),
        "source_status": "success",
        "record_count": 5,
    }
    views = {
        "realtime": {
            70: {
                "date": BUSINESS_DATE,
                "total_qty": 130,
                "workorder_count": 2,
                "hourly_stats": [{"hour": 8, "qty": 130}],
                "process_flow_stats": [{"step": 70, "flow": "A", "qty": 130}],
                "monthly_total_trend": [{"date": "2026-07-31", "qty": 130}],
                "monthly_process_stats": [
                    {"date": BUSINESS_DATE.isoformat(), "step": 70, "qty": 130},
                ],
                "monthly_hourly_stats": [],
                "station_ranking": [{"station": "(A)[S1]", "qty": 130}],
                "station_stats": [{"station": "(A)[S1]", "qty": 130}],
                "top_processes": [{"step": 70, "qty": 130}],
                "workorders": [],
                "all_stepnos": [70, 69],
                "heatmap_matrix": {"hours": [], "flows": [], "data": []},
            },
            69: {
                "date": BUSINESS_DATE,
                "total_qty": 20,
                "workorder_count": 1,
                "hourly_stats": [{"hour": 8, "qty": 20}],
                "process_flow_stats": [{"step": 69, "flow": "B", "qty": 20}],
                "monthly_total_trend": [{"date": "2026-07-31", "qty": 20}],
                "monthly_process_stats": [
                    {"date": BUSINESS_DATE.isoformat(), "step": 69, "qty": 20},
                ],
                "monthly_hourly_stats": [],
                "station_ranking": [{"station": "(B)[S2]", "qty": 20}],
                "station_stats": [{"station": "(B)[S2]", "qty": 20}],
                "top_processes": [{"step": 69, "qty": 20}],
                "workorders": [],
                "all_stepnos": [70, 69],
                "heatmap_matrix": {"hours": [], "flows": [], "data": []},
            },
            "all": {"date": BUSINESS_DATE, "total_qty": 150},
        },
        "processes": [70, 69],
        "workorders": {
            "rows": [
                {
                    "wrk_order": "WO-B",
                    "stepno": 70,
                    "total_qty": 80,
                    "employee_ids": [1, 2],
                    "flows": ["SO3-L3A"],
                },
                {
                    "wrk_order": "WO-A",
                    "stepno": 70,
                    "total_qty": 50,
                    "employee_ids": [1],
                    "flows": ["SO3-L3A"],
                },
                {
                    "wrk_order": "WO-A",
                    "stepno": 69,
                    "total_qty": 20,
                    "employee_ids": [3],
                    "flows": ["B"],
                },
                {
                    "wrk_order": "WO-HIDDEN",
                    "stepno": 70,
                    "total_qty": 999,
                    "employee_ids": [9],
                    "flows": ["SO2-L2A"],
                },
            ],
            "products": {
                "WO-A": {"product_name": "产品甲", "order_no": "ORDER-1"},
                "WO-B": {"product_name": "产品乙", "order_no": "ORDER-2"},
            },
        },
        "workorder_details": {
            "WO-A": {
                "wrk_order": "WO-A",
                "total_qty": 70,
                "steps": [
                    {"StepNo": 69, "qty": 20, "count": 1},
                    {"StepNo": 70, "qty": 50, "count": 1},
                ],
            }
        },
        "detail": {
            "flow_overview": {"A": {"total_qty": 130, "worker_count": 2}},
            "flow_hourly": {"A": [{"hour": 8, "qty": 130}]},
            "flow_employees": {"A": [{"reg_per_sys_id": 1, "total_qty": 130}]},
            "stepno_employees": {70: [{"reg_per_sys_id": 1, "qty": 130}]},
            "product_overview": {"products": []},
        },
        "kanban": [
            {"reg_per_sys_id": 1, "stepno": 70, "wrk_order": "WO-A", "flow": "A", "qty": 50, "record_count": 1},
            {"reg_per_sys_id": 1, "stepno": 70, "wrk_order": "WO-B", "flow": "A", "qty": 30, "record_count": 1},
            {"reg_per_sys_id": 2, "stepno": 70, "wrk_order": "WO-B", "flow": "A", "qty": 50, "record_count": 1},
            {"reg_per_sys_id": 3, "stepno": 69, "wrk_order": "WO-A", "flow": "B", "qty": 20, "record_count": 1},
            {"reg_per_sys_id": 9, "stepno": 70, "wrk_order": "WO-HIDDEN", "flow": "SO2-L2A", "qty": 999, "record_count": 1},
        ],
    }
    store = SnapshotStore(cache_backend=cache, now=lambda: NOW)
    store.publish({"metadata": metadata, "views": views})
    return ReadModelQueries(store=store)


def test_builder_creates_all_views_from_one_business_date(monkeypatch):
    """构建器必须把实时、详情和最低粒度事实装入同一版本。"""
    monkeypatch.setattr(
        "iwork.read_model.builder.get_batch_stats",
        lambda q, target_date: {70: {"date": target_date}, "all": {"date": target_date}},
    )
    monkeypatch.setattr(
        "iwork.read_model.builder.get_batch_detail_stats",
        lambda q, target_date: {"flow_overview": {}, "flow_hourly": {}, "flow_employees": {}, "stepno_employees": {}, "product_overview": {}},
    )
    source = SimpleNamespace(
        get_read_model_facts=lambda target_date: {
            "facts": [{
                "reg_per_sys_id": 1,
                "stepno": 70,
                "wrk_order": "WO-A",
                "flow": "A",
                "qty": 5,
                "record_count": 2,
            }],
            "products": {"WO-A": {"product_name": "产品甲", "order_no": "ORDER-1"}},
        }
    )

    snapshot = build_snapshot(BUSINESS_DATE, source=source, now=lambda: NOW)

    assert set(snapshot["views"]) == {
        "realtime", "processes", "workorders", "workorder_details", "detail", "kanban"
    }
    assert snapshot["metadata"]["business_date"] == BUSINESS_DATE.isoformat()
    assert snapshot["metadata"]["record_count"] == 2
    assert snapshot["views"]["workorder_details"]["WO-A"]["total_qty"] == 5


def test_realtime_multiple_stepnos_are_merged_without_database_fallback():
    """多工序筛选从同一快照合并，且总量与小时趋势一致。"""
    queries = _publish_snapshot()

    result = queries.realtime(BUSINESS_DATE, [70, 69])

    assert result.data["total_qty"] == 150
    assert result.data["hourly_stats"] == [{"hour": 8, "qty": 150}]
    assert result.data["monthly_total_trend"] == [{"date": "2026-07-31", "qty": 150}]


def test_workorders_use_stable_sort_and_pagination():
    """工单按产量降序、工单号升序稳定分页。"""
    queries = _publish_snapshot()

    result = queries.workorders(BUSINESS_DATE, page=1, page_size=1, stepnos=[70])

    assert result.data["items"][0]["wrk_order"] == "WO-B"
    assert result.data["total"] == 2
    assert result.data["total_pages"] == 2
    assert result.data["items"][0]["worker_count"] == 2


def test_unfiltered_workorders_retain_complete_flow_facts():
    """未选择工序时，工单列表应保留完整事实而不是提前套用白名单。"""
    queries = _publish_snapshot()

    result = queries.workorders(BUSINESS_DATE, page=1, page_size=20)

    assert result.data["items"][0]["wrk_order"] == "WO-HIDDEN"


def test_kanban_show_all_flows_can_restore_hidden_facts():
    """Kanban 的显示全部开关必须能读取快照中保留的隐藏 Flow。"""
    queries = _publish_snapshot()

    default_result = queries.kanban_stats(BUSINESS_DATE)
    show_all_result = queries.kanban_stats(BUSINESS_DATE, show_all_flows=True)

    assert default_result.data["total_production"] == 150
    assert show_all_result.data["total_production"] == 1149


def test_fact_collection_does_not_apply_realtime_flow_whitelist(monkeypatch):
    """最低粒度事实必须完整采集，Flow 过滤只能在具体查询语义中执行。"""
    from iwork import queries

    records = MagicMock()
    records.values.return_value.annotate.return_value.order_by.return_value = []
    monkeypatch.setattr(queries, "get_records_queryset", lambda _date: records)
    monkeypatch.setattr(
        queries,
        "apply_batch_flow_filter",
        lambda _records: (_ for _ in ()).throw(AssertionError("不应提前过滤")),
    )

    assert queries.get_read_model_facts(BUSINESS_DATE) == {
        "facts": [],
        "products": {},
    }


def test_kanban_stats_and_ranking_share_the_same_filtered_facts():
    """看板统计与排行必须基于同一筛选事实并得到一致总量。"""
    queries = _publish_snapshot()

    stats = queries.kanban_stats(BUSINESS_DATE, stepnos=["70"], wrk_orders=["WO-B"])
    ranking = queries.kanban_ranking(
        BUSINESS_DATE,
        stepnos=["70"],
        wrk_orders=["WO-B"],
        page=1,
        page_size=50,
    )

    assert stats.data["total_production"] == 80
    assert sum(worker["production"] for worker in ranking.data["workers"]) == 80
    assert ranking.data["workers"][0]["reg_per_sys_id"] == 2
