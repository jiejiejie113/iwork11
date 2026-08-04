"""单次基础事实采集生成实时读模型的行为测试。"""

from contextlib import contextmanager, nullcontext
from datetime import date, datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.core.cache import cache

from iwork.read_model.builder import build_snapshot


BUSINESS_DATE = date(2026, 8, 3)
NOW = datetime(2026, 8, 3, 11, 0, tzinfo=ZoneInfo("Asia/Bangkok"))


def test_one_fact_set_builds_consistent_realtime_detail_and_kanban():
    """同一批事实必须同时生成一致的实时、详情和看板视图。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    cache.clear()
    source = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[
            {
                "reg_per_sys_id": 1001,
                "stepno": 70,
                "wrk_order": "ABC123-01",
                "flow": "SO3-L3A",
                "station_id": "A01",
                "event_hour": 8,
                "qty": 60,
                "record_count": 2,
            },
            {
                "reg_per_sys_id": 1002,
                "stepno": 70,
                "wrk_order": "ABC123-01",
                "flow": "SO3-L3A",
                "station_id": "A02",
                "event_hour": 9,
                "qty": 40,
                "record_count": 1,
            },
            {
                "reg_per_sys_id": 1003,
                "stepno": 70,
                "wrk_order": "HIDDEN-01",
                "flow": "SO2-L2A",
                "station_id": "B01",
                "event_hour": 9,
                "qty": 999,
                "record_count": 1,
            },
        ],
        products={
            "ABC123-01": {"product_name": "产品甲", "order_no": "ORDER-1"},
        },
        step_metadata={
            ("ABC123-01", 70): {"description": "车缝", "step_time": 0.5},
        },
    )

    snapshot = build_snapshot(BUSINESS_DATE, source=source, now=lambda: NOW)

    realtime = snapshot["views"]["realtime"][70]
    assert realtime["total_qty"] == 100
    assert realtime["monthly_total_trend"] == [
        {"date": BUSINESS_DATE.isoformat(), "qty": 100},
    ]
    assert realtime["monthly_process_stats"] == [
        {"date": BUSINESS_DATE.isoformat(), "step": 70, "qty": 100},
    ]
    assert snapshot["views"]["detail"]["flow_overview"]["SO3-L3A"] == {
        "stepnos": {"70": {"qty": 100, "workers": 2}},
        "total_workers": 2,
    }
    assert snapshot["views"]["detail"]["product_overview"]["products"][0][
        "total_qty"
    ] == 100
    assert sum(item["qty"] for item in snapshot["views"]["kanban"]) == 1099
    assert snapshot["metadata"]["record_count"] == 4


def test_flow_detail_uses_same_snapshot_cumulative_quantity():
    """Flow 当日产量和从工单创建日起的累计产量应来自同一事实源。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    source = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[{
            "reg_per_sys_id": 1001,
            "stepno": 70,
            "wrk_order": "BU1211",
            "flow": "SO3-L3B",
            "qty": 80,
            "record_count": 2,
        }],
        cumulative_facts=[{
            "reg_per_sys_id": 1001,
            "stepno": 70,
            "wrk_order": "BU1211",
            "flow": "SO3-L3B",
            "cumulative_qty": 23152,
        }],
    )

    snapshot = build_snapshot(BUSINESS_DATE, source=source, now=lambda: NOW)
    employee = snapshot["views"]["detail"]["flow_employees"]["SO3-L3B"][0]

    assert employee["total_qty"] == 80
    assert employee["cumulative_qty"] == 23152
    assert employee["steps"][0]["cumulative_qty"] == 23152


def test_collector_loads_cumulative_rows_inside_consistent_snapshot():
    """当天事实和累计事实必须在同一远程一致性快照内采集。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    state = {"active": False}
    remote = Mock()

    @contextmanager
    def consistent_snapshot():
        state["active"] = True
        try:
            yield
        finally:
            state["active"] = False

    def checked(value):
        def query(*_args):
            assert state["active"] is True
            return value

        return query

    remote.read_model_consistent_snapshot.side_effect = consistent_snapshot
    remote.get_read_model_fact_rows.side_effect = checked([{
        "reg_per_sys_id": 1001,
        "stepno": 70,
        "wrk_order": "BU1211",
        "flow": "SO3-L3B",
        "qty": 80,
        "record_count": 2,
    }])
    remote.get_igarment_creation_dates.return_value = {
        "BU1211": date(2026, 6, 10),
    }
    remote.get_read_model_cumulative_rows.side_effect = checked([{
        "reg_per_sys_id": 1001,
        "stepno": 70,
        "wrk_order": "BU1211",
        "flow": "SO3-L3B",
        "cumulative_qty": 23152,
    }])
    remote.get_read_model_products.return_value = {}
    remote.get_batch_step_metadata.side_effect = checked({})

    source = ReadModelFactSource.collect(BUSINESS_DATE, source=remote)

    assert source.cumulative_qty[("SO3-L3B", 1001, 70, "BU1211")] == 23152
    remote.get_igarment_creation_dates.assert_called_once_with(["BU1211"])
    remote.get_read_model_cumulative_rows.assert_called_once_with({
        "BU1211": date(2026, 6, 10),
    })


@patch("iwork.read_model.builder.ReadModelFactSource.collect")
def test_default_builder_collects_one_remote_fact_set(mock_collect):
    """默认构建入口必须只收集一次远程基础事实。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    cache.clear()
    mock_collect.return_value = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[],
    )

    snapshot = build_snapshot(BUSINESS_DATE, now=lambda: NOW)

    mock_collect.assert_called_once_with(BUSINESS_DATE)
    assert snapshot["metadata"]["record_count"] == 0


def test_collector_uses_remote_history_only_before_business_date():
    """月历史可远程读取，但今天必须只使用本轮基础事实。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    cache.clear()
    remote = Mock()
    remote.get_read_model_fact_rows.return_value = [{
        "reg_per_sys_id": 1001,
        "stepno": 70,
        "wrk_order": "ABC123-01",
        "flow": "SO3-L3A",
        "station_id": "A01",
        "event_hour": 8,
        "qty": 100,
        "record_count": 1,
    }]
    remote.get_read_model_products.return_value = {}
    remote.get_batch_step_metadata.return_value = {}
    remote.read_model_consistent_snapshot.side_effect = nullcontext
    remote.get_igarment_creation_dates.return_value = {}
    remote.get_read_model_cumulative_rows.return_value = []
    remote.get_batch_monthly_total_trend.return_value = {
        70: [{"date": "2026-08-02", "qty": 80}],
    }
    remote.get_batch_monthly_process_stats.return_value = {
        70: [{"date": "2026-08-02", "step": 70, "qty": 80}],
    }
    remote.get_batch_monthly_hourly_stats.return_value = {
        70: [{"date": "2026-08-02", "hour": 8, "qty": 80}],
    }

    source = ReadModelFactSource.collect(BUSINESS_DATE, source=remote)
    snapshot = build_snapshot(BUSINESS_DATE, source=source, now=lambda: NOW)

    trend = snapshot["views"]["realtime"][70]["monthly_total_trend"]
    assert trend == [
        {"date": "2026-08-02", "qty": 80},
        {"date": "2026-08-03", "qty": 100},
    ]
    remote.get_read_model_fact_rows.assert_called_once_with(BUSINESS_DATE)
    remote.get_batch_monthly_total_trend.assert_called_once_with(
        date(2026, 8, 1),
        date(2026, 8, 2),
    )
    remote.get_batch_monthly_process_stats.assert_called_once_with(
        date(2026, 8, 1),
        date(2026, 8, 2),
    )
    remote.get_batch_monthly_hourly_stats.assert_called_once_with(
        date(2026, 8, 1),
        date(2026, 8, 2),
    )


def test_product_overview_merges_same_name_and_keeps_unclassified_last():
    """同名产品继续合并，未分类产品保持在列表末尾。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    source = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[
            {
                "reg_per_sys_id": 1,
                "stepno": 70,
                "wrk_order": "AAA111-01",
                "flow": "SO3-L3A",
                "qty": 10,
            },
            {
                "reg_per_sys_id": 2,
                "stepno": 70,
                "wrk_order": "BBB222-01",
                "flow": "SO3-L3A",
                "qty": 20,
            },
            {
                "reg_per_sys_id": 3,
                "stepno": 70,
                "wrk_order": "UNKNOWN-01",
                "flow": "SO3-L3A",
                "qty": 999,
            },
        ],
        products={
            "AAA111-01": {"product_name": "同名产品", "order_no": "ORDER-A"},
            "BBB222-01": {"product_name": "同名产品", "order_no": "ORDER-B"},
        },
    )

    products = source.get_batch_product_overview(BUSINESS_DATE)["products"]

    assert [item["product_name"] for item in products] == ["同名产品", "未分类"]
    assert products[0]["wrk_order_count"] == 2
    assert products[0]["total_qty"] == 30


def test_fact_counts_preserve_sql_null_semantics():
    """空员工和空工单不得被 DISTINCT 计数当成真实值。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    source = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[
            {
                "reg_per_sys_id": None,
                "stepno": 70,
                "wrk_order": "ABC123-01",
                "flow": "SO3-L3A",
                "qty": 10,
            },
            {
                "reg_per_sys_id": 1001,
                "stepno": 70,
                "wrk_order": "ABC123-01",
                "flow": "SO3-L3A",
                "qty": 5,
            },
            {
                "reg_per_sys_id": 1002,
                "stepno": 69,
                "wrk_order": None,
                "flow": "OTHER",
                "qty": 3,
            },
        ],
    )

    basic = source.get_batch_basic_stats(BUSINESS_DATE)
    overview = source.get_batch_flow_overview(BUSINESS_DATE)

    assert basic[69]["workorder_count"] == 0
    assert overview["SO3-L3A"]["stepnos"]["70"]["workers"] == 1
    assert overview["SO3-L3A"]["total_workers"] == 1


def test_realtime_workorders_keep_products_and_current_step_flows():
    """SSE 内嵌工单必须保留产品字段，且不能混入其他工序的 Flow。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    cache.clear()
    source = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[
            {
                "reg_per_sys_id": 1001,
                "stepno": 70,
                "wrk_order": "ABC123-01",
                "flow": "SO3-L3A",
                "station_id": "A01",
                "event_hour": 8,
                "qty": 60,
                "record_count": 1,
            },
            {
                "reg_per_sys_id": 1002,
                "stepno": 69,
                "wrk_order": "ABC123-01",
                "flow": "OTHER-STEP-FLOW",
                "station_id": "B01",
                "event_hour": 8,
                "qty": 40,
                "record_count": 1,
            },
        ],
        products={
            "ABC123-01": {"product_name": "产品甲", "order_no": "ORDER-1"},
        },
    )

    snapshot = build_snapshot(BUSINESS_DATE, source=source, now=lambda: NOW)
    workorder = snapshot["views"]["realtime"][70]["workorders"][0]

    assert workorder == {
        "wrk_order": "ABC123-01",
        "total_qty": 60,
        "flows": ["SO3-L3A"],
        "product_name": "产品甲",
        "order_no": "ORDER-1",
    }

    all_workorder = snapshot["views"]["realtime"]["all"]["workorders"][0]
    assert all_workorder == {
        "wrk_order": "ABC123-01",
        "total_qty": 100,
        "flows": ["OTHER-STEP-FLOW", "SO3-L3A"],
        "product_name": "产品甲",
        "order_no": "ORDER-1",
    }
