"""
导出 pytckreg3 表数据到 CSV

表信息：
- 总行数: ~3900万条
- RegDate 有索引: PYTCKREG3_RegDate (可高效查询)

字段说明：
- RegDate: 登记日期（格式: 21/4/2026 00:00:00）
- RegTime: 登记时间（格式: 30/12/1899 16:25:53）

运行模式：
- export_date: 按 TARGET_DATE 导出单日全部数据
  输出: scripts/output/pytckreg3_20260421_143052.csv
- export_month: 按 TARGET_MONTH 导出数据（月份→整月合并单文件；日期→单日），
  仅保留 StepNo 在 STEPNO_FILTER 中的记录
  输出: scripts/output/pytckreg3_202602_step70_20260508_140539.csv
"""

import calendar
import csv
from datetime import date, datetime
from pathlib import Path

import pymysql
from pymysql.cursors import SSCursor
from loguru import logger

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)

# ============== 可编辑参数 ==============
OUTPUT_DIR = Path(__file__).parent / "output"

# ---- 运行模式 ----
MODE = "export_date"            # "export_date" = 按日期导出 | "export_month" = 按月份导出

# ---- export_date 模式参数 ----
TARGET_DATE = "2026-05-21"      # None = 今日，或 格式"2026-04-21" 

# ---- export_month 模式参数 ----
TARGET_MONTH = "2026-04"        # 支持月份 "2026-02" 或具体日期 "2026-02-20"，自动识别
STEPNO_FILTER = [70]            # StepNo 筛选值列表，如 [69] 或 [69, 70]

# ---- 数据库连接参数 ----
CONNECT_TIMEOUT = 10        # 连接超时（秒）
READ_TIMEOUT = 300          # 读取超时（秒）
CHUNK_SIZE = 10000          # 进度显示间隔
# IWORK_DB_HOST = "192.168.3.15"  # VCO
IWORK_DB_HOST = "192.168.4.19"  # EST
# ========================================


def get_db_config() -> dict:
    env_path = Path(__file__).parent.parent / "iwork" / ".env"
    config = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()

    return {
        "host": IWORK_DB_HOST,
        "port": int(config["IWORK_DB_PORT"]),
        "user": config["IWORK_DB_USER"],
        "password": config["IWORK_DB_PASSWORD"],
        "database": config["IWORK_DB_NAME"],
        "charset": "utf8mb4",
        "connect_timeout": CONNECT_TIMEOUT,
        "read_timeout": READ_TIMEOUT,
    }


def export_to_csv(
    target_date: date,
    output_dir: Path,
    stepno_filter: list[int] | None = None,
    file_prefix: str = "pytckreg3",
) -> int:
    """
    导出数据到 CSV

    Args:
        target_date: 目标日期
        output_dir: 输出目录
        stepno_filter: StepNo 筛选值列表，None 表示不过滤
        file_prefix: 输出文件名前缀

    Returns:
        int: 导出的记录数
    """
    config = get_db_config()
    filter_info = f" | StepNo in {stepno_filter}" if stepno_filter else ""
    logger.info(f"连接: {config['host']}/{config['database']} | 日期: {target_date}{filter_info}")

    try:
        conn = pymysql.connect(**config, cursorclass=SSCursor)
    except pymysql.Error as e:
        logger.error(f"连接失败: {e}")
        return 0

    try:
        with conn.cursor() as cursor:
            # 构建 SQL
            sql = """
                SELECT TicketNo, SeqNo, WrkOrder, BundleNo, StepNo, Qty,
                       RegPerSysID, RegDate, RegTime, RFID, Flow, PO,
                       TimeCost, SysSource, AccBundleNo, MtrType, Color, Sizx,
                       SerialNum, StationID
                FROM pytckreg3
                WHERE RegDate >= %s AND RegDate < %s + INTERVAL 1 DAY
            """
            params: list = [target_date, target_date]

            if stepno_filter:
                placeholders = ",".join(["%s"] * len(stepno_filter))
                sql += f" AND StepNo IN ({placeholders})"
                params.extend(stepno_filter)

            cursor.execute(sql, params)

            columns = [d[0] for d in cursor.description]

            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"{file_prefix}_{timestamp}.csv"

            count = 0
            with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for row in cursor:
                    writer.writerow(row)
                    count += 1
                    if count % CHUNK_SIZE == 0:
                        logger.info(f"已写入 {count} 条")

            logger.success(f"导出完成: {output_file} ({count} 条)")
            return count

    except pymysql.Error as e:
        logger.error(f"查询失败: {e}")
        return 0
    finally:
        conn.close()


def export_month_to_csv(target_month: str, stepno_filter: list[int], output_dir: Path) -> int:
    """
    导出数据（自动识别月份或日期），仅保留 StepNo 在筛选列表中的记录

    - "YYYY-MM"（如 "2026-02"）：导出整月，合并为单个 CSV 文件
    - "YYYY-MM-DD"（如 "2026-02-20"）：导出单日

    Args:
        target_month: 目标月份 "YYYY-MM" 或具体日期 "YYYY-MM-DD"
        stepno_filter: StepNo 筛选值列表
        output_dir: 输出目录

    Returns:
        int: 导出的总记录数
    """
    parts = target_month.split("-")
    stepno_str = "_".join(str(s) for s in stepno_filter)

    if len(parts) == 3:
        # 日期格式：仅导出当天
        target_date = datetime.strptime(target_month, "%Y-%m-%d").date()
        logger.info(f"日期导出模式: {target_date}, StepNo in {stepno_filter}")

        return export_to_csv(
            target_date=target_date,
            output_dir=output_dir,
            stepno_filter=stepno_filter,
            file_prefix=f"pytckreg3_{target_date.strftime('%Y%m%d')}_step{stepno_str}",
        )

    elif len(parts) == 2:
        # 月份格式：遍历整月，写入单个文件
        year, month = map(int, parts)
        _, last_day = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        logger.info(f"月份导出模式: {target_month} ({start_date} ~ {end_date}), StepNo in {stepno_filter}")

        config = get_db_config()
        try:
            conn = pymysql.connect(**config, cursorclass=SSCursor)
        except pymysql.Error as e:
            logger.error(f"连接失败: {e}")
            return 0

        try:
            with conn.cursor() as cursor:
                # 取一次列名（任意一天即可）
                cursor.execute(
                    f"SELECT TicketNo, SeqNo, WrkOrder, BundleNo, StepNo, Qty, "
                    f"RegPerSysID, RegDate, RegTime, RFID, Flow, PO, "
                    f"TimeCost, SysSource, AccBundleNo, MtrType, Color, Sizx, "
                    f"SerialNum, StationID FROM pytckreg3 LIMIT 0"
                )
                columns = [d[0] for d in cursor.description]

                output_dir.mkdir(parents=True, exist_ok=True)
                month_str = target_month.replace("-", "")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = output_dir / f"pytckreg3_{month_str}_step{stepno_str}_{timestamp}.csv"

                total = 0
                with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)

                    current = start_date
                    while current <= end_date:
                        sql = """
                            SELECT TicketNo, SeqNo, WrkOrder, BundleNo, StepNo, Qty,
                                   RegPerSysID, RegDate, RegTime, RFID, Flow, PO,
                                   TimeCost, SysSource, AccBundleNo, MtrType, Color, Sizx,
                                   SerialNum, StationID
                            FROM pytckreg3
                            WHERE RegDate >= %s AND RegDate < %s + INTERVAL 1 DAY
                        """
                        params: list = [current, current]

                        if stepno_filter:
                            placeholders = ",".join(["%s"] * len(stepno_filter))
                            sql += f" AND StepNo IN ({placeholders})"
                            params.extend(stepno_filter)

                        cursor.execute(sql, params)
                        daily_count = 0
                        for row in cursor:
                            writer.writerow(row)
                            total += 1
                            daily_count += 1
                            if total % CHUNK_SIZE == 0:
                                logger.info(f"已写入 {total} 条")

                        logger.info(f"  {current}: {daily_count} 条 (累计 {total})")
                        current = date.fromordinal(current.toordinal() + 1)

                logger.success(f"月份导出完成: {output_file} ({total} 条)")
                return total

        except pymysql.Error as e:
            logger.error(f"查询失败: {e}")
            return 0
        finally:
            conn.close()

    else:
        logger.error(f"无法识别的格式: {target_month}，请使用 YYYY-MM 或 YYYY-MM-DD")
        return 0


def main():
    if MODE == "export_date":
        if TARGET_DATE:
            target_date = datetime.strptime(TARGET_DATE, "%Y-%m-%d").date()
        else:
            target_date = date.today()
        export_to_csv(target_date, OUTPUT_DIR)

    elif MODE == "export_month":
        export_month_to_csv(TARGET_MONTH, STEPNO_FILTER, OUTPUT_DIR)

    else:
        logger.error(f"未知模式: {MODE}，可选值: export_date / export_month")


if __name__ == "__main__":
    main()