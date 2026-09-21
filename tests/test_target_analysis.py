"""今日目标分析统计与目标拆分行为测试。"""

from decimal import Decimal

from iwork.target_analysis import (
    aggregate_target_analysis,
    build_period_analysis,
    get_period_metadata,
)


def test_aggregate_target_analysis_uses_step_70_and_exact_time_windows():
    """只统计70号工序，并按三个左闭右开时段正确归集产量。"""
    facts = [
        {"stepno": 69, "flow": "Sewing-A1", "event_hour": 8, "qty": 999},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 6, "qty": 1},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 7, "qty": 10},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 10, "qty": 11},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 11, "qty": 100},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 12, "qty": 20},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 15, "qty": 21},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 16, "qty": 30},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 17, "qty": 31},
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 18, "qty": 1000},
        {"stepno": 70, "flow": "Sewing-A2", "event_hour": 8, "qty": 7},
    ]

    result = aggregate_target_analysis(facts)

    assert result["Sewing-A1"] == {
        "morning": 21,
        "afternoon": 41,
        "night": 61,
    }
    assert result["Sewing-A2"] == {
        "morning": 7,
        "afternoon": 0,
        "night": 0,
    }


def test_aggregate_target_analysis_respects_allowed_flows():
    """传入白名单时只保留白名单内的分组。"""
    facts = [
        {"stepno": 70, "flow": "Sewing-A1", "event_hour": 8, "qty": 3},
        {"stepno": 70, "flow": "Sewing-B3", "event_hour": 8, "qty": 5},
    ]

    result = aggregate_target_analysis(facts, allowed_flows=["Sewing-A1"])

    assert result == {"Sewing-A1": {"morning": 3, "afternoon": 0, "night": 0}}


def test_get_period_metadata_uses_myanmar_workday_windows():
    """分析时段按缅甸工厂作息输出早上、下午、晚上三段。"""
    metadata = get_period_metadata()

    assert [item["key"] for item in metadata] == ["morning", "afternoon", "night"]
    assert [item["time_range"] for item in metadata] == [
        "07:30-11:30",
        "12:00-16:00",
        "16:30-18:30",
    ]


def test_build_period_analysis_splits_ten_and_eight_hours_and_excludes_overtime_target():
    """10小时按4/4/2拆分，8小时按4/4拆分，超出正常工时不再分配目标。"""
    actuals = {"morning": 40, "afternoon": 30, "night": 12}

    ten_hour = build_period_analysis(
        actuals,
        target_qty=100,
        planned_work_minutes=600,
    )
    eight_hour = build_period_analysis(
        actuals,
        target_qty=100,
        planned_work_minutes=480,
    )
    twelve_hour = build_period_analysis(
        actuals,
        target_qty=100,
        planned_work_minutes=720,
    )

    assert ten_hour == [
        {
            "key": "morning",
            "label": "早上",
            "time_range": "07:30-11:30",
            "actual_qty": 40,
            "target_qty": 40.0,
            "achievement_rate": 100.0,
        },
        {
            "key": "afternoon",
            "label": "下午",
            "time_range": "12:00-16:00",
            "actual_qty": 30,
            "target_qty": 40.0,
            "achievement_rate": 75.0,
        },
        {
            "key": "night",
            "label": "晚上",
            "time_range": "16:30-18:30",
            "actual_qty": 12,
            "target_qty": 20.0,
            "achievement_rate": 60.0,
        },
    ]
    assert eight_hour[0]["target_qty"] == 50.0
    assert eight_hour[1]["target_qty"] == 50.0
    assert eight_hour[0]["achievement_rate"] == 80.0
    assert eight_hour[1]["achievement_rate"] == 60.0
    assert eight_hour[2]["target_qty"] is None
    assert [item["target_qty"] for item in twelve_hour] == [40.0, 40.0, 20.0]
    assert twelve_hour[2]["actual_qty"] == 12


def test_build_period_analysis_does_not_calculate_unsubmitted_or_zero_target():
    """缺少目标/工时或目标为0时，实际照常返回但达成率保持为空。"""
    actuals = {"morning": 4, "afternoon": 5, "night": 6}

    missing_target = build_period_analysis(
        actuals,
        target_qty=None,
        planned_work_minutes=600,
    )
    missing_work_hours = build_period_analysis(
        actuals,
        target_qty=100,
        planned_work_minutes=None,
    )
    zero_target = build_period_analysis(
        actuals,
        target_qty=0,
        planned_work_minutes=600,
    )

    for result in (missing_target, missing_work_hours, zero_target):
        assert [item["actual_qty"] for item in result] == [4, 5, 6]
        assert all(item["target_qty"] is None for item in result)
        assert all(item["achievement_rate"] is None for item in result)


def test_build_period_analysis_uses_decimal_safe_rounding():
    """非整除目标应稳定保留两位目标和一位百分比。"""
    result = build_period_analysis(
        {"morning": 1, "afternoon": 2, "night": 0},
        target_qty=101,
        planned_work_minutes=480,
    )

    assert result[0]["target_qty"] == float(Decimal("50.5"))
    assert result[0]["achievement_rate"] == 2.0
