"""每日目标责任、权限和事务性保存服务。"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from iwork.identity import IworkIdentity
from iwork.local_models import (
    DailyTargetObligation,
    DailyTargetObligationLeader,
    GroupTargetAuditLog,
    GroupTargetProduction,
    IworkPrincipal,
    ManagedFlowAssignment,
    TargetSubmissionPolicy,
)
from iwork.statistics import get_business_date


# ======
# 本地目标责任配置
LOCAL_DB_ALIAS = 'iwork_local'


def _default_deadline_time() -> time:
    """读取统一配置的默认目标提交截止时间。

    Returns:
        time: 配置的无时区本地截止时间。

    Raises:
        ValueError: 配置值不是合法ISO时间。
    """
    return time.fromisoformat(settings.IWORK_TARGET_SUBMISSION_DEFAULT_DEADLINE)


class TargetResponsibilityError(Exception):
    """携带稳定错误码和 HTTP 状态的目标责任异常。"""

    def __init__(self, code: str, message: str, http_status: int = 400):
        """初始化业务异常。

        Args:
            code (str): 面向客户端的稳定错误码。
            message (str): 中文错误说明。
            http_status (int): 建议的 HTTP 状态码。
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def require_subject(identity: IworkIdentity | None) -> IworkIdentity:
    """要求请求身份具备稳定 subject。

    Args:
        identity (IworkIdentity | None): 请求身份。

    Returns:
        IworkIdentity: 已认证身份。

    Raises:
        TargetResponsibilityError: 身份缺失时抛出。
    """
    if identity is None or not identity.subject:
        raise TargetResponsibilityError('identity_required', '此接口需要可信用户身份', 401)
    return identity


def sync_principal(identity: IworkIdentity) -> IworkPrincipal:
    """把可信身份的最新展示属性同步到本地数据库。

    Args:
        identity (IworkIdentity): 待同步的可信身份。

    Returns:
        IworkPrincipal: 创建或更新后的本地用户。

    Raises:
        TargetResponsibilityError: 身份缺少稳定subject时抛出。
    """
    identity = require_subject(identity)
    principal, _ = IworkPrincipal.objects.using(LOCAL_DB_ALIAS).update_or_create(
        subject=identity.subject,
        defaults={
            'username': identity.username,
            'email': identity.email,
            'display_name': identity.display_name,
            'keycloak_groups': identity.keycloak_groups,
            'is_admin': identity.is_admin,
        },
    )
    return principal


def next_business_date(value: date) -> date:
    """返回仅排除周末的下一业务日。

    Args:
        value (date): 起算日期。

    Returns:
        date: 起算日期之后的首个工作日。
    """
    result = value + timedelta(days=1)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def active_assignment_query(target_date: date) -> models.Q:
    """构造指定日期有效的负责人条件。

    Args:
        target_date (date): 待判断分配有效性的日期。

    Returns:
        models.Q: 可组合到查询集的有效期条件。
    """
    return models.Q(effective_date__lte=target_date) & (
        models.Q(expires_date__isnull=True) | models.Q(expires_date__gte=target_date)
    )


def identity_can_manage_flow(
    identity: IworkIdentity,
    flow_name: str,
    target_date: date,
) -> bool:
    """判断管理员或有效组长能否管理指定 Flow。

    Args:
        identity (IworkIdentity): 待校验的可信身份。
        flow_name (str): 生产组名称。
        target_date (date): 权限生效日期。

    Returns:
        bool: 允许管理时返回 ``True``。

    Raises:
        TargetResponsibilityError: 身份缺少稳定subject时抛出。
    """
    identity = require_subject(identity)
    if identity.is_admin:
        return True
    return ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS).filter(
        active_assignment_query(target_date),
        principal__subject=identity.subject,
        flow_name=flow_name,
    ).exists()


def require_flow_permission(
    identity: IworkIdentity,
    flow_name: str,
    target_date: date,
) -> None:
    """校验目标写入的管理员或组长权限。

    Args:
        identity (IworkIdentity): 待校验的可信身份。
        flow_name (str): 目标所属生产组。
        target_date (date): 目标业务日期。

    Raises:
        TargetResponsibilityError: 身份无效或无权管理生产组时抛出。
    """
    if not identity_can_manage_flow(identity, flow_name, target_date):
        raise TargetResponsibilityError(
            'managed_flow_required',
            '仅管理员或该生产组的有效负责人可以保存目标',
            403,
        )


def require_admin(identity: IworkIdentity | None) -> IworkIdentity:
    """要求请求身份是管理员。

    Args:
        identity (IworkIdentity | None): 待校验的请求身份。

    Returns:
        IworkIdentity: 已认证的管理员身份。

    Raises:
        TargetResponsibilityError: 身份缺失或不是管理员时抛出。
    """
    identity = require_subject(identity)
    if not identity.is_admin:
        raise TargetResponsibilityError('admin_required', '此接口仅限管理员', 403)
    return identity


def get_policy_for_date(target_date: date) -> tuple[time, str]:
    """获取目标日期生效的策略，缺省为曼谷 09:00。

    Args:
        target_date (date): 待查询策略的业务日期。

    Returns:
        tuple[time, str]: 截止时间和IANA时区名称。
    """
    policy = TargetSubmissionPolicy.objects.using(LOCAL_DB_ALIAS).filter(
        effective_date__lte=target_date,
    ).order_by('-effective_date').first()
    if policy is None:
        return _default_deadline_time(), settings.IWORK_BUSINESS_TIME_ZONE
    return policy.deadline_time, policy.timezone_name


def deadline_for_date(target_date: date) -> datetime:
    """计算指定业务日期的时区感知截止时间。

    Args:
        target_date (date): 目标业务日期。

    Returns:
        datetime: 带策略时区的截止时刻。

    Raises:
        ZoneInfoNotFoundError: 策略中的IANA时区不存在时抛出。
    """
    deadline_time, timezone_name = get_policy_for_date(target_date)
    return datetime.combine(target_date, deadline_time, tzinfo=ZoneInfo(timezone_name))


def _now_instant(now: datetime | None) -> datetime:
    """返回用于状态比较的时区感知当前时间。

    Args:
        now (datetime | None): 可注入的当前时刻。

    Returns:
        datetime: 保留原时区或补充默认时区的时刻。
    """
    value = now or timezone.now()
    if timezone.is_naive(value):
        return timezone.make_aware(value, ZoneInfo(settings.IWORK_BUSINESS_TIME_ZONE))
    return value


def ensure_daily_target_obligations(
    target_date: date,
    *,
    now: datetime | None = None,
) -> list[DailyTargetObligation]:
    """生成或补偿一个业务日的 Flow 目标责任并刷新逾期/撤销状态。

    Args:
        target_date (date): 责任所属业务日期。
        now (datetime | None): 可注入的状态判断时刻。

    Returns:
        list[DailyTargetObligation]: 当日仍有负责人或已有提交的责任。
    """
    instant = _now_instant(now)
    assignments = list(
        ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS)
        .filter(active_assignment_query(target_date))
        .select_related('principal')
        .order_by('flow_name', 'principal__username')
    )
    leaders_by_flow: dict[str, list[IworkPrincipal]] = defaultdict(list)
    for assignment in assignments:
        leaders_by_flow[assignment.flow_name].append(assignment.principal)
    target_flows = set(
        GroupTargetProduction.objects.using(LOCAL_DB_ALIAS)
        .filter(target_date=target_date)
        .values_list('flow_name', flat=True)
    )
    flows_to_create = set(leaders_by_flow) | target_flows

    result = []
    with transaction.atomic(using=LOCAL_DB_ALIAS):
        for flow_name in sorted(flows_to_create):
            leaders = leaders_by_flow.get(flow_name, [])
            target = GroupTargetProduction.objects.using(LOCAL_DB_ALIAS).filter(
                target_date=target_date,
                flow_name=flow_name,
            ).first()
            obligation, created = DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).get_or_create(
                target_date=target_date,
                flow_name=flow_name,
                defaults={'deadline_at': deadline_for_date(target_date)},
            )
            if created:
                for leader in leaders:
                    DailyTargetObligationLeader.objects.using(LOCAL_DB_ALIAS).create(
                        obligation=obligation,
                        principal=leader,
                        subject=leader.subject,
                        username=leader.username,
                    )
            if target is not None:
                submitted_at = target.submitted_at or target.updated_at
                obligation.status = (
                    DailyTargetObligation.Status.FULFILLED
                    if submitted_at <= obligation.deadline_at
                    else DailyTargetObligation.Status.FULFILLED_LATE
                )
                obligation.submitted_by_subject = target.submitted_by_subject
                obligation.submitted_by_username = target.submitted_by_username
                obligation.submitted_at = submitted_at
                obligation.waived_at = None
            elif obligation.status == DailyTargetObligation.Status.PENDING:
                obligation.status = (
                    DailyTargetObligation.Status.OVERDUE
                    if instant > obligation.deadline_at
                    else DailyTargetObligation.Status.PENDING
                )
            obligation.save(using=LOCAL_DB_ALIAS)
            result.append(obligation)

        existing_without_current_assignment = DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).filter(
            target_date=target_date,
        ).exclude(flow_name__in=flows_to_create)
        for obligation in existing_without_current_assignment:
            if obligation.status == DailyTargetObligation.Status.PENDING and instant > obligation.deadline_at:
                obligation.status = DailyTargetObligation.Status.OVERDUE
                obligation.save(using=LOCAL_DB_ALIAS)
            result.append(obligation)
    return result


def mark_overdue_target_obligations(*, now: datetime | None = None) -> int:
    """批量把超过截止时间的待提交责任标记为逾期。

    Args:
        now (datetime | None): 可注入的当前时刻。

    Returns:
        int: 更新为逾期状态的责任数量。
    """
    instant = _now_instant(now)
    return DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).filter(
        status=DailyTargetObligation.Status.PENDING,
        deadline_at__lt=instant,
    ).update(status=DailyTargetObligation.Status.OVERDUE, updated_at=instant)


def list_target_obligations_for_alerts(
    target_date: date,
    *,
    now: datetime | None = None,
) -> list[DailyTargetObligation]:
    """为告警模块返回已补偿且带冻结负责人快照的当日责任。

    Args:
        target_date (date): 告警评估的业务日期。
        now (datetime | None): 可注入的评估时刻。

    Returns:
        list[DailyTargetObligation]: 按 Flow 排序的责任，调用方可按状态筛选。
    """
    ensure_daily_target_obligations(target_date, now=now)
    return list(
        DailyTargetObligation.objects.using(LOCAL_DB_ALIAS)
        .filter(target_date=target_date)
        .prefetch_related('leader_links')
        .order_by('flow_name')
    )


def waive_unfinished_obligations(
    *,
    flow_name: str,
    identity: IworkIdentity,
    now: datetime | None = None,
) -> int:
    """在截止前撤销最后一名组长时免除尚未完成的责任。

    已冻结的负责人快照不会删除；截止后的责任会保留并转为逾期。

    Args:
        flow_name (str): 分配发生变化的生产组。
        identity (IworkIdentity): 执行撤销的当前管理员身份。
        now (datetime | None): 可注入的撤销时刻。

    Returns:
        int: 本次免除的责任数。

    Raises:
        TargetResponsibilityError: 当前身份不是管理员时抛出。
    """
    require_admin(identity)
    instant = _now_instant(now)
    waived_count = 0
    obligations = DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).filter(
        flow_name=flow_name,
        status=DailyTargetObligation.Status.PENDING,
    )
    with transaction.atomic(using=LOCAL_DB_ALIAS):
        for obligation in obligations.select_for_update():
            still_managed = ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS).filter(
                active_assignment_query(obligation.target_date),
                flow_name=flow_name,
            ).exists()
            if still_managed:
                continue
            if instant > obligation.deadline_at:
                obligation.status = DailyTargetObligation.Status.OVERDUE
                obligation.save(using=LOCAL_DB_ALIAS)
                continue
            obligation.status = DailyTargetObligation.Status.WAIVED
            obligation.waived_at = instant
            obligation.save(using=LOCAL_DB_ALIAS)
            GroupTargetAuditLog.objects.using(LOCAL_DB_ALIAS).create(
                target_date=obligation.target_date,
                flow_name=flow_name,
                action='obligation_waived',
                actor_subject=identity.subject,
                actor_username=identity.username,
                old_value={'status': DailyTargetObligation.Status.PENDING},
                new_value={'status': DailyTargetObligation.Status.WAIVED},
            )
            waived_count += 1
    return waived_count


def save_group_target(
    *,
    identity: IworkIdentity,
    flow_name: str,
    target_date: date,
    target_qty: int,
    planned_work_minutes: int | None,
) -> GroupTargetProduction:
    """事务性保存整组目标、完成责任并写入审计。

    Args:
        identity (IworkIdentity): 可信提交人身份。
        flow_name (str): 生产组名称。
        target_date (date): 目标业务日期。
        target_qty (int): 非负整组目标，零是有效提交。
        planned_work_minutes (int | None): 可选计划工作分钟。

    Returns:
        GroupTargetProduction: 已保存目标。

    Raises:
        TargetResponsibilityError: 身份、日期、权限或目标数量不合法时抛出。
    """
    identity = require_subject(identity)
    if not identity.is_admin and target_date != get_business_date():
        raise TargetResponsibilityError(
            'current_business_date_required',
            '组长只能修改当前业务日的目标',
            403,
        )
    require_flow_permission(identity, flow_name, target_date)
    if target_qty < 0:
        raise TargetResponsibilityError('invalid_target_qty', '整组目标不能小于 0')
    submitted_at = timezone.now()
    with transaction.atomic(using=LOCAL_DB_ALIAS):
        sync_principal(identity)
        ensure_daily_target_obligations(target_date, now=submitted_at)
        obligation = DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).select_for_update().filter(
            target_date=target_date,
            flow_name=flow_name,
        ).first()
        if obligation is None:
            obligation = DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).create(
                target_date=target_date,
                flow_name=flow_name,
                deadline_at=deadline_for_date(target_date),
            )
        previous = GroupTargetProduction.objects.using(LOCAL_DB_ALIAS).select_for_update().filter(
            target_date=target_date,
            flow_name=flow_name,
        ).first()
        old_value = None
        if previous is not None:
            old_value = {
                'target_qty': previous.target_qty,
                'planned_work_minutes': previous.planned_work_minutes,
            }
        defaults = {
            'target_qty': target_qty,
            'submitted_by_subject': identity.subject,
            'submitted_by_username': identity.username,
            'submitted_at': submitted_at,
            'is_late': submitted_at > obligation.deadline_at,
        }
        if planned_work_minutes is not None:
            defaults['planned_work_minutes'] = planned_work_minutes
        target, _ = GroupTargetProduction.objects.using(LOCAL_DB_ALIAS).update_or_create(
            target_date=target_date,
            flow_name=flow_name,
            defaults=defaults,
        )
        obligation.status = (
            DailyTargetObligation.Status.FULFILLED
            if submitted_at <= obligation.deadline_at
            else DailyTargetObligation.Status.FULFILLED_LATE
        )
        obligation.submitted_by_subject = identity.subject
        obligation.submitted_by_username = identity.username
        obligation.submitted_at = submitted_at
        obligation.waived_at = None
        obligation.save(using=LOCAL_DB_ALIAS)
        GroupTargetAuditLog.objects.using(LOCAL_DB_ALIAS).create(
            target_date=target_date,
            flow_name=flow_name,
            action='target_saved',
            actor_subject=identity.subject,
            actor_username=identity.username,
            old_value=old_value,
            new_value={
                'target_qty': target.target_qty,
                'planned_work_minutes': target.planned_work_minutes,
                'is_late': target.is_late,
            },
        )
    return target


def set_submission_policy(
    *,
    identity: IworkIdentity,
    deadline_time: time,
    timezone_name: str,
    as_of_date: date,
) -> TargetSubmissionPolicy:
    """创建从下一业务日生效的提交策略版本。

    Args:
        identity (IworkIdentity): 执行设置的管理员身份。
        deadline_time (time): 每日目标提交截止时间。
        timezone_name (str): 截止时间使用的IANA时区名称。
        as_of_date (date): 计算生效日期的当前业务日。

    Returns:
        TargetSubmissionPolicy: 创建或更新后的策略版本。

    Raises:
        TargetResponsibilityError: 身份无权设置或时区无效时抛出。
    """
    require_admin(identity)
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise TargetResponsibilityError('invalid_timezone', '无效的 IANA 时区') from exc
    effective_date = next_business_date(as_of_date)
    policy, _ = TargetSubmissionPolicy.objects.using(LOCAL_DB_ALIAS).update_or_create(
        effective_date=effective_date,
        defaults={
            'deadline_time': deadline_time,
            'timezone_name': timezone_name,
            'created_by_subject': identity.subject,
        },
    )
    return policy
