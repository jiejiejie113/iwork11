from datetime import datetime
from iwork.models import Pydefstp, Pywrkord, Pywrkstp, Pytckreg3


class TestPytckreg3Model:
    """Pytckreg3 模型测试"""

    def test_app_label_is_iwork(self):
        """测试 app_label 配置为 iwork"""
        assert Pytckreg3._meta.app_label == 'iwork'

    def test_managed_is_false(self):
        """测试 managed=False 禁止迁移"""
        assert Pytckreg3._meta.managed is False

    def test_db_table_is_pytckreg3(self):
        """测试 db_table 配置"""
        assert Pytckreg3._meta.db_table == 'pytckreg3'

    def test_ticketno_max_length_is_13(self):
        """测试 TicketNo 字段最大长度"""
        field = Pytckreg3._meta.get_field('TicketNo')
        assert field.max_length == 13

    def test_ticketno_is_primary_key(self):
        """测试 TicketNo 是主键"""
        field = Pytckreg3._meta.get_field('TicketNo')
        assert field.primary_key is True

    def test_seqno_is_integer_field(self):
        """测试 SeqNo 是整数字段"""
        from django.db.models import IntegerField
        field = Pytckreg3._meta.get_field('SeqNo')
        assert isinstance(field, IntegerField)

    def test_wrkorder_max_length_is_14(self):
        """测试 WrkOrder 字段最大长度"""
        field = Pytckreg3._meta.get_field('WrkOrder')
        assert field.max_length == 14

    def test_rfid_max_length_is_10(self):
        """测试 RFID 字段最大长度"""
        field = Pytckreg3._meta.get_field('RFID')
        assert field.max_length == 10

    def test_flow_max_length_is_40(self):
        """测试 Flow 字段最大长度"""
        field = Pytckreg3._meta.get_field('Flow')
        assert field.max_length == 40

    def test_po_max_length_is_40(self):
        """测试 PO 字段最大长度"""
        field = Pytckreg3._meta.get_field('PO')
        assert field.max_length == 40

    def test_stationid_max_length_is_3(self):
        """测试 StationID 字段最大长度"""
        field = Pytckreg3._meta.get_field('StationID')
        assert field.max_length == 3

    def test_regdate_is_datetime_field(self):
        """测试 RegDate 是 DateTimeField"""
        from django.db.models import DateTimeField
        field = Pytckreg3._meta.get_field('RegDate')
        assert isinstance(field, DateTimeField)

    def test_regtime_is_datetime_field(self):
        """测试 RegTime 是 DateTimeField"""
        from django.db.models import DateTimeField
        field = Pytckreg3._meta.get_field('RegTime')
        assert isinstance(field, DateTimeField)

    def test_full_datetime_returns_combined_datetime(self):
        """测试 full_datetime 属性组合年月日和时分秒"""
        record = Pytckreg3(
            RegDate=datetime(2026, 4, 21, 0, 0, 0),
            RegTime=datetime(1900, 1, 1, 14, 30, 45)
        )
        result = record.full_datetime
        assert result == datetime(2026, 4, 21, 14, 30, 45)

    def test_full_datetime_with_none_regdate(self):
        """测试 full_datetime 处理 None RegDate"""
        record = Pytckreg3(
            RegDate=None,
            RegTime=datetime(1900, 1, 1, 14, 30, 45)
        )
        result = record.full_datetime
        assert result is None

    def test_full_datetime_with_none_regtime(self):
        """测试 full_datetime 处理 None RegTime"""
        record = Pytckreg3(
            RegDate=datetime(2026, 4, 21, 0, 0, 0),
            RegTime=None
        )
        result = record.full_datetime
        assert result is None

    def test_full_datetime_with_both_none(self):
        """测试 full_datetime 处理两者都为 None"""
        record = Pytckreg3(RegDate=None, RegTime=None)
        result = record.full_datetime
        assert result is None

    def test_str_representation(self):
        """测试字符串表示"""
        record = Pytckreg3(TicketNo='TK123456789AB', SeqNo=1, SysSource='SYS')
        assert str(record) == 'TK123456789AB'


class TestPywrkstpModel:
    """工单工序工时表模型测试。"""

    def test_primary_key_matches_remote_composite_key(self):
        """ORM 使用 WrkOrder + StepNo，不生成远端不存在的 id 字段。"""
        assert Pywrkstp._meta.pk.field_names == ('WrkOrder', 'StepNo')
        assert 'id' not in {field.name for field in Pywrkstp._meta.fields}

    def test_step_time_is_float_field(self):
        """标准工时字段按远端浮点列映射。"""
        from django.db.models import FloatField

        assert isinstance(Pywrkstp._meta.get_field('StepTime'), FloatField)

    def test_description_matches_remote_column(self):
        """工单工序描述来自 pywrkstp.Description。"""
        field = Pywrkstp._meta.get_field('Description')

        assert field.max_length == 120
        assert field.null is True


class TestPywrkordModel:
    """工单扩展信息表模型测试。"""

    def test_remote_table_mapping_is_read_only(self):
        """初版款号模型必须映射远程表且禁止迁移。"""
        assert Pywrkord._meta.db_table == 'pywrkord'
        assert Pywrkord._meta.managed is False

    def test_wrk_order_is_remote_primary_key(self):
        """完整工单号必须直接使用远程主键。"""
        field = Pywrkord._meta.get_field('WrkOrder')

        assert field.primary_key is True
        assert field.max_length == 14

    def test_ext_field_matches_initial_style_source_column(self):
        """初版款号来源字段必须允许远程空值并保留完整长度。"""
        field = Pywrkord._meta.get_field('ExtField01')

        assert field.max_length == 100
        assert field.null is True


class TestPydefstpModel:
    """工序字典表模型测试。"""

    def test_description_is_not_mapped(self):
        """pydefstp 不再作为生产详情的工序描述来源。"""
        assert 'description' not in {field.name for field in Pydefstp._meta.fields}
        assert 'Description' not in {field.name for field in Pydefstp._meta.fields}
