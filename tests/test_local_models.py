"""
本地模型测试
"""
import pytest
from iwork.local_models import IGarmentProductionOrder, LocalPytckreg3


class TestLocalPytckreg3:
    """本地Pytckreg3模型测试"""
    
    def test_model_exists(self):
        """测试模型是否存在"""
        assert hasattr(LocalPytckreg3, 'TicketNo')
        assert hasattr(LocalPytckreg3, 'Qty')
    
    def test_model_str(self):
        """测试模型字符串表示"""
        record = LocalPytckreg3(TicketNo='TEST001')
        assert str(record) == 'TEST001'
    
    def test_model_fields(self):
        """测试模型字段定义"""
        assert LocalPytckreg3._meta.db_table == 'pytckreg3'
        assert LocalPytckreg3._meta.managed is False
        assert LocalPytckreg3._meta.app_label == 'iwork'
    
    def test_model_field_types(self):
        """测试模型字段类型"""
        ticket_field = LocalPytckreg3._meta.get_field('TicketNo')
        assert ticket_field.max_length == 13
        assert ticket_field.primary_key is True
        
        qty_field = LocalPytckreg3._meta.get_field('Qty')
        assert qty_field.default == 0


def test_igarment_order_model_matches_server_snapshot_table():
    """iGarment 模型字段必须与服务器同步任务创建的 MySQL 表一致。"""
    assert IGarmentProductionOrder._meta.db_table == 'igarment_production_orders'
    assert IGarmentProductionOrder._meta.get_field('customer_order_no').max_length == 20
    assert IGarmentProductionOrder._meta.get_field('order_no').max_length == 50
    assert IGarmentProductionOrder._meta.get_field('quantity').get_internal_type() == 'IntegerField'
    assert IGarmentProductionOrder._meta.get_field('created_date').get_internal_type() == 'DateTimeField'
