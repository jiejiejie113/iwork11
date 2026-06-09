"""
数据同步模块
负责将远程数据库数据同步到本地数据库
"""
from datetime import date, timedelta
from loguru import logger
from django.utils import timezone
from django.db import transaction

from iwork.models import Pytckreg3
from iwork.local_models import LocalPytckreg3


def _get_date_range(target: date) -> tuple:
    """获取指定日期的 aware datetime 范围（利用 RegDate 索引）"""
    start = timezone.make_aware(timezone.datetime.combine(target, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(target + timedelta(days=1), timezone.datetime.min.time()))
    return start, end


def has_changes(local_record, remote_record) -> bool:
    """
    检测记录是否有变更

    Args:
        local_record: 本地记录
        remote_record: 远程记录

    Returns:
        bool: 是否有变更
    """
    compare_fields = [
        'SeqNo', 'WrkOrder', 'BundleNo', 'StepNo', 'Qty',
        'RegPerSysID', 'RegDate', 'RegTime', 'RFID', 'Flow',
        'PO', 'TimeCost', 'SysSource', 'AccBundleNo', 'MtrType',
        'Color', 'Sizx', 'SerialNum', 'StationID'
    ]

    for field in compare_fields:
        local_value = getattr(local_record, field)
        remote_value = getattr(remote_record, field)

        if local_value is None and remote_value is None:
            continue
        if local_value is None or remote_value is None:
            return True

        if local_value != remote_value:
            return True

    return False


def sync_date_data(target_date: date) -> dict:
    """
    同步指定日期的数据到本地数据库

    Args:
        target_date: 目标日期

    Returns:
        dict: 同步结果统计
    """
    logger.info(f"开始同步日期 {target_date} 的数据")

    start, end = _get_date_range(target_date)

    # 1. 从远程查询（走 RegDate 索引）
    remote_records = (
        Pytckreg3.objects.using('iwork')
        .filter(RegDate__gte=start, RegDate__lt=end)
        .iterator(chunk_size=5000)
    )

    # 2. 从本地查询现有数据
    local_records = {
        record.TicketNo: record
        for record in LocalPytckreg3.objects.using('iwork_local').filter(
            RegDate__gte=start, RegDate__lt=end
        )
    }

    stats = {'synced_count': 0, 'updated_count': 0, 'skipped_count': 0}

    # 3. 逐条处理（自动提交模式，每 500 条输出一次进度日志）
    progress_interval = 500
    for i, record in enumerate(remote_records, 1):
        local_record = local_records.get(record.TicketNo)

        if local_record is None:
            _, created = LocalPytckreg3.objects.using('iwork_local').update_or_create(
                TicketNo=record.TicketNo,
                defaults={
                    'SeqNo': record.SeqNo, 'WrkOrder': record.WrkOrder,
                    'BundleNo': record.BundleNo, 'StepNo': record.StepNo,
                    'Qty': record.Qty, 'RegPerSysID': record.RegPerSysID,
                    'RegDate': record.RegDate, 'RegTime': record.RegTime,
                    'RFID': record.RFID, 'Flow': record.Flow,
                    'PO': record.PO, 'TimeCost': record.TimeCost,
                    'SysSource': record.SysSource, 'AccBundleNo': record.AccBundleNo,
                    'MtrType': record.MtrType, 'Color': record.Color,
                    'Sizx': record.Sizx, 'SerialNum': record.SerialNum,
                    'StationID': record.StationID,
                },
            )
            if created:
                stats['synced_count'] += 1
            else:
                stats['updated_count'] += 1
        elif has_changes(local_record, record):
            local_record.SeqNo = record.SeqNo
            local_record.WrkOrder = record.WrkOrder
            local_record.BundleNo = record.BundleNo
            local_record.StepNo = record.StepNo
            local_record.Qty = record.Qty
            local_record.RegPerSysID = record.RegPerSysID
            local_record.RegDate = record.RegDate
            local_record.RegTime = record.RegTime
            local_record.RFID = record.RFID
            local_record.Flow = record.Flow
            local_record.PO = record.PO
            local_record.TimeCost = record.TimeCost
            local_record.SysSource = record.SysSource
            local_record.AccBundleNo = record.AccBundleNo
            local_record.MtrType = record.MtrType
            local_record.Color = record.Color
            local_record.Sizx = record.Sizx
            local_record.SerialNum = record.SerialNum
            local_record.StationID = record.StationID
            local_record.save(using='iwork_local')
            stats['updated_count'] += 1
        else:
            stats['skipped_count'] += 1

        if i % progress_interval == 0:
            logger.info(f"  已处理 {i} 条, 新增 {stats['synced_count']}, "
                        f"更新 {stats['updated_count']}, 跳过 {stats['skipped_count']}")

    logger.info(f"同步完成: 新增 {stats['synced_count']}, 更新 {stats['updated_count']}, "
                f"跳过 {stats['skipped_count']}")

    # 同步后清空本地历史缓存，确保下次查询获取最新数据
    from iwork.statistics import invalidate_local_cache
    invalidate_local_cache(target_date)

    return stats
