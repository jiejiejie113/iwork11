"""将 iGarment SQLite 精简字段事务发布到 iwork_local MySQL。"""

import os
import sqlite3
import sys
from pathlib import Path

from loguru import logger


# ======
# 文件与数据表配置
SOURCE_PATH = Path("/app/sqlite/iGarment_ProdOrder.db")
SOURCE_TABLE = "iGarment_ProdOrder"
TARGET_TABLE = "igarment_production_orders"

# ======
# 导入字段与批次配置
BATCH_SIZE = 1000
REQUIRED_COLUMNS = ("客戶訂單編號", "訂單編號", "數量", "創建日期")


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "iwork.settings")
sys.path.insert(0, "/app")

import django  # noqa: E402

django.setup()

from django.db import connections, transaction  # noqa: E402


logger.remove()
logger.add(
    sys.stdout,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
    level="INFO",
)


def validate_source(connection: sqlite3.Connection) -> int:
    """校验源库完整性、结构和目标字段内容。

    Args:
        connection: 以只读模式打开的 SQLite 连接。

    Returns:
        int: 校验通过的源表总行数。

    Raises:
        RuntimeError: SQLite 损坏、缺表、缺字段或包含无效必需字段。
    """
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError(f"SQLite 完整性检查失败: {'; '.join(integrity)}")

    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (SOURCE_TABLE,),
    ).fetchone()
    if table_exists is None:
        raise RuntimeError(f"SQLite 缺少 {SOURCE_TABLE} 表")

    source_columns = {
        row[1] for row in connection.execute(f'PRAGMA table_info("{SOURCE_TABLE}")')
    }
    missing = [name for name in REQUIRED_COLUMNS if name not in source_columns]
    if missing:
        raise RuntimeError(f"SQLite 缺少必需字段: {', '.join(missing)}")

    total_rows = connection.execute(
        f'SELECT COUNT(*) FROM "{SOURCE_TABLE}"'
    ).fetchone()[0]
    if total_rows <= 0:
        raise RuntimeError("SQLite 表中无数据，拒绝覆盖上一版 MySQL 快照")

    invalid_rows = connection.execute(
        f'''
        SELECT COUNT(*)
        FROM "{SOURCE_TABLE}"
        WHERE "訂單編號" IS NULL
           OR TRIM(CAST("訂單編號" AS TEXT)) = ''
           OR "數量" IS NULL
           OR "創建日期" IS NULL
           OR datetime("創建日期") IS NULL
           OR LENGTH(COALESCE(CAST("客戶訂單編號" AS TEXT), '')) > 20
           OR LENGTH(CAST("訂單編號" AS TEXT)) > 50
        '''
    ).fetchone()[0]
    if invalid_rows:
        raise RuntimeError(f"SQLite 必需字段存在 {invalid_rows} 条无效记录")
    return total_rows


def ensure_target_table() -> None:
    """首次运行时创建应用后续可直接读取的目标表。"""
    with connections["iwork_local"].cursor() as cursor:
        cursor.execute(
            f'''
            CREATE TABLE IF NOT EXISTS `{TARGET_TABLE}` (
                `id` BIGINT NOT NULL AUTO_INCREMENT,
                `customer_order_no` VARCHAR(20) NOT NULL DEFAULT '',
                `order_no` VARCHAR(50) NOT NULL,
                `quantity` INT NOT NULL,
                `created_date` DATETIME NOT NULL,
                PRIMARY KEY (`id`),
                KEY `idx_igarment_customer_created`
                    (`customer_order_no`, `created_date`),
                KEY `idx_igarment_order_no` (`order_no`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COLLATE=utf8mb4_unicode_ci
            '''
        )


def publish(connection: sqlite3.Connection, total_rows: int) -> None:
    """在单个 MySQL 事务中替换完整快照，失败时保留上一版。

    Args:
        connection: 已完成校验的只读 SQLite 连接。
        total_rows: 预期发布到 MySQL 的总行数。

    Raises:
        RuntimeError: 事务内写入后的行数与源表不一致。
    """
    source_cursor = connection.execute(
        f'''
        SELECT "客戶訂單編號", "訂單編號", "數量", "創建日期"
        FROM "{SOURCE_TABLE}"
        '''
    )
    inserted = 0
    with (
        transaction.atomic(using="iwork_local"),
        connections["iwork_local"].cursor() as cursor,
    ):
        cursor.execute(f"DELETE FROM `{TARGET_TABLE}`")
        while True:
            rows = source_cursor.fetchmany(BATCH_SIZE)
            if not rows:
                break
            normalized = [
                (
                    str(row[0]).strip() if row[0] is not None else "",
                    str(row[1]).strip(),
                    int(row[2]),
                    str(row[3]),
                )
                for row in rows
            ]
            cursor.executemany(
                f'''
                INSERT INTO `{TARGET_TABLE}`
                    (`customer_order_no`, `order_no`, `quantity`, `created_date`)
                VALUES (%s, %s, %s, %s)
                ''',
                normalized,
            )
            inserted += len(normalized)
            if inserted % 10000 == 0 or inserted == total_rows:
                logger.info("导入进度: {}/{}", inserted, total_rows)

        cursor.execute(f"SELECT COUNT(*) FROM `{TARGET_TABLE}`")
        published = cursor.fetchone()[0]
        if published != total_rows:
            raise RuntimeError(
                f"发布后数量不一致: SQLite={total_rows}, MySQL={published}"
            )


def main() -> None:
    """运行 SQLite 校验和 MySQL 事务发布。

    Raises:
        RuntimeError: SQLite 文件不存在或校验、发布失败。
    """
    if not SOURCE_PATH.is_file():
        raise RuntimeError(f"SQLite 文件不存在: {SOURCE_PATH}")

    source = sqlite3.connect(f"file:{SOURCE_PATH}?mode=ro", uri=True)
    try:
        total_rows = validate_source(source)
        ensure_target_table()
        publish(source, total_rows)
    finally:
        source.close()
        connections.close_all()
    logger.success("导入完成: MySQL 已发布 {} 条 iGarment 生产订单", total_rows)


if __name__ == "__main__":
    main()
