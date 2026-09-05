"""警报模块公共接口测试。"""

import asyncio
from datetime import date

import pytest
from django.utils import timezone


def test_alert_service_exposes_snapshot_evaluation_interface():
    """警报服务应提供幂等快照评估公共接口。"""
    from iwork.alerts.service import AlertService

    assert callable(AlertService().evaluate_published_snapshot)


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_snapshot_evaluation_accepts_business_date_and_version():
    """禁用水位规则时快照评估仍应记录成功结果。"""
    from iwork.alerts.service import AlertService

    result = AlertService().evaluate_published_snapshot(
        date(2026, 8, 18),
        "snapshot-v1",
    )

    assert result.business_date == date(2026, 8, 18)
    assert result.snapshot_version == "snapshot-v1"
    assert result.event_count == 0


@pytest.mark.asyncio
async def test_notification_broker_only_wakes_matching_subject_or_admin():
    """通知唤醒只应发送给明确收件人或管理员角色。"""
    from iwork.alerts.notification_events import NotificationWakeupBroker

    broker = NotificationWakeupBroker()
    async with (
        broker.subscribe("leader-subject", is_admin=False) as leader_queue,
        broker.subscribe("other-subject", is_admin=False) as other_queue,
        broker.subscribe("admin-subject", is_admin=True) as admin_queue,
    ):
        broker.broadcast(subjects={"leader-subject"}, include_admins=True)

        assert await leader_queue.get() == {"type": "notification_changed"}
        assert await admin_queue.get() == {"type": "notification_changed"}
        with pytest.raises(asyncio.QueueEmpty):
            other_queue.get_nowait()


@pytest.mark.asyncio
async def test_notification_broker_keeps_only_latest_wakeup():
    """慢客户端队列容量应为一且只保留最新唤醒。"""
    from iwork.alerts.notification_events import NotificationWakeupBroker

    broker = NotificationWakeupBroker()
    async with broker.subscribe("leader-subject", is_admin=False) as queue:
        broker.broadcast(subjects={"leader-subject"})
        broker.broadcast(subjects={"leader-subject"})

        assert queue.qsize() == 1
        assert await queue.get() == {"type": "notification_changed"}


@pytest.mark.asyncio
async def test_notification_broker_isolates_fifty_concurrent_connections():
    """五十个连接中只有匹配受众收到唤醒且队列均不积压。"""
    from contextlib import AsyncExitStack

    from iwork.alerts.notification_events import NotificationWakeupBroker

    broker = NotificationWakeupBroker()
    async with AsyncExitStack() as stack:
        queues = [
            await stack.enter_async_context(broker.subscribe(f"subject-{index}", is_admin=False))
            for index in range(50)
        ]
        broker.broadcast(subjects={"subject-17"})

        assert queues[17].qsize() == 1
        assert sum(queue.qsize() for queue in queues) == 1


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_snapshot_evaluation_is_idempotent_per_date_and_version():
    """重复评估同一业务日期和快照版本只能保留一个运行记录。"""
    from iwork.alert_models import AlertEvaluationRun
    from iwork.alerts.service import AlertService

    service = AlertService()
    first = service.evaluate_published_snapshot(date(2026, 8, 18), "snapshot-v1")
    second = service.evaluate_published_snapshot(date(2026, 8, 18), "snapshot-v1")

    assert first.event_count == second.event_count == 0
    assert AlertEvaluationRun.objects.using("iwork_local").count() == 1


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_injected_detector_materializes_event_audience_and_delivery():
    """测试检测器应验证快照评估到站内投递的完整框架链路。"""
    from iwork.alert_models import AlertAudience, AlertEvent, NotificationDelivery
    from iwork.alerts.contracts import AlertCandidate
    from iwork.alerts.service import AlertService

    class TestDetector:
        """返回一个稳定的测试异常候选。"""

        def evaluate(self, current_snapshot, previous_snapshot, context):
            """确认快照输入后返回测试候选。"""
            assert current_snapshot == {"value": 2}
            assert previous_snapshot == {"value": 1}
            return [AlertCandidate(
                rule_code="data_watermark_anomaly",
                business_date=context.business_date,
                dimension_key="SO3-L3A",
                payload={"flow": "SO3-L3A", "message": "测试水位异常"},
            )]

    service = AlertService(
        detectors={"data_watermark_anomaly": TestDetector()},
        snapshot_loader=lambda _date, _version: ({"value": 2}, {"value": 1}),
    )
    rule = service.ensure_builtin_rules()["data_watermark_anomaly"]
    rule.enabled = True
    rule.mandatory_roles = ["admin"]
    rule.save(using="iwork_local", update_fields=["enabled", "mandatory_roles"])

    result = service.evaluate_published_snapshot(date(2026, 8, 18), "snapshot-v2")

    event = AlertEvent.objects.using("iwork_local").get()
    assert result.event_count == 1
    assert event.snapshot_version == "snapshot-v2"
    assert event.message == "测试水位异常"
    assert AlertAudience.objects.using("iwork_local").filter(
        event=event,
        audience_type="role",
        audience_key="admin",
    ).exists()
    assert NotificationDelivery.objects.using("iwork_local").filter(event=event).exists()


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_target_overdue_event_is_deduplicated_and_recovers_after_late_submit():
    """同一Flow持续逾期只产生一个事件，逾期补填后原事件转为恢复。"""
    from iwork.alert_models import AlertAudience, AlertEvent, NotificationDelivery
    from iwork.alerts.service import AlertService
    from iwork.local_models import DailyTargetObligation

    obligation = DailyTargetObligation.objects.using("iwork_local").create(
        target_date=date(2026, 8, 18),
        flow_name="SO3-L3A",
        deadline_at=timezone.now(),
        status="overdue",
    )
    service = AlertService()

    service.evaluate_target_submission_overdue(date(2026, 8, 18))
    service.evaluate_target_submission_overdue(date(2026, 8, 18))

    event = AlertEvent.objects.using("iwork_local").get()
    assert event.status == "open"
    assert event.occurrence_count == 2
    assert AlertAudience.objects.using("iwork_local").filter(
        event=event,
        audience_type="role",
        audience_key="admin",
    ).count() == 1
    deliveries = list(
        NotificationDelivery.objects.using("iwork_local")
        .filter(event=event)
        .select_related("audience")
    )
    assert {delivery.audience.audience_key for delivery in deliveries} == {
        "admin",
        "iwork_admin",
    }

    obligation.status = "fulfilled_late"
    obligation.save(using="iwork_local", update_fields=["status"])
    service.evaluate_target_submission_overdue(date(2026, 8, 18))

    event.refresh_from_db(using="iwork_local")
    assert event.status == "recovered"
    assert event.recovered_at is not None
    deliveries = list(
        NotificationDelivery.objects.using("iwork_local")
        .filter(event=event)
        .select_related("audience")
    )
    assert len(deliveries) == 2
    assert all(delivery.event_revision == event.revision == 2 for delivery in deliveries)
    assert all(delivery.status == "pending" for delivery in deliveries)
