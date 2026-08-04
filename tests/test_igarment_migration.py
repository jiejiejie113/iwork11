"""iGarment 快照表迁移的生产安全行为测试。"""

from importlib import import_module
from unittest.mock import Mock


def test_reverse_migration_preserves_server_managed_snapshot_table():
    """反向迁移只移除模型状态，不得删除服务器同步任务维护的表。"""
    migration = import_module(
        "iwork.migrations.0007_igarmentproductionorder"
    ).Migration
    operation = migration.operations[0]
    schema_editor = Mock()

    operation.database_backwards(
        "iwork",
        schema_editor,
        Mock(),
        Mock(),
    )

    schema_editor.delete_model.assert_not_called()
    schema_editor.connection.cursor.assert_not_called()
