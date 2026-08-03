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


class GroupTargetProduction(models.Model):
    """
    生产组每日目标产量。

    同一生产组每天只保存一个整组目标。接口读取实时员工工序后，将该目标复制到
    每道工序，并按工序内去重员工人数分配个人目标。
    """
    target_date = models.DateField('目标日期')
    flow_name = models.CharField('生产组', max_length=40)
    target_qty = models.IntegerField('整组目标产量', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'group_target_production'
        unique_together = ('target_date', 'flow_name')
        managed = True
        verbose_name = '生产组目标产量'
        verbose_name_plural = '生产组目标产量'

    def __str__(self) -> str:
        """
        返回包含日期、生产组和目标值的可读文本。

        Returns:
            str: 整组目标记录的可读文本。
        """
        return f'{self.target_date} - {self.flow_name}: {self.target_qty}'


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


class HistoricalProductionFact(models.Model):
    """按小时聚合的本地历史生产事实。"""

    production_date = models.DateField('生产日期')
    event_hour = models.SmallIntegerField('生产小时', default=-1)
    registered_date = models.DateTimeField('登记日期', db_column='RegDate')
    registered_time = models.DateTimeField('登记时间', db_column='RegTime', null=True, blank=True)
    flow = models.CharField('生产线', max_length=40, blank=True, default='')
    station_id = models.CharField('工位ID', max_length=3, blank=True, default='')
    employee_id = models.IntegerField('员工系统ID', default=0)
    wrk_order = models.CharField('本厂款号', max_length=14, blank=True, default='')
    step_no = models.IntegerField('工序号', default=0)
    qty = models.BigIntegerField('聚合产量', default=0)
    source_record_count = models.PositiveIntegerField('源记录数', default=0)

    class Meta:
        app_label = 'iwork'
        db_table = 'historical_production_fact'
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'production_date', 'event_hour', 'flow', 'station_id',
                    'employee_id', 'wrk_order', 'step_no',
                ],
                name='uq_history_fact_grain',
            ),
        ]
        indexes = [
            models.Index(fields=['production_date', 'flow', 'employee_id'], name='idx_hist_flow_emp'),
            models.Index(fields=['production_date', 'wrk_order', 'step_no', 'flow'], name='idx_hist_wo_step_flow'),
            models.Index(fields=['production_date', 'step_no', 'employee_id'], name='idx_hist_step_emp'),
            models.Index(fields=['production_date', 'event_hour'], name='idx_hist_date_hour'),
        ]


class HistoricalStepSnapshot(models.Model):
    """生产日期对应的工序和产品元数据快照。"""

    snapshot_date = models.DateField('快照日期')
    wrk_order = models.CharField('本厂款号', max_length=14)
    step_no = models.IntegerField('工序号')
    description = models.CharField('工序描述', max_length=120, blank=True, default='')
    step_time = models.FloatField('标准工时', null=True, blank=True)
    style_no = models.CharField('款号', max_length=50, blank=True, default='')
    product_name = models.CharField('产品名称', max_length=200, blank=True, default='')
    order_no = models.CharField('生产单号', max_length=50, blank=True, default='')

    class Meta:
        app_label = 'iwork'
        db_table = 'historical_step_snapshot'
        constraints = [
            models.UniqueConstraint(
                fields=['snapshot_date', 'wrk_order', 'step_no'],
                name='uq_history_step_snapshot',
            ),
        ]
        indexes = [
            models.Index(fields=['snapshot_date', 'wrk_order'], name='idx_hist_meta_workorder'),
        ]


class HistoricalSyncState(models.Model):
    """一个生产日期的历史快照发布状态与校验摘要。"""

    class Status(models.TextChoices):
        RUNNING = 'running', '同步中'
        SUCCESS = 'success', '成功'
        FAILED = 'failed', '失败'

    snapshot_date = models.DateField('快照日期', unique=True)
    status = models.CharField('状态', max_length=16, choices=Status.choices)
    source_row_count = models.PositiveBigIntegerField('源记录数', default=0)
    source_total_qty = models.BigIntegerField('源总产量', default=0)
    fact_row_count = models.PositiveIntegerField('事实行数', default=0)
    metadata_row_count = models.PositiveIntegerField('元数据行数', default=0)
    missing_metadata_count = models.PositiveIntegerField('缺失元数据数', default=0)
    snapshot_version = models.PositiveIntegerField('快照版本', default=1)
    error_message = models.TextField('错误信息', blank=True, default='')
    started_at = models.DateTimeField('开始时间', auto_now_add=True)
    completed_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'historical_sync_state'
        ordering = ['-snapshot_date']
