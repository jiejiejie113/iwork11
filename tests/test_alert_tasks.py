"""警报独立队列和补偿任务测试。"""

from datetime import date
from unittest.mock import patch

import pytest


def test_alert_tasks_are_routed_to_independent_queue():
    """警报任务必须路由到alerts队列且不占用实时采集队列。"""
    from iwork.celery import app

    assert app.conf.task_routes["iwork.alerts.tasks.*"] == {"queue": "alerts"}
    assert app.conf.beat_schedule["reconcile-target-obligations-every-minute"]["options"] == {
        "queue": "alerts",
    }


def test_minute_task_compensates_obligations_before_evaluating_overdue():
    """每分钟任务应先生成责任，再评估逾期事件。"""
    from iwork.alerts.tasks import reconcile_target_obligations_task

    with (
        patch("iwork.alerts.tasks.get_business_date", return_value=date(2026, 8, 18)),
        patch("iwork.alerts.tasks.list_target_obligations_for_alerts", return_value=[object()]) as obligations,
        patch("iwork.alerts.tasks.AlertService") as service,
    ):
        service.return_value.evaluate_target_submission_overdue.return_value.event_count = 1
        result = reconcile_target_obligations_task()

    obligations.assert_called_once_with(date(2026, 8, 18))
    service.return_value.evaluate_target_submission_overdue.assert_called_once_with(date(2026, 8, 18))
    assert result == {
        "business_date": "2026-08-18",
        "obligation_count": 1,
        "overdue_count": 1,
    }


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_delivery_reconcile_publishes_role_wakeup_once():
    """待投递管理员受众应发布通用唤醒并转为已投递。"""
    from iwork.alert_models import AlertAudience, AlertEvent, NotificationDelivery
    from iwork.alerts.service import AlertService
    from iwork.alerts.tasks import reconcile_alerts_task

    rule = AlertService().ensure_builtin_rules()["target_submission_overdue"]
    event = AlertEvent.objects.using("iwork_local").create(
        rule=rule,
        business_date=date(2026, 8, 18),
        dimension_key="SO3-L3A",
        title="逾期",
        message="逾期",
    )
    audience = AlertAudience.objects.using("iwork_local").create(
        event=event,
        audience_type="role",
        audience_key="admin",
    )
    delivery = NotificationDelivery.objects.using("iwork_local").create(event=event, audience=audience)

    with (
        patch("iwork.alerts.tasks.get_business_date", return_value=date(2026, 8, 18)),
        patch("iwork.alerts.tasks.SnapshotStore") as store,
        patch("iwork.alerts.tasks.publish_notification_wakeup", return_value=1) as publish,
    ):
        store.return_value.read_metadata.side_effect = Exception("skip")
        with pytest.raises(Exception, match="skip"):
            reconcile_alerts_task()

    delivery.refresh_from_db(using="iwork_local")
    assert delivery.status == "pending"
    publish.assert_not_called()

    from iwork.read_model.errors import ReadModelNotReadyError

    with (
        patch("iwork.alerts.tasks.get_business_date", return_value=date(2026, 8, 18)),
        patch("iwork.alerts.tasks.SnapshotStore") as store,
        patch("iwork.alerts.tasks.publish_notification_wakeup", return_value=1) as publish,
    ):
        store.return_value.read_metadata.side_effect = ReadModelNotReadyError("not ready")
        result = reconcile_alerts_task()

    publish.assert_called_once_with(subjects=[], include_admins=True)
    delivery.refresh_from_db(using="iwork_local")
    assert delivery.status == "sent"
    assert result == {"sent": 1, "failed": 0}

    with (
        patch("iwork.alerts.tasks.get_business_date", return_value=date(2026, 8, 18)),
        patch("iwork.alerts.tasks.SnapshotStore") as store,
        patch("iwork.alerts.tasks.publish_notification_wakeup", return_value=1) as second_publish,
    ):
        store.return_value.read_metadata.side_effect = ReadModelNotReadyError("not ready")
        second_result = reconcile_alerts_task()

    second_publish.assert_not_called()
    assert second_result == {"sent": 0, "failed": 0}
