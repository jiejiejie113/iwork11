"""
生产工单数据导入命令

将 iwork/sqlite/production_orders.db 中的 orders 表数据导入到 MySQL iwork_local.production_orders 表。

用法:
    python manage.py import_production_orders

特性:
    - 精确镜像：MySQL 与当前 SQLite 快照完全一致
    - 事务发布：失败时完整回滚到上一版数据
    - 批量写入：每次 1000 条，减少数据库往返
    - 进度展示：每 5000 条输出一次进度
"""

import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from loguru import logger

from iwork.local_models import ProductionOrder

# ============================================================================
# 配置
# ============================================================================
SQLITE_DB_PATH = settings.PRODUCTION_ORDERS_SQLITE_PATH
BATCH_SIZE = settings.PRODUCTION_ORDERS_IMPORT_BATCH_SIZE
PROGRESS_INTERVAL = settings.PRODUCTION_ORDERS_PROGRESS_INTERVAL
DATABASE_ALIAS = 'iwork_local'
SOURCE_FIELD_MAP = {
    'order': 'order_no',
    'order/dept': 'order_dept',
    'Style No': 'style_no',
    'Product Name': 'product_name',
    '款式': 'style_desc',
}
SOURCE_COLUMNS = tuple(SOURCE_FIELD_MAP)


class Command(BaseCommand):
    help = '从 SQLite 数据库导入生产工单数据到 MySQL iwork_local 库'

    def handle(self, *args, **options):
        """
        校验 SQLite 快照并以事务方式发布到 MySQL。

        Args:
            *args (tuple): Django 管理命令传入的位置参数。
            **options (dict): Django 管理命令解析后的选项。

        Raises:
            CommandError: SQLite 快照无效或发布后的数据不一致。
        """
        logger.info("开始导入生产工单数据...")
        logger.info("SQLite 数据源: {}", SQLITE_DB_PATH)

        if not SQLITE_DB_PATH.exists():
            logger.error("SQLite 文件不存在: {}", SQLITE_DB_PATH)
            raise CommandError(f"SQLite 文件不存在: {SQLITE_DB_PATH}")

        # 连接 SQLite，完成完整性和结构校验后读取所有数据。
        conn = None
        try:
            conn = sqlite3.connect(str(SQLITE_DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            integrity_results = [
                row[0] for row in cursor.execute('PRAGMA integrity_check')
            ]
            if integrity_results != ['ok']:
                raise CommandError(
                    f"SQLite 完整性检查失败: {'; '.join(integrity_results)}"
                )

            table_exists = cursor.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'orders'"
            ).fetchone()
            if not table_exists:
                raise CommandError("SQLite 缺少 orders 表")

            source_columns = {
                row['name'] for row in cursor.execute('PRAGMA table_info("orders")')
            }
            missing_columns = [
                column for column in SOURCE_COLUMNS if column not in source_columns
            ]
            if missing_columns:
                raise CommandError(
                    f"SQLite orders 表缺少必需字段: {', '.join(missing_columns)}"
                )

            cursor.execute('SELECT * FROM orders')
            rows = cursor.fetchall()
            total_rows = len(rows)
        except sqlite3.DatabaseError as exc:
            raise CommandError(f"SQLite 完整性检查失败: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()

        logger.info("SQLite 中共有 {} 条记录", total_rows)

        if total_rows == 0:
            raise CommandError("SQLite 表中无数据，拒绝覆盖上一版 MySQL 快照")

        blank_columns = [
            column
            for column in SOURCE_COLUMNS
            if any(
                row[column] is None or str(row[column]).strip() == ''
                for row in rows
            )
        ]
        if blank_columns:
            raise CommandError(
                f"SQLite 必需字段存在空值: {', '.join(blank_columns)}"
            )

        oversized_columns = []
        for source_column, model_field_name in SOURCE_FIELD_MAP.items():
            max_length = ProductionOrder._meta.get_field(model_field_name).max_length
            if any(len(str(row[source_column])) > max_length for row in rows):
                oversized_columns.append(f"{source_column}>{max_length}")
        if oversized_columns:
            raise CommandError(
                f"SQLite 字段长度超过限制: {', '.join(oversized_columns)}"
            )

        composite_rows = [tuple(row[column] for column in SOURCE_COLUMNS) for row in rows]
        duplicate_count = total_rows - len(set(composite_rows))
        if duplicate_count:
            raise CommandError(f"SQLite 存在 {duplicate_count} 条复合重复记录")

        # 在事务外完成对象构建，缩短 MySQL 事务时间。
        objects = [
            ProductionOrder(
                order_no=row['order'],
                order_dept=row['order/dept'],
                style_no=row['Style No'],
                product_name=row['Product Name'],
                style_desc=row['款式'],
            )
            for row in rows
        ]

        logger.info("开始事务发布 MySQL 精确快照...")
        manager = ProductionOrder.objects.using(DATABASE_ALIAS)
        with transaction.atomic(using=DATABASE_ALIAS):
            deleted_count, _ = manager.all().delete()
            logger.info("已移除上一版生产订单: {} 条", deleted_count)
            for start_index in range(0, total_rows, BATCH_SIZE):
                batch = objects[start_index:start_index + BATCH_SIZE]
                manager.bulk_create(batch, batch_size=BATCH_SIZE)
                published_rows = start_index + len(batch)
                if (
                    published_rows % PROGRESS_INTERVAL == 0
                    or published_rows == total_rows
                ):
                    logger.info(
                        "发布进度: {}/{} ({:.1f}%)",
                        published_rows,
                        total_rows,
                        published_rows / total_rows * 100,
                    )
            published_count = manager.count()
            if published_count != total_rows:
                raise CommandError(
                    f"发布后数量不一致: SQLite={total_rows}, MySQL={published_count}"
                )

        logger.success(
            "生产订单快照发布完成: {} 条",
            total_rows,
        )
        self.stdout.write(f"导入完成: MySQL 已发布 {total_rows} 条生产订单")
