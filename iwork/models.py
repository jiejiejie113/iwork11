from django.db import models
from datetime import datetime

from iwork import alert_models as _alert_models  # noqa: F401


class Pytckreg3(models.Model):
    """
    生产流水线打卡记录模型（只读）
    映射到 payroll.pytckreg3 表
    """

    TicketNo = models.CharField('票号', max_length=13, primary_key=True)
    SeqNo = models.IntegerField('序号', default=0)
    WrkOrder = models.CharField('工单号', max_length=14, blank=True, default='')
    BundleNo = models.IntegerField('扎号', default=0)
    StepNo = models.IntegerField('工序号', default=0)
    Qty = models.IntegerField('数量', default=0)
    RegPerSysID = models.IntegerField('登记人系统ID', default=0)
    RegDate = models.DateTimeField('登记日期', null=True, blank=True)
    RegTime = models.DateTimeField('登记时间', null=True, blank=True)
    RFID = models.CharField('RFID', max_length=10, blank=True, default='')
    Flow = models.CharField('流程', max_length=40, blank=True, default='')
    PO = models.CharField('PO号', max_length=40, blank=True, default='')
    TimeCost = models.IntegerField('耗时', default=0)
    SysSource = models.CharField('系统来源', max_length=3, default='')
    AccBundleNo = models.IntegerField('累计扎号', default=0)
    MtrType = models.CharField('物料类型', max_length=14, blank=True, default='')
    Color = models.CharField('颜色', max_length=35, blank=True, default='')
    Sizx = models.CharField('尺码', max_length=16, blank=True, default='')
    SerialNum = models.CharField('序列号', max_length=10, blank=True, default='')
    StationID = models.CharField('工位ID', max_length=3, blank=True, default='')

    class Meta:
        app_label = 'iwork'
        db_table = 'pytckreg3'
        managed = False
        verbose_name = '打卡记录'
        verbose_name_plural = '打卡记录'

    @property
    def full_datetime(self) -> datetime | None:
        """
        组合年月日和时分秒返回完整时间

        Returns:
            datetime | None: 完整时间，如果任一字段为 None 则返回 None
        """
        if self.RegDate is None or self.RegTime is None:
            return None

        return datetime(
            self.RegDate.year,
            self.RegDate.month,
            self.RegDate.day,
            self.RegTime.hour,
            self.RegTime.minute,
            self.RegTime.second,
        )

    def __str__(self) -> str:
        return self.TicketNo


class Pyperson(models.Model):
    """
    人员主数据模型（只读）。

    ``SysID`` 用于匹配生产记录中的 ``RegPerSysID``；生产详情仅使用
    ``Remark`` 作为新的员工 ID，空值和重复值由映射规则过滤。
    """

    SysID = models.IntegerField('人员系统ID', primary_key=True)
    Remark = models.TextField('员工ID', null=True, blank=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'pyperson'
        managed = False
        verbose_name = '人员'
        verbose_name_plural = '人员'

    def __str__(self) -> str:
        """返回人员系统 ID。"""
        return str(self.SysID)


class Pywrkord(models.Model):
    """
    工单扩展信息模型（只读）。

    映射到 ``payroll.pywrkord``，其中 ``ExtField01`` 作为初版款号来源。
    """

    WrkOrder = models.CharField('完整工单号', max_length=14, primary_key=True)
    ExtField01 = models.CharField(
        '初版款号',
        max_length=100,
        null=True,
        blank=True,
        default='',
    )

    class Meta:
        app_label = 'iwork'
        db_table = 'pywrkord'
        managed = False
        verbose_name = '工单扩展信息'
        verbose_name_plural = '工单扩展信息'

    def __str__(self) -> str:
        """返回完整工单号。"""
        return self.WrkOrder

class Pydefstp(models.Model):
    """
    工序定义表（只读）
    映射到远程 pydefstp 表
    生产详情不使用该表的 Description 字段。
    """

    StepNo = models.IntegerField('工序号', primary_key=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'pydefstp'
        managed = False
        verbose_name = '工序定义'
        verbose_name_plural = '工序定义'

    def __str__(self) -> str:
        return str(self.StepNo)


class Pywrkstp(models.Model):
    """
    工单工序工时表（只读）
    映射到远程 pywrkstp 表
    StepNo + WrkOrder 联合确定 Description（工序描述）和 StepTime（标准工时）
    """

    pk = models.CompositePrimaryKey('WrkOrder', 'StepNo')
    StepNo = models.IntegerField('工序号', default=0)
    WrkOrder = models.CharField('工单号', max_length=14, blank=True, default='')
    Description = models.CharField('工序描述', max_length=120, null=True, blank=True, default='')
    StepTime = models.FloatField('标准工时', default=0.0)

    class Meta:
        app_label = 'iwork'
        db_table = 'pywrkstp'
        managed = False
        unique_together = ('StepNo', 'WrkOrder')
        verbose_name = '工单工序工时'
        verbose_name_plural = '工单工序工时'

    def __str__(self) -> str:
        return f'{self.WrkOrder} / Step {self.StepNo}: {self.Description or ""} / {self.StepTime}'
