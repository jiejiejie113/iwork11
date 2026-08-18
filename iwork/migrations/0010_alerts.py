"""创建站内警报、订阅、受众、回执和投递表。"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """在本地业务库建立警报框架。"""

    dependencies = [("iwork", "0009_identity_target_responsibility")]

    operations = [
        migrations.CreateModel(
            name="AlertRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64, unique=True, verbose_name="规则编码")),
                ("name", models.CharField(max_length=120, verbose_name="规则名称")),
                ("severity", models.CharField(default="warning", max_length=16, verbose_name="严重程度")),
                ("detector_type", models.CharField(max_length=64, verbose_name="检测器类型")),
                ("config", models.JSONField(blank=True, default=dict, verbose_name="规则配置")),
                ("allowed_roles", models.JSONField(blank=True, default=list, verbose_name="可订阅角色")),
                ("scope_type", models.CharField(default="none", max_length=32, verbose_name="范围类型")),
                ("mandatory_roles", models.JSONField(blank=True, default=list, verbose_name="强制接收角色")),
                ("cooldown_seconds", models.PositiveIntegerField(default=900, verbose_name="冷却秒数")),
                ("enabled", models.BooleanField(default=False, verbose_name="是否启用")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={"db_table": "alert_rule"},
        ),
        migrations.CreateModel(
            name="AlertEvaluationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("business_date", models.DateField(verbose_name="业务日期")),
                ("snapshot_version", models.CharField(max_length=120, verbose_name="快照版本")),
                ("status", models.CharField(default="completed", max_length=16, verbose_name="状态")),
                ("event_count", models.PositiveIntegerField(default=0, verbose_name="事件数量")),
                ("error_message", models.TextField(blank=True, default="", verbose_name="错误信息")),
                ("started_at", models.DateTimeField(auto_now_add=True, verbose_name="开始时间")),
                ("completed_at", models.DateTimeField(auto_now=True, verbose_name="完成时间")),
            ],
            options={
                "db_table": "alert_evaluation_run",
                "constraints": [models.UniqueConstraint(fields=("business_date", "snapshot_version"), name="uq_alert_evaluation_run")],
            },
        ),
        migrations.CreateModel(
            name="AlertEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("business_date", models.DateField(verbose_name="业务日期")),
                ("dimension_key", models.CharField(max_length=255, verbose_name="业务维度键")),
                ("snapshot_version", models.CharField(blank=True, default="", max_length=120, verbose_name="快照版本")),
                ("status", models.CharField(choices=[("open", "异常中"), ("recovered", "已恢复")], default="open", max_length=16, verbose_name="状态")),
                ("severity", models.CharField(default="warning", max_length=16, verbose_name="严重程度")),
                ("title", models.CharField(max_length=200, verbose_name="标题")),
                ("message", models.TextField(verbose_name="通知正文")),
                ("payload", models.JSONField(blank=True, default=dict, verbose_name="业务负载")),
                ("occurrence_count", models.PositiveIntegerField(default=1, verbose_name="出现次数")),
                ("revision", models.PositiveIntegerField(default=1, verbose_name="事件修订号")),
                ("first_seen_at", models.DateTimeField(auto_now_add=True, verbose_name="首次出现时间")),
                ("last_seen_at", models.DateTimeField(auto_now=True, verbose_name="最后出现时间")),
                ("recovered_at", models.DateTimeField(blank=True, null=True, verbose_name="恢复时间")),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="iwork.alertrule")),
            ],
            options={
                "db_table": "alert_event",
                "indexes": [models.Index(fields=["business_date", "status"], name="idx_alert_event_state")],
                "constraints": [models.UniqueConstraint(fields=("rule", "business_date", "dimension_key"), name="uq_alert_event_dimension")],
            },
        ),
        migrations.CreateModel(
            name="AlertSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(max_length=255, verbose_name="订阅人subject")),
                ("scope_type", models.CharField(default="none", max_length=32, verbose_name="范围类型")),
                ("scope_value", models.CharField(blank=True, default="", max_length=120, verbose_name="范围值")),
                ("enabled", models.BooleanField(default=True, verbose_name="是否启用")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subscriptions", to="iwork.alertrule")),
            ],
            options={
                "db_table": "alert_subscription",
                "constraints": [models.UniqueConstraint(fields=("subject", "rule", "scope_type", "scope_value"), name="uq_alert_subscription_scope")],
            },
        ),
        migrations.CreateModel(
            name="AlertAudience",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("audience_type", models.CharField(max_length=16, verbose_name="受众类型")),
                ("audience_key", models.CharField(max_length=255, verbose_name="受众键")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audiences", to="iwork.alertevent")),
            ],
            options={
                "db_table": "alert_audience",
                "constraints": [models.UniqueConstraint(fields=("event", "audience_type", "audience_key"), name="uq_alert_audience")],
            },
        ),
        migrations.CreateModel(
            name="NotificationReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(max_length=255, verbose_name="收件人subject")),
                ("read_revision", models.PositiveIntegerField(default=0, verbose_name="已读修订号")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="已读时间")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="receipts", to="iwork.alertevent")),
            ],
            options={
                "db_table": "notification_receipt",
                "constraints": [models.UniqueConstraint(fields=("event", "subject"), name="uq_notification_receipt")],
            },
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel", models.CharField(default="in_app", max_length=32, verbose_name="渠道")),
                ("event_revision", models.PositiveIntegerField(default=1, verbose_name="待投递事件修订号")),
                ("status", models.CharField(choices=[("pending", "待投递"), ("sending", "投递中"), ("sent", "已投递"), ("failed", "失败")], default="pending", max_length=16, verbose_name="状态")),
                ("attempt_count", models.PositiveIntegerField(default=0, verbose_name="尝试次数")),
                ("next_retry_at", models.DateTimeField(blank=True, null=True, verbose_name="下次重试时间")),
                ("last_error", models.TextField(blank=True, default="", verbose_name="最后错误")),
                ("sent_at", models.DateTimeField(blank=True, null=True, verbose_name="投递时间")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("audience", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="iwork.alertaudience")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="iwork.alertevent")),
            ],
            options={
                "db_table": "notification_delivery",
                "constraints": [models.UniqueConstraint(fields=("event", "channel", "audience"), name="uq_notification_delivery")],
            },
        ),
    ]
