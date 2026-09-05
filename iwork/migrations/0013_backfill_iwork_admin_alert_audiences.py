"""为升级前已存在的内置警报事件补齐 iwork 专属管理员受众。"""

from django.db import migrations


# ======
# 数据迁移配置
BUILTIN_RULE_CODES = (
    "target_submission_overdue",
    "daily_responsibility_summary",
)
IWORK_ADMIN_ROLE = "iwork_admin"


def backfill_iwork_admin_alert_audiences(apps, schema_editor):
    """为已有内置警报事件幂等创建专属管理员受众和投递记录。

    Args:
        apps: Django迁移时提供的历史模型注册表。
        schema_editor: 当前数据库连接的迁移编辑器。
    """
    database_alias = schema_editor.connection.alias
    if database_alias != "iwork_local":
        return

    alert_rule = apps.get_model("iwork", "AlertRule")
    alert_event = apps.get_model("iwork", "AlertEvent")
    alert_audience = apps.get_model("iwork", "AlertAudience")
    notification_delivery = apps.get_model("iwork", "NotificationDelivery")
    rule_ids = list(
        alert_rule.objects.using(database_alias)
        .filter(code__in=BUILTIN_RULE_CODES)
        .values_list("id", flat=True)
    )
    if not rule_ids:
        return

    events = (
        alert_event.objects.using(database_alias)
        .filter(rule_id__in=rule_ids)
        .only("id", "revision")
    )
    for event in events.iterator():
        audience, _ = alert_audience.objects.using(database_alias).get_or_create(
            event_id=event.pk,
            audience_type="role",
            audience_key=IWORK_ADMIN_ROLE,
        )
        notification_delivery.objects.using(database_alias).get_or_create(
            event_id=event.pk,
            audience_id=audience.pk,
            channel="in_app",
            defaults={"event_revision": event.revision},
        )


def remove_iwork_admin_alert_audiences(apps, schema_editor):
    """回滚迁移创建的内置警报专属管理员受众及其投递记录。

    Args:
        apps: Django迁移时提供的历史模型注册表。
        schema_editor: 当前数据库连接的迁移编辑器。
    """
    database_alias = schema_editor.connection.alias
    if database_alias != "iwork_local":
        return

    alert_rule = apps.get_model("iwork", "AlertRule")
    alert_audience = apps.get_model("iwork", "AlertAudience")
    rule_ids = list(
        alert_rule.objects.using(database_alias)
        .filter(code__in=BUILTIN_RULE_CODES)
        .values_list("id", flat=True)
    )
    if not rule_ids:
        return
    alert_audience.objects.using(database_alias).filter(
        event__rule_id__in=rule_ids,
        audience_type="role",
        audience_key=IWORK_ADMIN_ROLE,
    ).delete()


class Migration(migrations.Migration):
    """补齐内置警报事件的 iwork 专属管理员受众。"""

    dependencies = [
        ("iwork", "0012_iworkprincipal_is_iwork_admin"),
    ]

    operations = [
        migrations.RunPython(
            backfill_iwork_admin_alert_audiences,
            remove_iwork_admin_alert_audiences,
        ),
    ]
