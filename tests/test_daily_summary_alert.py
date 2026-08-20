"""每日责任摘要规则与管理员投递行为测试。"""

from datetime import date

import pytest
from django.utils import timezone


def _create_obligation(flow, status, leaders=()):
    """创建一条责任并附带组长快照。"""
    from iwork.local_models import DailyTargetObligation, DailyTargetObligationLeader, IworkPrincipal

    obligation = DailyTargetObligation.objects.using("iwork_local").create(
        target_date=date(2026, 8, 18),
        flow_name=flow,
        status=status,
        deadline_at=timezone.now(),
    )
    for index, username in enumerate(leaders):
        principal, _ = IworkPrincipal.objects.using("iwork_local").get_or_create(
            subject=f"subject-{flow}-{index}",
            defaults={"username": username},
        )
        DailyTargetObligationLeader.objects.using("iwork_local").get_or_create(
            obligation=obligation,
            principal=principal,
            defaults={"subject": principal.subject, "username": username},
        )
    return obligation


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_daily_summary_creates_single_admin_event_with_detail():
    """存在未填写责任时应生成一条含明细的管理员摘要事件。"""
    from iwork.alert_models import AlertAudience, AlertEvent, NotificationDelivery
    from iwork.alerts.service import AlertService

    _create_obligation("SO1", "pending", leaders=["组长甲"])
    _create_obligation("SO2", "overdue", leaders=["组长乙"])
    _create_obligation("SO3", "fulfilled")

    result = AlertService().evaluate_daily_responsibility_summary(date(2026, 8, 18))

    assert result.event_count == 2
    event = AlertEvent.objects.using("iwork_local").get(rule__code="daily_responsibility_summary")
    assert event.business_date == date(2026, 8, 18)
    assert event.status == "open"
    assert event.title == "每日责任摘要"
    assert "2 个生产组未填写目标" in event.message
    assert event.payload["status_counts"] == {
        "pending": 1,
        "overdue": 1,
        "fulfilled": 1,
        "fulfilled_late": 0,
        "waived": 0,
    }
    flows = {item["flow"]: item for item in event.payload["flows"]}
    assert set(flows) == {"SO1", "SO2", "SO3"}
    assert flows["SO1"]["leaders"] == ["组长甲"]
    assert flows["SO2"]["leaders"] == ["组长乙"]
    assert flows["SO3"]["leaders"] == []
    assert AlertAudience.objects.using("iwork_local").filter(
        event=event,
        audience_type="role",
        audience_key="admin",
    ).exists()
    assert NotificationDelivery.objects.using("iwork_local").filter(event=event).exists()


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_daily_summary_is_deduplicated_per_date():
    """同一业务日重复评估只能保留一条摘要事件。"""
    from iwork.alert_models import AlertEvent
    from iwork.alerts.service import AlertService

    _create_obligation("SO1", "overdue")

    AlertService().evaluate_daily_responsibility_summary(date(2026, 8, 18))
    AlertService().evaluate_daily_responsibility_summary(date(2026, 8, 18))

    events = AlertEvent.objects.using("iwork_local").filter(rule__code="daily_responsibility_summary")
    assert events.count() == 1
    assert events.get().occurrence_count == 2


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_daily_summary_recovers_when_all_filled():
    """责任全部填写后摘要事件应转为恢复并重新投递。"""
    from iwork.alert_models import AlertEvent, NotificationDelivery
    from iwork.alerts.service import AlertService

    obligation = _create_obligation("SO1", "overdue")
    service = AlertService()
    service.evaluate_daily_responsibility_summary(date(2026, 8, 18))

    obligation.status = "fulfilled_late"
    obligation.save(using="iwork_local", update_fields=["status"])
    service.evaluate_daily_responsibility_summary(date(2026, 8, 18))

    event = AlertEvent.objects.using("iwork_local").get(rule__code="daily_responsibility_summary")
    assert event.status == "recovered"
    assert event.recovered_at is not None
    assert event.message == "当日目标已全部填写。"
    assert event.payload["status_counts"] == {
        "pending": 0,
        "overdue": 0,
        "fulfilled": 0,
        "fulfilled_late": 1,
        "waived": 0,
    }
    assert event.payload["flows"] == [
        {
            "flow": "SO1",
            "status": "fulfilled_late",
            "deadline_at": obligation.deadline_at.isoformat(),
            "leaders": [],
        }
    ]
    delivery = NotificationDelivery.objects.using("iwork_local").get(event=event)
    assert delivery.event_revision == event.revision == 2
    assert delivery.status == "pending"


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_daily_summary_not_created_when_nothing_unfilled():
    """当日全部完成或豁免时不应产生摘要事件。"""
    from iwork.alert_models import AlertEvent
    from iwork.alerts.service import AlertService

    _create_obligation("SO1", "fulfilled")
    _create_obligation("SO2", "waived")

    result = AlertService().evaluate_daily_responsibility_summary(date(2026, 8, 18))

    assert result.event_count == 0
    assert not AlertEvent.objects.using("iwork_local").filter(
        rule__code="daily_responsibility_summary"
    ).exists()


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_daily_summary_reopens_after_recovery():
    """恢复后再次出现未填写责任应重新打开并递增修订号。"""
    from iwork.alert_models import AlertEvent
    from iwork.alerts.service import AlertService

    obligation = _create_obligation("SO1", "overdue")
    service = AlertService()
    service.evaluate_daily_responsibility_summary(date(2026, 8, 18))
    obligation.status = "fulfilled_late"
    obligation.save(using="iwork_local", update_fields=["status"])
    service.evaluate_daily_responsibility_summary(date(2026, 8, 18))

    obligation.status = "pending"
    obligation.save(using="iwork_local", update_fields=["status"])
    service.evaluate_daily_responsibility_summary(date(2026, 8, 18))

    event = AlertEvent.objects.using("iwork_local").get(rule__code="daily_responsibility_summary")
    assert event.status == "open"
    assert event.recovered_at is None
    assert event.revision == 3
