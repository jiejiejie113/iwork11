import pandas as pd
import numpy as np
from datetime import datetime
from typing import Tuple
import os

# ==================== 全局配置 ====================
# 输入文件路径配置
DETAIL_FILE_PATH = (
    r"D:\DM\Python代码\Seamus\iwork\EST_L5C_260323明细表.csv"  # 明细表文件路径
)
ACTUAL_FILE_PATH = r"D:\DM\Python代码\Seamus\iwork\实际表.csv"  # 实际表文件路径

# 输出目录配置
OUTPUT_DIR = r"D:\DM\Python代码\Seamus\iwork\save"  # 输出文件保存目录
# ==================== 配置结束 ====================


def map_hour_to_time_slot(hour: int) -> str:
    """将小时映射到时间段标签"""
    if 7 <= hour <= 8:
        return "7—9"
    elif 9 <= hour <= 10:
        return "9—11"
    elif 12 <= hour <= 13:
        return "12—14"
    elif 14 <= hour <= 15:
        return "14—16"
    elif 16 <= hour <= 17:
        return "16—18"
    else:
        return None


def process_detail_data(df_detail: pd.DataFrame) -> pd.DataFrame:
    """
    处理明细表：解析时间，映射时间段，过滤，聚合

    参数:
        df_detail: 明细表DataFrame
    返回:
        聚合后的DataFrame，包含日期、流水线、工号、姓名，以及各时间段和全天总计
    """
    # 复制避免修改原数据
    df = df_detail.copy()

    # 解析时间字段，支持多种格式（如 "2026/3/23 7:03:00" 或 "2026/3/23 6:47"）
    df["时间_dt"] = pd.to_datetime(df["时间"], format="mixed")

    # 提取日期和小时
    df["日期"] = df["时间_dt"].dt.date
    df["小时"] = df["时间_dt"].dt.hour

    # 映射时间段
    df["时段"] = df["小时"].apply(map_hour_to_time_slot)

    # 过滤非工作时间段
    df = df[df["时段"].notna()].copy()

    # 获取每个工号每天对应的流水线（取第一个出现的流水线）
    # 假设同一工号每天只在一个流水线，否则取第一个
    line_mapping = df.groupby(["日期", "工号"])["流水线"].first().reset_index()

    # 聚合：按日期、工号、姓名、时段分组，计算数量总和（不按流水线分组）
    grouped = df.groupby(["日期", "工号", "姓名", "时段"], as_index=False)["数量"].sum()

    # 透视表：将时段展开为列
    pivot = grouped.pivot_table(
        index=["日期", "工号", "姓名"],
        columns="时段",
        values="数量",
        fill_value=0,
        aggfunc="sum",
    )

    # 确保所有时间段列都存在
    time_slots = ["7—9", "9—11", "12—14", "14—16", "16—18"]
    for slot in time_slots:
        if slot not in pivot.columns:
            pivot[slot] = 0

    # 计算全天总计
    pivot["合计"] = pivot[time_slots].sum(axis=1)

    # 重置索引，将日期、工号、姓名变为列
    pivot = pivot.reset_index()

    # 合并流水线信息
    pivot = pivot.merge(line_mapping, on=["日期", "工号"], how="left")

    # 重新排列列顺序，将流水线放在前面
    cols = ["日期", "流水线", "工号", "姓名"] + time_slots + ["合计"]
    pivot = pivot[cols]

    return pivot


def process_actual_data(df_actual: pd.DataFrame) -> pd.DataFrame:
    """
    处理实际表：确保列名一致，规范化时间段列名

    参数:
        df_actual: 实际表DataFrame
    返回:
        处理后的实际表DataFrame
    """
    df = df_actual.copy()

    # 去除列名两端的空格
    df.columns = df.columns.str.strip()

    # 重命名列：将可能的列名映射到标准格式
    column_mapping = {}

    # 映射ID列
    for col in df.columns:
        if col.upper() == "ID":
            column_mapping[col] = "ID"
            break

    # 映射员工工号列（可能是第二列，或者包含'工号'的列）
    if len(df.columns) >= 2:
        # 假设第二列是员工工号
        column_mapping[df.columns[1]] = "工号"

    # 映射组别列（可能是第三列）
    if len(df.columns) >= 3:
        # 假设第三列是组别
        column_mapping[df.columns[2]] = "组别"

    # 规范化时间段列名
    for col in df.columns:
        col_str = str(col).strip()
        # 移除空格和特殊字符，只保留数字和中文破折号
        normalized = col_str.replace(" ", "").replace("-", "—").replace("–", "—")
        if normalized in ["7—9", "9—11", "12—14", "14—16", "16—18", "合计"]:
            column_mapping[col] = normalized
        elif "合计" in col_str:
            column_mapping[col] = "合计"

    # 重命名列
    df = df.rename(columns=column_mapping)

    # 确保所有必要列存在，缺失的列填充0
    required_columns = ["7—9", "9—11", "12—14", "14—16", "16—18", "合计"]
    for col in required_columns:
        if col not in df.columns:
            df[col] = 0

    return df


def reconcile_data(df_detail: pd.DataFrame, df_actual: pd.DataFrame) -> pd.DataFrame:
    """
    核对明细表与实际表数据

    参数:
        df_detail: 明细表DataFrame
        df_actual: 实际表DataFrame
    返回:
        核对结果DataFrame，包含差异分析
    """
    # 处理明细表
    system_agg = process_detail_data(df_detail)

    # 处理实际表
    actual_processed = process_actual_data(df_actual)

    # 合并：左连接，基于工号
    merged = system_agg.merge(
        actual_processed[
            ["工号", "ID", "组别", "7—9", "9—11", "12—14", "14—16", "16—18", "合计"]
        ],
        on="工号",
        how="left",
        suffixes=("_系统", "_手动"),
    )

    # 填充手动数量的NaN为0
    manual_cols = [
        "7—9_手动",
        "9—11_手动",
        "12—14_手动",
        "14—16_手动",
        "16—18_手动",
        "合计_手动",
    ]
    for col in manual_cols:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    # 计算差异：系统数量 - 手动数量
    time_slots = ["7—9", "9—11", "12—14", "14—16", "16—18"]
    for slot in time_slots:
        merged[f"{slot}_差异"] = merged[f"{slot}_系统"] - merged[f"{slot}_手动"]
    merged["合计_差异"] = merged["合计_系统"] - merged["合计_手动"]

    # 将结果转换为长格式：每个时间段一行
    result_rows = []
    for _, row in merged.iterrows():
        base_info = {
            "日期": row["日期"],
            "流水线": row["流水线"],
            "工号": row["工号"],
            "姓名": row["姓名"],
            "ID": None if pd.isna(row.get("ID")) else row.get("ID"),
            "组别": None if pd.isna(row.get("组别")) else row.get("组别"),
        }
        # 添加每个时间段的行
        for slot in time_slots:
            result_rows.append(
                {
                    **base_info,
                    "时段": slot,
                    "系统数量": row[f"{slot}_系统"],
                    "手动数量": row[f"{slot}_手动"],
                    "差异值": row[f"{slot}_差异"],
                }
            )
        # 添加合计行
        result_rows.append(
            {
                **base_info,
                "时段": "合计",
                "系统数量": row["合计_系统"],
                "手动数量": row["合计_手动"],
                "差异值": row["合计_差异"],
            }
        )

    result_df = pd.DataFrame(result_rows)

    # 按日期、流水线、工号、时段排序
    result_df = result_df.sort_values(
        by=["日期", "流水线", "工号", "时段"]
    ).reset_index(drop=True)

    return result_df


def read_csv_with_encoding(file_path: str) -> pd.DataFrame:
    """
    尝试多种编码方式读取CSV文件

    参数:
        file_path: CSV文件路径
    返回:
        读取的DataFrame
    """
    # 常见的中文编码
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin1"]

    for encoding in encodings:
        try:
            df = pd.read_csv(file_path, encoding=encoding)
            print(f"成功使用 {encoding} 编码读取文件: {file_path}")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue

    # 如果所有编码都失败，抛出异常
    raise ValueError(f"无法读取文件 {file_path}，尝试了以下编码: {encodings}")


def load_data(detail_file: str, actual_file: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    加载数据，支持Excel和CSV格式

    参数:
        detail_file: 明细表文件路径
        actual_file: 实际表文件路径
    返回:
        (明细表DataFrame, 实际表DataFrame)
    """
    # 根据文件扩展名选择读取方式
    if detail_file.endswith(".xlsx") or detail_file.endswith(".xls"):
        df_detail = pd.read_excel(detail_file)
    elif detail_file.endswith(".csv"):
        df_detail = read_csv_with_encoding(detail_file)
    else:
        raise ValueError(f"不支持的明细表文件格式: {detail_file}")

    if actual_file.endswith(".xlsx") or actual_file.endswith(".xls"):
        df_actual = pd.read_excel(actual_file)
    elif actual_file.endswith(".csv"):
        df_actual = read_csv_with_encoding(actual_file)
    else:
        raise ValueError(f"不支持的实际表文件格式: {actual_file}")

    return df_detail, df_actual


def main():
    """
    主函数：使用全局配置加载数据，执行核对，输出结果到带时间戳的文件
    """
    # 使用全局配置
    detail_file = DETAIL_FILE_PATH
    actual_file = ACTUAL_FILE_PATH

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 生成带时间戳的输出文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"核对结果_{timestamp}.xlsx")

    print(f"明细表文件: {detail_file}")
    print(f"实际表文件: {actual_file}")
    print(f"输出文件: {output_file}")
    print("=" * 50)

    print("加载数据...")
    df_detail, df_actual = load_data(detail_file, actual_file)

    print("处理明细表...")
    print(f"明细表记录数: {len(df_detail)}")

    print("处理实际表...")
    print(f"实际表记录数: {len(df_actual)}")

    print("执行数据核对...")
    result = reconcile_data(df_detail, df_actual)

    print(f"核对结果记录数: {len(result)}")

    # 显示前几行结果
    print("\n核对结果预览:")
    print(result.head(20))

    # 保存结果
    if output_file.endswith(".xlsx"):
        result.to_excel(output_file, index=False)
    elif output_file.endswith(".csv"):
        result.to_csv(output_file, index=False, encoding="utf-8-sig")
    else:
        # 默认保存为Excel
        result.to_excel(output_file + ".xlsx", index=False)
    print(f"\n结果已保存到: {output_file}")

    # 统计差异
    diff_count = (result["差异值"] != 0).sum()
    total_count = len(result)
    print(
        f"\n差异统计: 有差异的记录数 {diff_count}/{total_count} ({diff_count/total_count*100:.2f}%)"
    )

    return result


if __name__ == "__main__":
    import sys

    try:
        result_df = main()
    except FileNotFoundError as e:
        print(f"文件未找到: {e}")
        print("请确保全局配置中的文件路径正确。")
        sys.exit(1)
    except Exception as e:
        print(f"发生错误: {e}")
        sys.exit(1)
