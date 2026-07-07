"""
生产工单数据导入命令

将 iwork/sqlite/production_orders.db 中的 orders 表数据导入到 MySQL iwork_local.production_orders 表。

用法:
    python manage.py import_production_orders

特性:
    - 幂等：可重复执行，重复数据自动跳过
    - 批量写入：每次 1000 条，减少数据库往返
    - 进度展示：每 5000 条输出一次进度
"""

import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from iwork.local_models import ProductionOrder

# ============================================================================
# 配置
# ============================================================================
SQLITE_DB_PATH = settings.BASE_DIR / "sqlite" / "production_orders.db"
BATCH_SIZE = 1000
PROGRESS_INTERVAL = 5000


class Command(BaseCommand):
    help = '从 SQLite 数据库导入生产工单数据到 MySQL iwork_local 库'

    def handle(self, *args, **options):
        logger.info("开始导入生产工单数据...")
        logger.info("SQLite 数据源: {}", SQLITE_DB_PATH)

        if not SQLITE_DB_PATH.exists():
            logger.error("SQLite 文件不存在: {}", SQLITE_DB_PATH)
            self.stderr.write(f"错误: SQLite 文件不存在: {SQLITE_DB_PATH}")
            return

        # 连接 SQLite，读取所有数据
        conn = sqlite3.connect(str(SQLITE_DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM orders')
        rows = cursor.fetchall()
        total_rows = len(rows)
        conn.close()

        logger.info("SQLite 中共有 {} 条记录", total_rows)

        if total_rows == 0:
            logger.warning("SQLite 表中无数据，跳过导入")
            return

        # 转换为 Django 模型对象列表
        logger.info("开始批量写入 MySQL...")
        objects = []
        success_count = 0
        skip_count = 0

        for i, row in enumerate(rows, 1):
            objects.append(ProductionOrder(
                order_no=row['order'],
                order_dept=row['order/dept'],
                style_no=row['Style No'],
                product_name=row['Product Name'],
                style_desc=row['款式'],
            ))

            # 分批写入
            if len(objects) >= BATCH_SIZE or i == total_rows:
                try:
                    created = ProductionOrder.objects.bulk_create(
                        objects,
                        ignore_conflicts=True,
                    )
                    success_count += len(created)
                    skip_count += len(objects) - len(created)
                except Exception as e:
                    logger.error("批写入失败 (第 {} 条附近): {}", i, e)
                    self.stderr.write(f"错误: 第 {i} 条附近写入失败: {e}")
                objects = []

            # 进度提示
            if i % PROGRESS_INTERVAL == 0 or i == total_rows:
                logger.info(
                    "导入进度: {}/{} ({:.1f}%)，已成功 {} 条，跳过 {} 条",
                    i, total_rows, i / total_rows * 100,
                    success_count, skip_count,
                )

        logger.success(
            "导入完成！共 {} 条，成功 {} 条，跳过 {} 条（重复）",
            total_rows, success_count, skip_count,
        )
        self.stdout.write(
            f"导入完成: 总计 {total_rows} 条, 成功 {success_count} 条, "
            f"跳过 {skip_count} 条 (重复)"
        )
