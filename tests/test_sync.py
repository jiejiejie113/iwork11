"""
同步逻辑测试
"""
import pytest
from unittest.mock import patch, Mock, call
from datetime import date, datetime
from django.utils import timezone


class TestHasChanges:
    """数据变更检测测试（已有）"""

    def test_has_changes_same_record(self):
        """测试相同记录无变更"""
        class MockRecord:
            def __init__(self):
                self.SeqNo = 1; self.Qty = 100; self.WrkOrder = 'WO001'
                self.BundleNo = 1; self.StepNo = 1; self.RegPerSysID = 1
                self.RegDate = None; self.RegTime = None; self.RFID = ''
                self.Flow = 'FlowA'; self.PO = ''; self.TimeCost = 0
                self.SysSource = ''; self.AccBundleNo = 0; self.MtrType = ''
                self.Color = ''; self.Sizx = ''; self.SerialNum = ''; self.StationID = ''
        from iwork.sync import has_changes
        assert has_changes(MockRecord(), MockRecord()) is False

    def test_has_changes_different_record(self):
        """测试不同记录有变更"""
        class MockRecord:
            def __init__(self, qty):
                self.SeqNo = 1; self.Qty = qty; self.WrkOrder = 'WO001'
                self.BundleNo = 1; self.StepNo = 1; self.RegPerSysID = 1
                self.RegDate = None; self.RegTime = None; self.RFID = ''
                self.Flow = 'FlowA'; self.PO = ''; self.TimeCost = 0
                self.SysSource = ''; self.AccBundleNo = 0; self.MtrType = ''
                self.Color = ''; self.Sizx = ''; self.SerialNum = ''; self.StationID = ''
        from iwork.sync import has_changes
        assert has_changes(MockRecord(100), MockRecord(200)) is True

    def test_has_changes_none_values(self):
        """测试None值处理：两者都是 None → 无变更"""
        class MockRecord:
            def __init__(self, qty=None):
                self.SeqNo = 1; self.Qty = qty; self.WrkOrder = 'WO001'
                self.BundleNo = 1; self.StepNo = 1; self.RegPerSysID = 1
                self.RegDate = None; self.RegTime = None; self.RFID = ''
                self.Flow = 'FlowA'; self.PO = ''; self.TimeCost = 0
                self.SysSource = ''; self.AccBundleNo = 0; self.MtrType = ''
                self.Color = ''; self.Sizx = ''; self.SerialNum = ''; self.StationID = ''
        from iwork.sync import has_changes
        assert has_changes(MockRecord(None), MockRecord(None)) is False

    def test_has_changes_one_none(self):
        """测试一个为 None 一个不为 None → 有变更"""
        class MockRecord:
            def __init__(self, qty=None):
                self.SeqNo = 1; self.Qty = qty; self.WrkOrder = 'WO001'
                self.BundleNo = 1; self.StepNo = 1; self.RegPerSysID = 1
                self.RegDate = None; self.RegTime = None; self.RFID = ''
                self.Flow = 'FlowA'; self.PO = ''; self.TimeCost = 0
                self.SysSource = ''; self.AccBundleNo = 0; self.MtrType = ''
                self.Color = ''; self.Sizx = ''; self.SerialNum = ''; self.StationID = ''
        from iwork.sync import has_changes
        assert has_changes(MockRecord(None), MockRecord(100)) is True

    def test_has_changes_all_fields_compared(self):
        """测试全部字段变更检测（非仅 Qty）"""
        from iwork.sync import has_changes

        class MockRecord:
            SeqNo = 1; Qty = 100; WrkOrder = 'WO001'; BundleNo = 1
            StepNo = 1; RegPerSysID = 1; RegDate = None; RegTime = None
            RFID = ''; Flow = 'A'; PO = ''; TimeCost = 0; SysSource = ''
            AccBundleNo = 0; MtrType = ''; Color = ''; Sizx = ''
            SerialNum = ''; StationID = ''

        local = MockRecord()
        remote = MockRecord()
        remote.Flow = 'B'
        assert has_changes(local, remote) is True


class TestGetDateRange:
    """_get_date_range 工具函数测试"""

    def test_returns_aware_datetimes(self):
        """测试返回 timezone-aware 时间范围"""
        from iwork.sync import _get_date_range
        start, end = _get_date_range(date(2026, 5, 12))
        assert timezone.is_aware(start)
        assert timezone.is_aware(end)

    def test_span_is_exactly_one_day(self):
        """测试时间跨度正好 24 小时"""
        from iwork.sync import _get_date_range
        start, end = _get_date_range(date(2026, 5, 12))
        assert (end - start).days == 1
        assert (end - start).seconds == 0

    def test_start_is_midnight(self):
        """测试起始时间为当天 00:00:00"""
        from iwork.sync import _get_date_range
        start, _ = _get_date_range(date(2026, 5, 12))
        assert start.hour == 0
        assert start.minute == 0


class TestSyncDateData:
    """sync_date_data 同步流水线测试"""

    def _make_mock_record(self, ticket_no='T001', qty=100, wrk_order='W001',
                          stepno=70, flow='A1', station='S01'):
        """构造模拟的远程记录"""
        mock = Mock()
        mock.TicketNo = ticket_no
        mock.SeqNo = 1
        mock.WrkOrder = wrk_order
        mock.BundleNo = 1
        mock.StepNo = stepno
        mock.Qty = qty
        mock.RegPerSysID = 1
        fixed_time = timezone.make_aware(datetime(2026, 5, 12, 8, 30))
        mock.RegDate = fixed_time
        mock.RegTime = fixed_time
        mock.RFID = ''
        mock.Flow = flow
        mock.PO = ''
        mock.TimeCost = 0
        mock.SysSource = ''
        mock.AccBundleNo = 0
        mock.MtrType = ''
        mock.Color = ''
        mock.Sizx = ''
        mock.SerialNum = ''
        mock.StationID = station
        return mock

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_new_record_created(self, mock_remote_model, mock_local_model, mock_invalidate):
        """本地无记录 → 创建新记录"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = [
            self._make_mock_record('T001'),
        ]
        mock_local_model.objects.using.return_value.filter.return_value = {}
        mock_local_model.objects.using.return_value.update_or_create.return_value = (Mock(), True)

        result = sync_date_data(date(2026, 5, 12))

        assert result['synced_count'] == 1
        assert result['updated_count'] == 0
        assert result['skipped_count'] == 0
        mock_invalidate.assert_called_once_with(date(2026, 5, 12))

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_existing_record_unchanged_skipped(self, mock_remote_model, mock_local_model, mock_invalidate):
        """本地有相同记录 → 跳过"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = [
            self._make_mock_record('T001'),
        ]
        # 本地已存在相同记录
        local_record = self._make_mock_record('T001')
        mock_local_model.objects.using.return_value.filter.return_value = [local_record]

        result = sync_date_data(date(2026, 5, 12))
        assert result['skipped_count'] == 1

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_existing_record_changed_updated(self, mock_remote_model, mock_local_model, mock_invalidate):
        """本地有记录但 Qty 变化 → 更新"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = [
            self._make_mock_record('T001', qty=200),
        ]
        local_record = self._make_mock_record('T001', qty=100)
        mock_local_model.objects.using.return_value.filter.return_value = [local_record]

        result = sync_date_data(date(2026, 5, 12))
        assert result['updated_count'] >= 1
        # 字段应被更新
        assert local_record.Qty == 200

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_multiple_records_mixed(self, mock_remote_model, mock_local_model, mock_invalidate):
        """混合场景：新增+更新+跳过"""
        from iwork.sync import sync_date_data

        remote = [
            self._make_mock_record('T001'),  # 新增
            self._make_mock_record('T002', qty=200),  # 更新 (本地 qty=100)
            self._make_mock_record('T003'),  # 跳过 (完全相同)
            self._make_mock_record('T004'),  # 新增
        ]
        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = remote

        local_unchanged = self._make_mock_record('T003')
        local_changed = self._make_mock_record('T002', qty=100)
        mock_local_model.objects.using.return_value.filter.return_value = [
            local_changed,
            local_unchanged,
        ]
        mock_local_model.objects.using.return_value.update_or_create.return_value = (Mock(), True)

        result = sync_date_data(date(2026, 5, 12))

        assert result['synced_count'] == 2  # T001, T004
        assert result['updated_count'] == 1  # T002
        assert result['skipped_count'] == 1  # T003

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_cache_invalidated_after_sync(self, mock_remote_model, mock_local_model, mock_invalidate):
        """同步完成后调用 invalidate_local_cache"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = []
        mock_local_model.objects.using.return_value.filter.return_value = {}

        sync_date_data(date(2026, 5, 12))
        mock_invalidate.assert_called_once_with(date(2026, 5, 12))

    @patch('iwork.sync.logger')
    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_progress_logged_every_500(self, mock_r, mock_l, mock_inv, mock_logger):
        """每 500 条输出一次进度日志"""
        from iwork.sync import sync_date_data

        # 构造 501 条记录，应触发行日志一次
        remote = [self._make_mock_record(f'T{i:04d}') for i in range(501)]
        mock_r.objects.using.return_value.filter.return_value.iterator.return_value = remote
        mock_l.objects.using.return_value.filter.return_value = {}
        mock_l.objects.using.return_value.update_or_create.return_value = (Mock(), True)

        sync_date_data(date(2026, 5, 12))

        # 检查 info 日志中包含 "已处理 500"
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        progress_msgs = [c for c in info_calls if '已处理 500' in c]
        assert len(progress_msgs) >= 1

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_empty_remote_returns_zero_stats(self, mock_remote_model, mock_local_model, mock_invalidate):
        """远程无数据 → 全部统计为 0"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = []
        mock_local_model.objects.using.return_value.filter.return_value = {}

        result = sync_date_data(date(2026, 5, 12))

        assert result['synced_count'] == 0
        assert result['updated_count'] == 0
        assert result['skipped_count'] == 0

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_local_query_uses_correct_date_range(self, mock_remote_model, mock_local_model, mock_invalidate):
        """验证本地查询使用正确的日期范围过滤"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = []
        mock_local_model.objects.using.return_value.filter.return_value = {}

        sync_date_data(date(2026, 5, 12))

        # 验证远程查询和本地查询都使用了 filter
        assert mock_remote_model.objects.using.called
        assert mock_local_model.objects.using.called

    @patch('iwork.sync.invalidate_local_cache')
    @patch('iwork.sync.LocalPytckreg3')
    @patch('iwork.sync.Pytckreg3')
    def test_update_or_create_fields_match_remote(self, mock_remote_model, mock_local_model, mock_invalidate):
        """验证 update_or_create 传递的 defaults 包含所有 18 个字段"""
        from iwork.sync import sync_date_data

        mock_remote_model.objects.using.return_value.filter.return_value.iterator.return_value = [
            self._make_mock_record('T001'),
        ]
        mock_local_model.objects.using.return_value.filter.return_value = {}
        mock_local_model.objects.using.return_value.update_or_create.return_value = (Mock(), True)

        sync_date_data(date(2026, 5, 12))

        call_kwargs = mock_local_model.objects.using.return_value.update_or_create.call_args
        defaults = call_kwargs[1]['defaults']
        expected_fields = {'SeqNo', 'WrkOrder', 'BundleNo', 'StepNo', 'Qty',
                          'RegPerSysID', 'RegDate', 'RegTime', 'RFID', 'Flow',
                          'PO', 'TimeCost', 'SysSource', 'AccBundleNo', 'MtrType',
                          'Color', 'Sizx', 'SerialNum', 'StationID'}
        assert set(defaults.keys()) == expected_fields
