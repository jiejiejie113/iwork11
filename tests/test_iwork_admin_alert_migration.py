"""iwork 专属管理员警报受众迁移测试。"""

from datetime import date
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_iwork_admin_alert_migration_backfills_builtin_events_idempotently():
    """升级前的内置事件应补齐受众和投递且不改动已有管理员记录。"""
    from iwork.alert_models import (
        AlertAudience,
        AlertEvent,
        AlertRule,
        NotificationDelivery,
    )

    target_rule = AlertRule.objects.using("iwork_local").create(
        code="target_submission_overdue",
        name="目标逾期",
        detector_type="target_submission_overdue",
        mandatory_roles=["admin"],
    )
    unrelated_rule = AlertRule.objects.using("iwork_local").create(
        code="unrelated_rule",
        name="其他规则",
        detector_type="unrelated_rule",
    )
    target_event = AlertEvent.objects.using("iwork_local").create(
        rule=target_rule,
        business_date=date(2026, 9, 5),
        dimension_key="SO3-L3A",
        revision=3,
        title="目标逾期",
        message="目标逾期",
    )
    unrelated_event = AlertEvent.objects.using("iwork_local").create(
        rule=unrelated_rule,
        business_date=date(2026, 9, 5),
        dimension_key="other",
        title="其他规则",
        message="其他规则",
    )
    admin_audience = AlertAudience.objects.using("iwork_local").create(
        event=target_event,
        audience_type="role",
        audience_key="admin",
    )
    admin_delivery = NotificationDelivery.objects.using("iwork_local").create(
        event=target_event,
        audience=admin_audience,
        event_revision=2,
        status=NotificationDelivery.Status.SENT,
    )

    migration = import_module(
        "iwork.migrations.0013_backfill_iwork_admin_alert_audiences"
    )
    schema_editor = SimpleNamespace(
        connection=SimpleNamespace(alias="iwork_local")
    )

    migration.backfill_iwork_admin_alert_audiences(django_apps, schema_editor)
    migration.backfill_iwork_admin_alert_audiences(django_apps, schema_editor)

    iwork_audiences = AlertAudience.objects.using("iwork_local").filter(
        event=target_event,
        audience_type="role",
        audience_key="iwork_admin",
    )
    assert iwork_audiences.count() == 1
    assert AlertAudience.objects.using("iwork_local").filter(
        event=unrelated_event,
        audience_type="role",
        audience_key="iwork_admin",
    ).count() == 0
    assert AlertAudience.objects.using("iwork_local").filter(
        event=target_event,
        audience_type="role",
        audience_key="admin",
    ).count() == 1
    assert NotificationDelivery.objects.using("iwork_local").filter(
        event=target_event,
        audience__audience_key="iwork_admin",
    ).values_list("event_revision", flat=True).get() == 3
    admin_delivery.refresh_from_db(using="iwork_local")
    assert admin_delivery.status == NotificationDelivery.Status.SENT
    assert admin_delivery.event_revision == 2
