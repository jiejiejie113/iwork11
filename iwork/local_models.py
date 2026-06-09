from django.db import models


class LocalPytckreg3(models.Model):
    """
    本地业务数据模型（可读写）
    映射到 iwork_local.pytckreg3 表
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
        verbose_name = '本地打卡记录'
        verbose_name_plural = '本地打卡记录'

    def __str__(self) -> str:
        return self.TicketNo


class TargetProduction(models.Model):
    """
    目标产量（本地持久化存储）
    采用全局员工日目标模型，每个员工每天只有一个总目标
    """
    target_date = models.DateField('目标日期')
    employee_id = models.CharField('员工ID', max_length=50)
    target_qty = models.IntegerField('目标产量', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'target_production'
        unique_together = ('target_date', 'employee_id')
        managed = True
        verbose_name = '目标产量'
        verbose_name_plural = '目标产量'

    def __str__(self) -> str:
        return f'{self.target_date} - {self.employee_id}: {self.target_qty}'
