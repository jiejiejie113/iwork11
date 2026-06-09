import pandas as pd
import numpy as np
from data_reconciliation import reconcile_data, process_detail_data, process_actual_data


def create_sample_detail_data():
    """创建示例明细表数据"""
    data = {
        "日期": ["2026/3/23"] * 10,
        "时间": [
            "2026/3/23 7:03:00",
            "2026/3/23 7:15:00",
            "2026/3/23 8:30:00",
            "2026/3/23 9:05:00",
            "2026/3/23 9:45:00",
            "2026/3/23 10:20:00",
            "2026/3/23 12:10:00",
            "2026/3/23 13:30:00",
            "2026/3/23 14:05:00",
            "2026/3/23 15:50:00",
        ],
        "流水线": ["A线"] * 5 + ["B线"] * 5,
        "生产单": ["PO001"] * 10,
        "款号": ["ST001"] * 10,
        "初版款号": ["ST001"] * 10,
        "面料类型": ["棉"] * 10,
        "颜色": ["红"] * 10,
        "尺码": ["M"] * 10,
        "工号": [
            "E001",
            "E001",
            "E001",
            "E002",
            "E002",
            "E002",
            "E001",
            "E001",
            "E002",
            "E002",
        ],
        "姓名": [
            "张三",
            "张三",
            "张三",
            "李四",
            "李四",
            "李四",
            "张三",
            "张三",
            "李四",
            "李四",
        ],
        "工序号": ["OP01"] * 10,
        "工序名称": ["缝纫"] * 10,
        "标准工时": [0.5] * 10,
        "机器类型": ["平车"] * 10,
        "工价系数": [1.0] * 10,
        "数量": [10, 15, 20, 12, 18, 8, 25, 30, 22, 16],
        "耗时": [0.5] * 10,
    }
    return pd.DataFrame(data)


def create_sample_actual_data():
    """创建示例实际表数据"""
    data = {
        "ID": [1, 2],
        "员工工号": ["E001", "E002"],
        "组别": ["一组", "二组"],
        "7—9": [45, 0],  # E001在7-9时段手动登记45，E002没有记录
        "9—11": [0, 38],  # E001在9-11时段手动登记0，E002手动登记38
        "12—14": [55, 0],  # E001在12-14时段手动登记55，E002没有记录
        "14—16": [0, 38],  # E001在14-16时段手动登记0，E002手动登记38
        "16—18": [0, 0],
        "合计": [100, 76],
    }
    return pd.DataFrame(data)


def test_process_detail_data():
    """测试明细表处理函数"""
    print("测试明细表处理...")
    df_detail = create_sample_detail_data()
    print("原始明细表:")
    print(df_detail[["日期", "时间", "工号", "姓名", "数量"]].head())

    # 处理明细表
    system_agg = process_detail_data(df_detail)
    print("\n聚合后的系统数据:")
    print(system_agg)
    return system_agg


def test_process_actual_data():
    """测试实际表处理函数"""
    print("\n测试实际表处理...")
    df_actual = create_sample_actual_data()
    print("原始实际表:")
    print(df_actual)

    # 处理实际表
    actual_processed = process_actual_data(df_actual)
    print("\n处理后的实际表:")
    print(actual_processed)
    return actual_processed


def test_reconcile_data():
    """测试完整的核对流程"""
    print("\n测试完整核对流程...")
    df_detail = create_sample_detail_data()
    df_actual = create_sample_actual_data()

    print("明细表数据:")
    print(df_detail[["日期", "时间", "流水线", "工号", "姓名", "数量"]])

    print("\n实际表数据:")
    print(df_actual)

    # 执行核对
    result = reconcile_data(df_detail, df_actual)

    print("\n核对结果:")
    print(result)

    # 分析差异
    print("\n差异分析:")
    diff_records = result[result["差异值"] != 0]
    if len(diff_records) > 0:
        print("存在差异的记录:")
        print(
            diff_records[
                [
                    "日期",
                    "流水线",
                    "工号",
                    "姓名",
                    "时段",
                    "系统数量",
                    "手动数量",
                    "差异值",
                ]
            ]
        )
    else:
        print("所有记录均无差异。")

    return result


if __name__ == "__main__":
    print("=" * 50)
    print("数据核对脚本测试")
    print("=" * 50)

    # 测试各个函数
    test_process_detail_data()
    test_process_actual_data()

    # 测试完整流程
    result = test_reconcile_data()

    print("\n测试完成。")
