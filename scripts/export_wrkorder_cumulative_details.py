"""按工单号从生产库导出累计产量源数据明细。"""

import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pymysql
from loguru import logger
from openpyxl import Workbook
from pymysql.cursors import SSCursor

# ======
# 查询配置：日常使用只需修改这里的工单号
WRKORDER = "BU1211"

# ======
# 文件路径配置
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
ENV_FILE_CANDIDATES = (
    Path(__file__).resolve().parent / "export.env",
    Path.cwd() / "export.env",
    Path(__file__).resolve().parent.parent / "iwork" / ".env",
)

# ======
# 生产数据库连接配置
IWORK_DB_HOST = "192.168.4.19"
IWORK_DB_PORT = 3306
IWORK_DB_NAME = "payroll"
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 300

# ======
# 导出配置
CHUNK_SIZE = 10_000
SOURCE_FIELDS = (
    "TicketNo",
    "SeqNo",
    "WrkOrder",
    "BundleNo",
    "StepNo",
    "Qty",
    "RegPerSysID",
    "RegDate",
    "RegTime",
    "RFID",
    "Flow",
    "PO",
    "TimeCost",
    "SysSource",
    "AccBundleNo",
    "MtrType",
    "Color",
    "Sizx",
    "SerialNum",
    "StationID",
)
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def configure_logging() -> None:
    """配置控制台日志和保留七天的文件日志。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stdout, format=LOG_FORMAT, level="INFO")
    logger.add(
        LOG_DIR / "export_wrkorder_{time:YYYY-MM-DD}.log",
        format=LOG_FORMAT,
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        level="DEBUG",
    )


def build_detail_query() -> str:
    """
    构建按完整工单号读取全部源明细的参数化查询。

    Returns:
        str: 只包含工单号过滤条件的只读查询。
    """
    fields = ", ".join(f"`{field}`" for field in SOURCE_FIELDS)
    return f"""
        SELECT {fields}
        FROM `pytckreg3`
        WHERE `WrkOrder` = %s
        ORDER BY `StepNo`, `RegDate`, `RegTime`, `TicketNo`, `SeqNo`
    """


def load_db_config() -> dict[str, Any]:
    """
    从现有 export.env 或 iwork/.env 加载生产库只读连接配置。

    Returns:
        dict[str, Any]: 可传给 pymysql.connect 的连接参数。

    Raises:
        ValueError: 未找到数据库用户名或密码。
    """
    values: dict[str, str] = {}
    for env_path in ENV_FILE_CANDIDATES:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        break

    user = values.get("IWORK_DB_USER", "")
    password = values.get("IWORK_DB_PASSWORD", "")
    if not user or not password:
        raise ValueError(
            "未找到生产库凭据，请在 scripts/export.env 中配置 "
            "IWORK_DB_USER 和 IWORK_DB_PASSWORD"
        )

    return {
        "host": values.get("IWORK_DB_HOST", IWORK_DB_HOST),
        "port": int(values.get("IWORK_DB_PORT", IWORK_DB_PORT)),
        "user": user,
        "password": password,
        "database": values.get("IWORK_DB_NAME", IWORK_DB_NAME),
        "charset": "utf8mb4",
        "connect_timeout": CONNECT_TIMEOUT,
        "read_timeout": READ_TIMEOUT,
        "cursorclass": SSCursor,
    }


def build_output_path(wrkorder: str, output_dir: Path) -> Path:
    """
    生成包含工单号和时间戳的导出文件路径。

    Args:
        wrkorder (str): 完整工单号。
        output_dir (Path): 导出目录。

    Returns:
        Path: 最终 XLSX 文件路径。
    """
    safe_wrkorder = re.sub(r'[^0-9A-Za-z_-]+', "_", wrkorder)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"pytckreg3_{safe_wrkorder}_累计产量源明细_{timestamp}.xlsx"


def export_wrkorder_details(
    wrkorder: str,
    output_dir: Path = OUTPUT_DIR,
    db_config: dict[str, Any] | None = None,
    connection_factory: Callable[..., Any] = pymysql.connect,
) -> tuple[Path, int]:
    """
    按完整工单号逐行导出生产表中的全部源数据。

    查询不限制日期、Flow 或工序号，也不做汇总、去重和字段转换。输出行按
    工序号和登记时间排序，便于直接核对每个工序的历史产量明细。

    Args:
        wrkorder (str): 要查询的完整 WrkOrder。
        output_dir (Path): XLSX 输出目录。
        db_config (dict[str, Any] | None): 数据库连接参数，默认从配置文件加载。
        connection_factory (Callable[..., Any]): 数据库连接工厂，默认使用 PyMySQL。

    Returns:
        tuple[Path, int]: 导出文件路径和源数据行数。

    Raises:
        ValueError: 工单号为空。
        pymysql.MySQLError: 生产库连接或查询失败。
    """
    normalized_wrkorder = wrkorder.strip()
    if not normalized_wrkorder:
        raise ValueError("WRKORDER 不能为空")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = build_output_path(normalized_wrkorder, output_dir)
    temp_path = output_path.with_name(
        f"{output_path.stem}.{uuid4().hex}.tmp{output_path.suffix}"
    )
    connection = None
    workbook = None

    try:
        config = db_config if db_config is not None else load_db_config()
        logger.info(
            "开始查询生产源表: WrkOrder={}, host={}, database={}",
            normalized_wrkorder,
            config.get("host", ""),
            config.get("database", ""),
        )
        connection = connection_factory(**config)
        workbook = Workbook(write_only=True)
        worksheet = workbook.create_sheet(title="累计产量源明细")
        worksheet.append(SOURCE_FIELDS)

        row_count = 0
        with connection.cursor() as cursor:
            cursor.execute(build_detail_query(), (normalized_wrkorder,))
            for row in cursor:
                worksheet.append(row)
                row_count += 1
                if row_count % CHUNK_SIZE == 0:
                    logger.info("已写入 {} 条源数据", row_count)

        workbook.save(temp_path)
        workbook.close()
        workbook = None
        temp_path.replace(output_path)
        logger.success("导出完成: {}，共 {} 条源数据", output_path, row_count)
        return output_path, row_count
    except Exception:
        if workbook is not None:
            workbook.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        if connection is not None:
            connection.close()


def main() -> int:
    """
    执行全局配置中的工单累计产量源明细导出。

    Returns:
        int: 成功返回 0，失败返回 1。
    """
    configure_logging()
    try:
        export_wrkorder_details(WRKORDER)
    except Exception as exc:
        logger.exception("导出失败: {}", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
