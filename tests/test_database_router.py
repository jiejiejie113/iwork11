from unittest.mock import Mock
from iwork.database_router import DatabaseRouter


class TestDatabaseRouter:
    """数据库路由器测试"""

    def setup_method(self):
        self.router = DatabaseRouter()

    def test_db_for_read_iwork_app_returns_iwork(self):
        """测试 iwork app 读取操作返回 iwork 数据库"""
        model = Mock()
        model._meta.app_label = 'iwork'
        result = self.router.db_for_read(model)
        assert result == 'iwork'

    def test_db_for_read_other_app_returns_default(self):
        """测试其他 app 读取操作返回 default 数据库"""
        model = Mock()
        model._meta.app_label = 'auth'
        result = self.router.db_for_read(model)
        assert result == 'default'

    def test_db_for_write_iwork_app_returns_none(self):
        """测试 iwork app 写入操作被拒绝"""
        model = Mock()
        model._meta.app_label = 'iwork'
        result = self.router.db_for_write(model)
        assert result is None

    def test_db_for_write_other_app_returns_default(self):
        """测试其他 app 写入操作返回 default 数据库"""
        model = Mock()
        model._meta.app_label = 'auth'
        result = self.router.db_for_write(model)
        assert result == 'default'

    def test_allow_relation_same_db_returns_true(self):
        """测试同一数据库的关联查询允许"""
        obj1 = Mock()
        obj1._state.db = 'default'
        obj2 = Mock()
        obj2._state.db = 'default'
        result = self.router.allow_relation(obj1, obj2)
        assert result is True

    def test_allow_relation_different_db_returns_false(self):
        """测试不同数据库的关联查询禁止"""
        obj1 = Mock()
        obj1._state.db = 'default'
        obj2 = Mock()
        obj2._state.db = 'iwork'
        result = self.router.allow_relation(obj1, obj2)
        assert result is False

    def test_allow_migrate_iwork_app_returns_false(self):
        """测试 iwork app 禁止迁移"""
        result = self.router.allow_migrate('iwork', 'iwork')
        assert result is False

    def test_allow_migrate_other_app_returns_true_for_default(self):
        """测试其他 app 迁移到 default"""
        result = self.router.allow_migrate('default', 'auth')
        assert result is True


class TestDatabaseRouterLocalPytckreg3:
    """LocalPytckreg3 模型专属路由规则"""

    def setup_method(self):
        self.router = DatabaseRouter()

    def _make_model(self, app_label='iwork', model_name='localpytckreg3'):
        model = Mock()
        model._meta.app_label = app_label
        model._meta.model_name = model_name
        return model

    def test_db_for_read_localpytckreg3_returns_iwork_local(self):
        """LocalPytckreg3 读 → iwork_local"""
        model = self._make_model()
        result = self.router.db_for_read(model)
        assert result == 'iwork_local'

    def test_db_for_write_localpytckreg3_returns_iwork_local(self):
        """LocalPytckreg3 写 → iwork_local（可读写）"""
        model = self._make_model()
        result = self.router.db_for_write(model)
        assert result == 'iwork_local'

    def test_db_for_read_pytckreg3_returns_iwork(self):
        """普通 Pytckreg3 读 → iwork"""
        model = self._make_model(model_name='pytckreg3')
        result = self.router.db_for_read(model)
        assert result == 'iwork'

    def test_db_for_write_pytckreg3_returns_none(self):
        """普通 Pytckreg3 写 → None（只读）"""
        model = self._make_model(model_name='pytckreg3')
        result = self.router.db_for_write(model)
        assert result is None

    def test_allow_migrate_localpytckreg3_to_iwork_local(self):
        """LocalPytckreg3 可迁移到 iwork_local"""
        result = self.router.allow_migrate('iwork_local', 'iwork', model_name='localpytckreg3')
        assert result is True

    def test_allow_migrate_localpytckreg3_not_to_other_db(self):
        """LocalPytckreg3 不可迁移到其他库"""
        result = self.router.allow_migrate('default', 'iwork', model_name='localpytckreg3')
        assert result is False

    def test_allow_migrate_pytckreg3_always_false(self):
        """普通 Pytckreg3 任何库都不允许迁移"""
        result = self.router.allow_migrate('iwork', 'iwork', model_name='pytckreg3')
        assert result is False

    def test_group_target_production_uses_local_database(self):
        """整组目标模型应固定读写并迁移到 iwork_local。"""
        model = self._make_model(model_name='grouptargetproduction')

        assert self.router.db_for_read(model) == 'iwork_local'
        assert self.router.db_for_write(model) == 'iwork_local'
        assert self.router.allow_migrate(
            'iwork_local',
            'iwork',
            model_name='grouptargetproduction',
        ) is True

    def test_igarment_production_order_uses_local_database(self):
        """iGarment 精简快照模型应固定路由到 iwork_local。"""
        model = self._make_model(model_name='igarmentproductionorder')

        assert self.router.db_for_read(model) == 'iwork_local'
        assert self.router.db_for_write(model) == 'iwork_local'
        assert self.router.allow_migrate(
            'iwork_local',
            'iwork',
            model_name='igarmentproductionorder',
        ) is True
