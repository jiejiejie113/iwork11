"""站内警报、订阅、受众和投递的本地持久化模型。"""

from django.db import models


class AlertRule(models.Model):
    """声明一个可配置的数据异常检测规则。"""

    code = models.CharField("规则编码", max_length=64, unique=True)
    name = models.CharField("规则名称", max_length=120)
    severity = models.CharField("严重程度", max_length=16, default="warning")
    detector_type = models.CharField("检测器类型", max_length=64)
    config = models.JSONField("规则配置", default=dict, blank=True)
    allowed_roles = models.JSONField("可订阅角色", default=list, blank=True)
    scope_type = models.CharField("范围类型", max_length=32, default="none")
    mandatory_roles = models.JSONField("强制接收角色", default=list, blank=True)
    cooldown_seconds = models.PositiveIntegerField("冷却秒数", default=900)
    enabled = models.BooleanField("是否启用", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        app_label = "iwork"
        db_table = "alert_rule"


class AlertSubscription(models.Model):
    """用户对允许规则及业务范围的站内订阅。"""

    subject = models.CharField("订阅人subject", max_length=255)
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="subscriptions")
    scope_type = models.CharField("范围类型", max_length=32, default="none")
    scope_value = models.CharField("范围值", max_length=120, blank=True, default="")
    enabled = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        app_label = "iwork"
        db_table = "alert_subscription"
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "rule", "scope_type", "scope_value"],
                name="uq_alert_subscription_scope",
            ),
        ]


class AlertEvent(models.Model):
    """按稳定业务维度去重的警报事件及恢复状态。"""

    class Status(models.TextChoices):
        """警报生命周期状态。"""

        OPEN = "open", "异常中"
        RECOVERED = "recovered", "已恢复"

    rule = models.ForeignKey(AlertRule, on_delete=models.PROTECT, related_name="events")
    business_date = models.DateField("业务日期")
    dimension_key = models.CharField("业务维度键", max_length=255)
    snapshot_version = models.CharField("快照版本", max_length=120, blank=True, default="")
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.OPEN)
    severity = models.CharField("严重程度", max_length=16, default="warning")
    title = models.CharField("标题", max_length=200)
    message = models.TextField("通知正文")
    payload = models.JSONField("业务负载", default=dict, blank=True)
    occurrence_count = models.PositiveIntegerField("出现次数", default=1)
    revision = models.PositiveIntegerField("事件修订号", default=1)
    first_seen_at = models.DateTimeField("首次出现时间", auto_now_add=True)
    last_seen_at = models.DateTimeField("最后出现时间", auto_now=True)
    recovered_at = models.DateTimeField("恢复时间", null=True, blank=True)

    class Meta:
        app_label = "iwork"
        db_table = "alert_event"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "business_date", "dimension_key"],
                name="uq_alert_event_dimension",
            ),
        ]
        indexes = [models.Index(fields=["business_date", "status"], name="idx_alert_event_state")]


class AlertAudience(models.Model):
    """事件的角色或具体账号受众，不预先枚举管理员。"""

    event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="audiences")
    audience_type = models.CharField("受众类型", max_length=16)
    audience_key = models.CharField("受众键", max_length=255)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        app_label = "iwork"
        db_table = "alert_audience"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "audience_type", "audience_key"],
                name="uq_alert_audience",
            ),
        ]


class NotificationReceipt(models.Model):
    """具体用户对事件修订的已读状态。"""

    event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="receipts")
    subject = models.CharField("收件人subject", max_length=255)
    read_revision = models.PositiveIntegerField("已读修订号", default=0)
    read_at = models.DateTimeField("已读时间", null=True, blank=True)

    class Meta:
        app_label = "iwork"
        db_table = "notification_receipt"
        constraints = [
            models.UniqueConstraint(fields=["event", "subject"], name="uq_notification_receipt"),
        ]


class NotificationDelivery(models.Model):
    """一个事件对一个受众的可靠站内投递状态。"""

    class Status(models.TextChoices):
        """投递处理状态。"""

        PENDING = "pending", "待投递"
        SENDING = "sending", "投递中"
        SENT = "sent", "已投递"
        FAILED = "failed", "失败"

    event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="deliveries")
    audience = models.ForeignKey(AlertAudience, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField("渠道", max_length=32, default="in_app")
    event_revision = models.PositiveIntegerField("待投递事件修订号", default=1)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveIntegerField("尝试次数", default=0)
    next_retry_at = models.DateTimeField("下次重试时间", null=True, blank=True)
    last_error = models.TextField("最后错误", blank=True, default="")
    sent_at = models.DateTimeField("投递时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        app_label = "iwork"
        db_table = "notification_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "channel", "audience"],
                name="uq_notification_delivery",
            ),
        ]


class AlertEvaluationRun(models.Model):
    """一份已发布快照的幂等警报评估记录。"""

    business_date = models.DateField("业务日期")
    snapshot_version = models.CharField("快照版本", max_length=120)
    status = models.CharField("状态", max_length=16, default="completed")
    event_count = models.PositiveIntegerField("事件数量", default=0)
    error_message = models.TextField("错误信息", blank=True, default="")
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    completed_at = models.DateTimeField("完成时间", auto_now=True)

    class Meta:
        app_label = "iwork"
        db_table = "alert_evaluation_run"
        constraints = [
            models.UniqueConstraint(
                fields=["business_date", "snapshot_version"],
                name="uq_alert_evaluation_run",
            ),
        ]
