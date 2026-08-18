"""独立警报队列使用的Celery任务。"""

from datetime import date, timedelta

from celery import shared_task
from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from loguru import logger

from iwork.alert_models import NotificationDelivery
from iwork.alerts.notification_events import publish_notification_wakeup
from iwork.alerts.service import AlertService
from iwork.read_model.errors import ReadModelNotReadyError
from iwork.read_model.store import SnapshotStore
from iwork.statistics import get_business_date
from iwork.target_responsibility import list_target_obligations_for_alerts


# ======
# 警报任务配置
LOCAL_DB_ALIAS = "iwork_local"
DELIVERY_LEASE_MINUTES = 5
DELIVERY_BATCH_SIZE = 200


def _claim_notification_deliveries(now):
    """事务性领取一批待投递记录，避免多个Worker重复发布。"""
    retryable = (
        Q(status=NotificationDelivery.Status.PENDING)
        | Q(status=NotificationDelivery.Status.FAILED, next_retry_at__lte=now)
        | Q(status=NotificationDelivery.Status.SENDING, next_retry_at__lte=now)
    )
    with transaction.atomic(using=LOCAL_DB_ALIAS):
        deliveries = list(
            NotificationDelivery.objects.using(LOCAL_DB_ALIAS)
            .select_for_update(skip_locked=True)
            .filter(retryable)
            .select_related("audience", "event")
            .order_by("created_at")[:DELIVERY_BATCH_SIZE]
        )
        lease_until = now + timedelta(minutes=DELIVERY_LEASE_MINUTES)
        for delivery in deliveries:
            delivery.status = NotificationDelivery.Status.SENDING
            delivery.next_retry_at = lease_until
            delivery.save(
                using=LOCAL_DB_ALIAS,
                update_fields=["status", "next_retry_at", "updated_at"],
            )
    return deliveries


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="alerts",
)
def evaluate_published_snapshot_task(
    self,
    business_date_text: str,
    snapshot_version: str,
) -> dict[str, object]:
    """异步评估一份已成功发布的实时快照。

    Args:
        business_date_text: ISO格式曼谷业务日期。
        snapshot_version: 已切换为current的版本。

    Returns:
        dict[str, object]: 可记录的评估摘要。
    """
    result = AlertService().evaluate_published_snapshot(
        date.fromisoformat(business_date_text),
        snapshot_version,
    )
    return {
        "business_date": result.business_date.isoformat(),
        "snapshot_version": result.snapshot_version,
        "event_count": result.event_count,
    }


@shared_task(queue="alerts")
def reconcile_target_obligations_task() -> dict[str, object]:
    """每分钟补偿目标责任并评估逾期与恢复。"""
    business_date = get_business_date()
    obligations = list_target_obligations_for_alerts(business_date)
    result = AlertService().evaluate_target_submission_overdue(business_date)
    return {
        "business_date": business_date.isoformat(),
        "obligation_count": len(obligations),
        "overdue_count": result.event_count,
    }


@shared_task(queue="alerts")
def reconcile_alerts_task() -> dict[str, int]:
    """补偿当前快照评估并重试未完成站内投递。"""
    business_date = get_business_date()
    try:
        metadata = SnapshotStore().read_metadata(business_date).metadata
        snapshot_version = str(metadata.get("snapshot_version", "")).strip()
        if snapshot_version:
            AlertService().evaluate_published_snapshot(business_date, snapshot_version)
    except ReadModelNotReadyError:
        logger.info("当前快照尚未准备好，本轮警报评估补偿跳过: {}", business_date)

    now = timezone.now()
    deliveries = _claim_notification_deliveries(now)
    sent = 0
    failed = 0
    for delivery in deliveries:
        audience = delivery.audience
        try:
            publish_notification_wakeup(
                subjects=[audience.audience_key] if audience.audience_type == "subject" else [],
                include_admins=(audience.audience_type == "role" and audience.audience_key == "admin"),
            )
            delivery.status = NotificationDelivery.Status.SENT
            delivery.attempt_count += 1
            delivery.sent_at = now
            delivery.next_retry_at = None
            delivery.last_error = ""
            sent += 1
        except Exception as exc:
            delivery.status = NotificationDelivery.Status.FAILED
            delivery.attempt_count += 1
            delivery.next_retry_at = now + timedelta(minutes=min(30, 2 ** min(delivery.attempt_count, 4)))
            delivery.last_error = str(exc)[:1000]
            failed += 1
        delivery.save(using=LOCAL_DB_ALIAS)
    return {"sent": sent, "failed": failed}
