"""生产订单 SQLite 快照导入测试。"""

import sqlite3

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connections

from iwork.local_models import ProductionOrder
from iwork.management.commands import import_production_orders


SQLITE_COLUMNS = (
    '"order" TEXT',
    '"order/dept" TEXT',
    '"Style No" TEXT',
    '"Product Name" TEXT',
    '"款式" TEXT',
)


def create_source_database(path, rows, columns=SQLITE_COLUMNS):
    """
    创建测试用生产订单 SQLite 快照。

    Args:
        path (Path): SQLite 文件路径。
        rows (list[tuple[str, ...]]): 待写入的生产订单数据。
        columns (tuple[str, ...]): 测试表字段定义。
    """
    with sqlite3.connect(path) as connection:
        connection.execute(f'CREATE TABLE "orders" ({", ".join(columns)})')
        connection.executemany(
            f'INSERT INTO "orders" VALUES ({", ".join("?" for _ in columns)})',  # noqa: S608 -- 测试字段定义来自本文件常量。
            rows,
        )


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_import_replaces_existing_snapshot(monkeypatch, tmp_path):
    """导入新快照后，MySQL 镜像应与 SQLite 内容完全一致。"""
    ProductionOrder.objects.using('iwork_local').create(
        order_no='OLD-ORDER',
        order_dept='OLD-DEPT',
        style_no='OLD001',
        product_name='旧产品',
        style_desc='旧款式',
    )
    source_path = tmp_path / 'production_orders.db'
    expected_rows = [
        ('ORDER-1', 'DEPT-1', '100001', '产品一', '款式一'),
        ('ORDER-2', 'DEPT-2', '100002', '产品二', '款式二'),
    ]
    create_source_database(source_path, expected_rows)
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    call_command('import_production_orders')

    actual_rows = list(
        ProductionOrder.objects.using('iwork_local')
        .order_by('order_no')
        .values_list(
            'order_no',
            'order_dept',
            'style_no',
            'product_name',
            'style_desc',
        )
    )
    assert actual_rows == expected_rows


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_empty_source_keeps_previous_snapshot(monkeypatch, tmp_path):
    """空快照应中止导入，并保留上一版 MySQL 数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    create_source_database(source_path, [])
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='SQLite 表中无数据'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_duplicate_source_rows_are_rejected(monkeypatch, tmp_path):
    """复合重复的源记录应被拒绝，并保留上一版 MySQL 数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    duplicate_row = ('ORDER-1', 'DEPT-1', '100002', '产品一', '款式一')
    create_source_database(source_path, [duplicate_row, duplicate_row])
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='复合重复记录'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_missing_source_column_is_rejected(monkeypatch, tmp_path):
    """缺少必需字段的 SQLite 应明确失败，并保留上一版数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    create_source_database(
        source_path,
        [('ORDER-1', 'DEPT-1', '100002', '产品一')],
        columns=SQLITE_COLUMNS[:-1],
    )
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='缺少必需字段.*款式'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_missing_source_table_is_rejected(monkeypatch, tmp_path):
    """缺少 orders 表的 SQLite 应明确失败，并保留上一版数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    with sqlite3.connect(source_path):
        pass
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='缺少 orders 表'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_corrupt_source_database_is_rejected(monkeypatch, tmp_path):
    """损坏的 SQLite 应明确失败，并保留上一版数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    source_path.write_bytes(b'not a valid SQLite database')
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='SQLite 完整性检查失败'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_blank_required_value_is_rejected(monkeypatch, tmp_path):
    """必需字段存在空值时应中止导入，并保留上一版数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    create_source_database(
        source_path,
        [('ORDER-1', 'DEPT-1', '100002', '产品一', '')],
    )
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='必需字段存在空值.*款式'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_value_exceeding_model_length_is_rejected(monkeypatch, tmp_path):
    """字段值超过 MySQL 模型长度时应中止导入，并保留上一版数据。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    create_source_database(
        source_path,
        [('O' * 51, 'DEPT-1', '100002', '产品一', '款式一')],
    )
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    with pytest.raises(CommandError, match='字段长度超过限制.*order'):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_database_write_failure_rolls_back_previous_snapshot(monkeypatch, tmp_path):
    """MySQL 写入失败时，删除旧快照的操作也必须回滚。"""
    previous = ProductionOrder.objects.using('iwork_local').create(
        order_no='EXISTING',
        order_dept='DEPT',
        style_no='100001',
        product_name='现有产品',
        style_desc='现有款式',
    )
    source_path = tmp_path / 'production_orders.db'
    create_source_database(
        source_path,
        [('ORDER-1', 'DEPT-1', '100002', '产品一', '款式一')],
    )
    monkeypatch.setattr(import_production_orders, 'SQLITE_DB_PATH', source_path)

    def reject_production_order_insert(execute, sql, params, many, context):
        """模拟数据库在写入新生产订单时失败。"""
        if 'INSERT INTO "production_orders"' in sql:
            raise DatabaseError('模拟 MySQL 写入失败')
        return execute(sql, params, many, context)

    with (
        connections['iwork_local'].execute_wrapper(reject_production_order_insert),
        pytest.raises(DatabaseError, match='模拟 MySQL 写入失败'),
    ):
        call_command('import_production_orders')

    assert list(
        ProductionOrder.objects.using('iwork_local').values_list('pk', flat=True)
    ) == [previous.pk]
