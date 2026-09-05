from datetime import time

from django.conf import settings
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
    planned_work_minutes = models.PositiveIntegerField(
        '计划工作分钟',
        null=True,
        blank=True,
    )
    submitted_by_subject = models.CharField('提交人 subject', max_length=255, blank=True, default='')
    submitted_by_username = models.CharField('提交人用户名', max_length=150, blank=True, default='')
    submitted_at = models.DateTimeField('提交时间', null=True, blank=True)
    is_late = models.BooleanField('是否逾期提交', default=False)
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


class IworkPrincipal(models.Model):
    """iwork 本地稳定身份快照。"""

    subject = models.CharField('Keycloak subject', max_length=255, unique=True)
    username = models.CharField('用户名', max_length=150, blank=True, default='')
    email = models.EmailField('邮箱', blank=True, default='')
    display_name = models.CharField('显示名称', max_length=255, blank=True, default='')
    keycloak_groups = models.JSONField('Keycloak 组', default=list, blank=True)
    is_admin = models.BooleanField('是否管理员', default=False)
    is_iwork_admin = models.BooleanField('是否 iwork 专属管理员', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'iwork_principal'
        verbose_name = 'iwork 身份'
        verbose_name_plural = 'iwork 身份'

    def __str__(self) -> str:
        """返回优先使用用户名的可读身份。

        Returns:
            str: 用户名；用户名为空时返回稳定subject。
        """
        return self.username or self.subject


class ManagedFlowAssignment(models.Model):
    """稳定身份在有效期内负责的生产组。"""

    principal = models.ForeignKey(
        IworkPrincipal,
        on_delete=models.CASCADE,
        related_name='flow_assignments',
        verbose_name='负责人',
    )
    flow_name = models.CharField('生产组', max_length=40)
    effective_date = models.DateField('生效日期')
    expires_date = models.DateField('失效日期', null=True, blank=True)
    created_by_subject = models.CharField('创建人 subject', max_length=255)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'managed_flow_assignment'
        constraints = [
            models.UniqueConstraint(
                fields=['principal', 'flow_name', 'effective_date'],
                name='uq_flow_assignment_start',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(expires_date__isnull=True)
                    | models.Q(expires_date__gte=models.F('effective_date'))
                ),
                name='ck_flow_assignment_dates',
            ),
        ]
        indexes = [
            models.Index(fields=['flow_name', 'effective_date', 'expires_date'], name='idx_flow_assignment_valid'),
        ]


class TargetSubmissionPolicy(models.Model):
    """按生效日期版本化的每日目标提交策略。"""

    effective_date = models.DateField('生效日期', unique=True)
    deadline_time = models.TimeField(
        '提交截止时间',
        default=time.fromisoformat(settings.IWORK_TARGET_SUBMISSION_DEFAULT_DEADLINE),
    )
    timezone_name = models.CharField(
        '业务时区',
        max_length=64,
        default=settings.IWORK_BUSINESS_TIME_ZONE,
    )
    created_by_subject = models.CharField('创建人 subject', max_length=255)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'target_submission_policy'
        ordering = ['-effective_date']


class DailyTargetObligation(models.Model):
    """一个生产组在一个业务日的目标提交责任。"""

    class Status(models.TextChoices):
        """每日责任状态。"""

        PENDING = 'pending', '待提交'
        FULFILLED = 'fulfilled', '按时完成'
        OVERDUE = 'overdue', '已逾期'
        FULFILLED_LATE = 'fulfilled_late', '逾期完成'
        WAIVED = 'waived', '已免除'

    target_date = models.DateField('目标日期')
    flow_name = models.CharField('生产组', max_length=40)
    status = models.CharField('状态', max_length=16, choices=Status.choices, default=Status.PENDING)
    deadline_at = models.DateTimeField('截止时间')
    submitted_by_subject = models.CharField('提交人 subject', max_length=255, blank=True, default='')
    submitted_by_username = models.CharField('提交人用户名', max_length=150, blank=True, default='')
    submitted_at = models.DateTimeField('提交时间', null=True, blank=True)
    waived_at = models.DateTimeField('免除时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'daily_target_obligation'
        constraints = [
            models.UniqueConstraint(fields=['target_date', 'flow_name'], name='uq_daily_target_obligation'),
        ]
        indexes = [
            models.Index(fields=['target_date', 'status'], name='idx_target_obligation_status'),
        ]


class DailyTargetObligationLeader(models.Model):
    """每日责任生成时冻结的有效负责人快照。"""

    obligation = models.ForeignKey(
        DailyTargetObligation,
        on_delete=models.CASCADE,
        related_name='leader_links',
        verbose_name='每日责任',
    )
    principal = models.ForeignKey(
        IworkPrincipal,
        on_delete=models.PROTECT,
        related_name='obligation_links',
        verbose_name='负责人',
    )
    subject = models.CharField('负责人 subject', max_length=255)
    username = models.CharField('负责人用户名', max_length=150, blank=True, default='')

    class Meta:
        app_label = 'iwork'
        db_table = 'daily_target_obligation_leader'
        constraints = [
            models.UniqueConstraint(fields=['obligation', 'principal'], name='uq_obligation_leader'),
        ]


class GroupTargetAuditLog(models.Model):
    """生产组目标写入和责任状态变化的审计日志。"""

    target_date = models.DateField('目标日期')
    flow_name = models.CharField('生产组', max_length=40)
    action = models.CharField('动作', max_length=32)
    actor_subject = models.CharField('操作人 subject', max_length=255)
    actor_username = models.CharField('操作人用户名', max_length=150, blank=True, default='')
    old_value = models.JSONField('变更前', null=True, blank=True)
    new_value = models.JSONField('变更后', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        app_label = 'iwork'
        db_table = 'group_target_audit_log'
        indexes = [
            models.Index(fields=['target_date', 'flow_name', 'created_at'], name='idx_group_target_audit'),
        ]


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


class IGarmentProductionOrder(models.Model):
    """iGarment 生产订单精简快照（本地 MySQL）。"""

    customer_order_no = models.CharField(
        '客户订单编号',
        max_length=20,
        blank=True,
        default='',
    )
    order_no = models.CharField('订单编号', max_length=50)
    quantity = models.IntegerField('订单数量')
    created_date = models.DateTimeField('创建日期')

    class Meta:
        app_label = 'iwork'
        db_table = 'igarment_production_orders'
        managed = True
        indexes = [
            models.Index(
                fields=['customer_order_no', 'created_date'],
                name='idx_igarment_customer_created',
            ),
            models.Index(fields=['order_no'], name='idx_igarment_order_no'),
        ]
        verbose_name = 'iGarment 生产订单'
        verbose_name_plural = 'iGarment 生产订单'

    def __str__(self) -> str:
        """返回客户订单编号和订单编号组成的可读标识。"""
        return f'{self.customer_order_no} - {self.order_no}'


class HistoricalProductionFact(models.Model):
    """按小时聚合的本地历史生产事实。"""

    production_date = models.DateField('生产日期')
    event_hour = models.SmallIntegerField('生产小时', default=-1)
    registered_date = models.DateTimeField('登记日期', db_column='RegDate')
    registered_time = models.DateTimeField('登记时间', db_column='RegTime', null=True, blank=True)
    flow = models.CharField('生产线', max_length=40, blank=True, default='')
    station_id = models.CharField('工位ID', max_length=3, blank=True, default='')
    employee_id = models.IntegerField('员工系统ID', default=0)
    employee_remark = models.TextField('员工新ID', blank=True, default='')
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
    initial_style_no = models.CharField(
        '初版款号',
        max_length=100,
        blank=True,
        default='',
    )

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
