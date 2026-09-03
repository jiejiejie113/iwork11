"""生产详情员工 ID 映射行为测试。"""


def test_unique_nonblank_remark_values_are_used_as_employee_ids():
    """空 Remark、重复 Remark 被排除，唯一 Remark 去空白后保留。"""
    from iwork.employee_id_mapping import build_unique_remark_map

    rows = [
        {"SysID": 1001, "Remark": "  EMP-A  "},
        {"SysID": 1002, "Remark": "EMP-A"},
        {"SysID": 1003, "Remark": "   "},
        {"SysID": 1004, "Remark": None},
        {"SysID": 1005, "Remark": "EMP-B"},
    ]

    assert build_unique_remark_map(rows) == {"1005": "EMP-B"}


def test_group_target_allocation_supports_text_remark_ids():
    """Remark 为字母文本时，整组目标仍能稳定分配员工目标。"""
    from iwork.api_views import _allocate_step_target

    allocations = _allocate_step_target(
        {"70": {"EMP-2", "EMP-1"}},
        3,
    )

    assert allocations == {"70": {"EMP-1": 2, "EMP-2": 1}}
