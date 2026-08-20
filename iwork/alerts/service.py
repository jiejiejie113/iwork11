"""警报评估编排服务。"""

from dataclasses import dataclass
from collections.abc import Callable, Mapping
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from iwork.alert_models import (
    AlertAudience,
    AlertEvaluationRun,
    AlertEvent,
    AlertRule,
    NotificationDelivery,
)
from iwork.alerts.contracts import AlertCandidate, AlertDetector, EvaluationContext
from iwork.local_models import DailyTargetObligation


# ======
# 警报持久化与内置规则配置
LOCAL_DB_ALIAS = "iwork_local"
TARGET_OVERDUE_RULE_CODE = "target_submission_overdue"
DAILY_SUMMARY_RULE_CODE = "daily_responsibility_summary"
DATA_WATERMARK_RULE_CODE = "data_watermark_anomaly"


@dataclass(frozen=True)
class EvaluationResult:
    """一次已发布快照的警报评估摘要。"""

    business_date: date
    snapshot_version: str
    event_count: int


class AlertService:
    """在不阻塞快照发布的前提下幂等评估警报。"""

    def __init__(
        self,
        *,
        detectors: Mapping[str, AlertDetector] | None = None,
        snapshot_loader: Callable[[date, str], tuple[dict, dict | None]] | None = None,
    ) -> None:
        """注入检测器和快照读取器，默认仅保留禁用的水位扩展点。

        Args:
            detectors (Mapping[str, AlertDetector] | None): 按规则编码索引的检测器。
            snapshot_loader (Callable | None): 按日期和版本读取快照的函数。
        """
        self.detectors = dict(detectors or {})
        self.snapshot_loader = snapshot_loader or (lambda _date, _version: ({}, None))

    def evaluate_published_snapshot(
        self,
        business_date: date,
        snapshot_version: str,
    ) -> EvaluationResult:
        """评估一份已发布快照。

        水位异常规则在口径明确前保持禁用。该方法仍持久化唯一运行记录，
        保证Celery至少一次执行不会产生重复评估。

        Args:
            business_date: 快照所属曼谷业务日期。
            snapshot_version: 已切换为 current 的快照版本。

        Returns:
            EvaluationResult: 本轮日期、版本和事件数量。

        Raises:
            Exception: 快照读取、检测或持久化失败时原样抛出。
        """
        rules = self.ensure_builtin_rules()
        with transaction.atomic(using=LOCAL_DB_ALIAS):
            run, created = AlertEvaluationRun.objects.using(LOCAL_DB_ALIAS).select_for_update().get_or_create(
                business_date=business_date,
                snapshot_version=snapshot_version,
                defaults={"status": "running", "event_count": 0},
            )
            if not created and run.status == "completed":
                return EvaluationResult(run.business_date, run.snapshot_version, run.event_count)
            if (
                not created
                and run.status == "running"
                and run.started_at > timezone.now() - timedelta(minutes=5)
            ):
                return EvaluationResult(run.business_date, run.snapshot_version, run.event_count)
            run.status = "running"
            run.error_message = ""
            run.save(using=LOCAL_DB_ALIAS, update_fields=["status", "error_message", "completed_at"])
        event_count = 0
        try:
            active_detectors = {
                code: detector
                for code, detector in self.detectors.items()
                if code in rules and rules[code].enabled
            }
            if active_detectors:
                current_snapshot, previous_snapshot = self.snapshot_loader(
                    business_date,
                    snapshot_version,
                )
                context = EvaluationContext(business_date, snapshot_version)
                for code, detector in active_detectors.items():
                    candidates = detector.evaluate(current_snapshot, previous_snapshot, context)
                    for candidate in candidates:
                        if candidate.rule_code != code or candidate.business_date != business_date:
                            continue
                        self._materialize_candidate(rules[code], candidate, snapshot_version)
                        event_count += 1
            run.status = "completed"
            run.event_count = event_count
            run.save(using=LOCAL_DB_ALIAS, update_fields=["status", "event_count", "completed_at"])
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:1000]
            run.save(using=LOCAL_DB_ALIAS, update_fields=["status", "error_message", "completed_at"])
            raise
        return EvaluationResult(
            business_date=run.business_date,
            snapshot_version=run.snapshot_version,
            event_count=run.event_count,
        )

    def _materialize_candidate(
        self,
        rule: AlertRule,
        candidate: AlertCandidate,
        snapshot_version: str,
    ) -> AlertEvent:
        """把测试或后续正式检测器候选幂等转换为事件、受众和投递。

        Args:
            rule (AlertRule): 候选对应的警报规则。
            candidate (AlertCandidate): 检测器生成的警报候选。
            snapshot_version (str): 候选来源快照版本。

        Returns:
            AlertEvent: 创建或更新后的警报事件。
        """
        with transaction.atomic(using=LOCAL_DB_ALIAS):
            event, created = AlertEvent.objects.using(LOCAL_DB_ALIAS).get_or_create(
                rule=rule,
                business_date=candidate.business_date,
                dimension_key=candidate.dimension_key,
                defaults={
                    "snapshot_version": snapshot_version,
                    "severity": rule.severity,
                    "title": rule.name,
                    "message": str(candidate.payload.get("message", rule.name)),
                    "payload": candidate.payload,
                },
            )
            if not created:
                event = AlertEvent.objects.using(LOCAL_DB_ALIAS).select_for_update().get(pk=event.pk)
                event.snapshot_version = snapshot_version
                event.payload = candidate.payload
                event.last_seen_at = timezone.now()
                event.occurrence_count += 1
                event.save(using=LOCAL_DB_ALIAS)
            for role in rule.mandatory_roles:
                audience, _ = AlertAudience.objects.using(LOCAL_DB_ALIAS).get_or_create(
                    event=event,
                    audience_type="role",
                    audience_key=role,
                )
                NotificationDelivery.objects.using(LOCAL_DB_ALIAS).get_or_create(
                    event=event,
                    audience=audience,
                    channel="in_app",
                    defaults={"event_revision": event.revision},
                )
        return event

    def ensure_builtin_rules(self) -> dict[str, AlertRule]:
        """幂等创建首版启用规则和禁用的水位预留规则。

        Returns:
            dict[str, AlertRule]: 按规则编码索引的内置规则。
        """
        target_rule, _ = AlertRule.objects.using(LOCAL_DB_ALIAS).get_or_create(
            code=TARGET_OVERDUE_RULE_CODE,
            defaults={
                "name": "每日目标逾期未填",
                "severity": "warning",
                "detector_type": TARGET_OVERDUE_RULE_CODE,
                "allowed_roles": ["admin"],
                "scope_type": "flow",
                "mandatory_roles": ["admin"],
                "cooldown_seconds": 300,
                "enabled": True,
            },
        )
        daily_rule, _ = AlertRule.objects.using(LOCAL_DB_ALIAS).get_or_create(
            code=DAILY_SUMMARY_RULE_CODE,
            defaults={
                "name": "每日责任摘要",
                "severity": "warning",
                "detector_type": DAILY_SUMMARY_RULE_CODE,
                "allowed_roles": ["admin"],
                "scope_type": "none",
                "mandatory_roles": ["admin"],
                "cooldown_seconds": 0,
                "enabled": True,
            },
        )
        watermark_rule, _ = AlertRule.objects.using(LOCAL_DB_ALIAS).get_or_create(
            code=DATA_WATERMARK_RULE_CODE,
            defaults={
                "name": "数据水位异常",
                "severity": "warning",
                "detector_type": DATA_WATERMARK_RULE_CODE,
                "allowed_roles": ["admin", "leader"],
                "scope_type": "flow",
                "mandatory_roles": [],
                "enabled": False,
            },
        )
        return {
            target_rule.code: target_rule,
            daily_rule.code: daily_rule,
            watermark_rule.code: watermark_rule,
        }

    def evaluate_target_submission_overdue(self, business_date: date) -> EvaluationResult:
        """评估并恢复指定业务日的目标逾期事件。

        Args:
            business_date: 待检查的曼谷业务日期。

        Returns:
            EvaluationResult: 本轮仍处于异常中的事件数量。
        """
        rule = self.ensure_builtin_rules()[TARGET_OVERDUE_RULE_CODE]
        if not rule.enabled:
            return EvaluationResult(business_date, "target-obligation", 0)
        overdue_flows = set(
            DailyTargetObligation.objects.using(LOCAL_DB_ALIAS)
            .filter(target_date=business_date, status="overdue")
            .values_list("flow_name", flat=True)
        )
        now = timezone.now()
        with transaction.atomic(using=LOCAL_DB_ALIAS):
            for flow_name in sorted(overdue_flows):
                event, created = AlertEvent.objects.using(LOCAL_DB_ALIAS).get_or_create(
                    rule=rule,
                    business_date=business_date,
                    dimension_key=flow_name,
                    defaults={
                        "severity": rule.severity,
                        "title": "生产组目标逾期未填",
                        "message": f"生产组 {flow_name} 尚未提交今日目标。",
                        "payload": {"flow": flow_name},
                    },
                )
                if not created:
                    event = AlertEvent.objects.using(LOCAL_DB_ALIAS).select_for_update().get(pk=event.pk)
                if not created and event.status == AlertEvent.Status.RECOVERED:
                    event.status = AlertEvent.Status.OPEN
                    event.recovered_at = None
                    event.revision += 1
                    event.occurrence_count += 1
                    event.save(using=LOCAL_DB_ALIAS)
                elif not created:
                    event.occurrence_count += 1
                    event.save(using=LOCAL_DB_ALIAS, update_fields=["occurrence_count", "last_seen_at"])
                self._ensure_admin_delivery(event)

            open_events = AlertEvent.objects.using(LOCAL_DB_ALIAS).select_for_update().filter(
                rule=rule,
                business_date=business_date,
                status=AlertEvent.Status.OPEN,
            )
            for event in open_events.exclude(dimension_key__in=overdue_flows):
                event.status = AlertEvent.Status.RECOVERED
                event.recovered_at = now
                event.revision += 1
                event.message = f"生产组 {event.dimension_key} 的目标已完成补填。"
                event.save(using=LOCAL_DB_ALIAS)
                self._ensure_admin_delivery(event, reset=True)
        return EvaluationResult(
            business_date=business_date,
            snapshot_version="target-obligation",
            event_count=len(overdue_flows),
        )

    def evaluate_daily_responsibility_summary(self, business_date: date) -> EvaluationResult:
        """评估并维护指定业务日的每日责任摘要事件。

        只要当日存在未填写（待提交或已逾期）责任，就生成一条管理员可见的
        汇总事件；全部填写或豁免后转为已恢复。每条事件按业务日去重。

        Args:
            business_date: 待检查的曼谷业务日期。

        Returns:
            EvaluationResult: 本轮未填写生产组数量。
        """
        rule = self.ensure_builtin_rules()[DAILY_SUMMARY_RULE_CODE]
        if not rule.enabled:
            return EvaluationResult(business_date, "daily-summary", 0)
        obligations = list(
            DailyTargetObligation.objects.using(LOCAL_DB_ALIAS)
            .filter(target_date=business_date)
            .prefetch_related("leader_links")
            .order_by("flow_name")
        )
        status_order = ("pending", "overdue", "fulfilled", "fulfilled_late", "waived")
        status_counts = {name: 0 for name in status_order}
        flows = []
        for obligation in obligations:
            status_counts[obligation.status] = status_counts.get(obligation.status, 0) + 1
            flows.append({
                "flow": obligation.flow_name,
                "status": obligation.status,
                "deadline_at": obligation.deadline_at.isoformat(),
                "leaders": [link.username for link in obligation.leader_links.all()],
            })
        unfilled = [item for item in flows if item["status"] in ("pending", "overdue")]
        payload = {
            "type": "daily_summary",
            "business_date": business_date.isoformat(),
            "status_counts": status_counts,
            "flows": flows,
        }
        now = timezone.now()
        with transaction.atomic(using=LOCAL_DB_ALIAS):
            event = (
                AlertEvent.objects.using(LOCAL_DB_ALIAS)
                .select_for_update()
                .filter(rule=rule, business_date=business_date, dimension_key="daily")
                .first()
            )
            if unfilled:
                message = "今日 {count} 个生产组未填写目标，其中 {overdue} 个已逾期。".format(
                    count=len(unfilled),
                    overdue=status_counts.get("overdue", 0),
                )
                if event is None:
                    event = AlertEvent.objects.using(LOCAL_DB_ALIAS).create(
                        rule=rule,
                        business_date=business_date,
                        dimension_key="daily",
                        severity=rule.severity,
                        title="每日责任摘要",
                        message=message,
                        payload=payload,
                    )
                else:
                    if event.status == AlertEvent.Status.RECOVERED:
                        event.status = AlertEvent.Status.OPEN
                        event.recovered_at = None
                        event.revision += 1
                    event.title = "每日责任摘要"
                    event.message = message
                    event.payload = payload
                    event.occurrence_count += 1
                    event.last_seen_at = now
                    event.save(using=LOCAL_DB_ALIAS)
                self._ensure_admin_delivery(event)
            elif event is not None and event.status == AlertEvent.Status.OPEN:
                event.status = AlertEvent.Status.RECOVERED
                event.recovered_at = now
                event.revision += 1
                event.message = "当日目标已全部填写。"
                event.save(using=LOCAL_DB_ALIAS)
                self._ensure_admin_delivery(event, reset=True)
        return EvaluationResult(
            business_date=business_date,
            snapshot_version="daily-summary",
            event_count=len(unfilled),
        )

    def _ensure_admin_delivery(self, event: AlertEvent, *, reset: bool = False) -> None:
        """创建或刷新管理员角色的站内投递。

        Args:
            event: 待投递事件。
            reset: 是否因事件修订而重新进入待投递状态。
        """
        audience, _ = AlertAudience.objects.using(LOCAL_DB_ALIAS).get_or_create(
            event=event,
            audience_type="role",
            audience_key="admin",
        )
        delivery, _ = NotificationDelivery.objects.using(LOCAL_DB_ALIAS).get_or_create(
            event=event,
            audience=audience,
            channel="in_app",
            defaults={"event_revision": event.revision},
        )
        if reset or delivery.event_revision != event.revision:
            delivery.event_revision = event.revision
            delivery.status = NotificationDelivery.Status.PENDING
            delivery.sent_at = None
            delivery.last_error = ""
            delivery.save(using=LOCAL_DB_ALIAS)
