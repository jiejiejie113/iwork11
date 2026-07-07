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
    支持员工级总目标和工单级分目标：
    - workorder='' 表示员工总目标（兼容旧数据）
    - workorder='WO-001' 表示该工单的分目标
    """
    target_date = models.DateField('目标日期')
    employee_id = models.CharField('员工ID', max_length=50)
    workorder = models.CharField('工单号', max_length=100, blank=True, default='')
    target_qty = models.IntegerField('目标产量', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'target_production'
        unique_together = ('target_date', 'employee_id', 'workorder')
        managed = True
        verbose_name = '目标产量'
        verbose_name_plural = '目标产量'

    def __str__(self) -> str:
        wo_tag = f' @ {self.workorder}' if self.workorder else ''
        return f'{self.target_date} - {self.employee_id}{wo_tag}: {self.target_qty}'


class ProductionOrder(models.Model):
    """
    生产工单信息（本地存储）
    数据源：iwork/sqlite/production_orders.db → orders 表
    每个工单可关联多个部门和款号
    """
    order_no = models.CharField('工单号', max_length=50)
    order_dept = models.CharField('工单/部门', max_length=50, blank=True, default='')
    style_no = models.CharField('款号', max_length=50, blank=True, default='')
    product_name = models.CharField('产品名称', max_length=200, blank=True, default='')
    style_desc = models.CharField('款式', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'production_orders'
        managed = True
        indexes = [
            models.Index(fields=['order_no'], name='idx_po_order_no'),
            models.Index(fields=['style_no'], name='idx_po_style_no'),
            models.Index(fields=['order_dept'], name='idx_po_order_dept'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['order_no', 'order_dept', 'style_no', 'product_name', 'style_desc'],
                name='idx_po_unique_record',
            ),
        ]
        verbose_name = '生产工单'
        verbose_name_plural = '生产工单'

    def __str__(self) -> str:
        return f'{self.order_no} - {self.style_no}'
