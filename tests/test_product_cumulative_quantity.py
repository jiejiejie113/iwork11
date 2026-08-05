"""产品概览累计产量测试。"""

from datetime import date


# ======
# 测试业务日期配置
BUSINESS_DATE = date(2026, 8, 4)


def test_product_overview_aggregates_full_cumulative_quantity():
    """产品树应汇总完整累计事实，并保留今日无产量的历史工序。"""
    from iwork.read_model.fact_source import ReadModelFactSource

    source = ReadModelFactSource(
        business_date=BUSINESS_DATE,
        facts=[
            {
                "reg_per_sys_id": 1001,
                "stepno": 70,
                "wrk_order": "BU1211",
                "flow": "SO3-L3B",
                "qty": 10,
            },
            {
                "reg_per_sys_id": 1002,
                "stepno": 70,
                "wrk_order": "BU1211",
                "flow": "SO3-L3B",
                "qty": 5,
            },
        ],
        cumulative_facts=[
            {
                "reg_per_sys_id": 1001,
                "stepno": 70,
                "wrk_order": "BU1211",
                "flow": "SO3-L3B",
                "cumulative_qty": 100,
            },
            {
                "reg_per_sys_id": 1002,
                "stepno": 70,
                "wrk_order": "BU1211",
                "flow": "SO3-L3B",
                "cumulative_qty": 50,
            },
            {
                "reg_per_sys_id": 1003,
                "stepno": 69,
                "wrk_order": "BU1211",
                "flow": "SO3-L3A",
                "cumulative_qty": 30,
            },
            {
                "reg_per_sys_id": 1004,
                "stepno": 70,
                "wrk_order": "BU1211",
                "flow": "NOT-ALLOWED",
                "cumulative_qty": 999,
            },
        ],
        products={
            "BU1211": {"product_name": "产品甲", "order_no": "ORDER-1"},
        },
    )

    product = source.get_batch_product_overview(BUSINESS_DATE)["products"][0]
    workorder = product["wrk_orders"][0]
    steps = {item["stepno"]: item for item in workorder["stepnos"]}

    assert product["total_qty"] == 15
    assert product["cumulative_qty"] == 1179
    assert workorder["cumulative_qty"] == 1179
    assert steps[70]["cumulative_qty"] == 1149
    assert steps[70]["flows"][0]["cumulative_qty"] == 150
    assert steps[70]["flows"][1]["flow"] == "NOT-ALLOWED"
    assert steps[70]["flows"][1]["cumulative_qty"] == 999
    assert steps[69]["qty"] == 0
    assert steps[69]["cumulative_qty"] == 30
