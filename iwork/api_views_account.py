"""可信账户、Flow 分配和每日目标责任 API。"""

import re
from datetime import date, time

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from loguru import logger
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from iwork.local_models import (
    DailyTargetObligation,
    GroupTargetProduction,
    HistoricalSyncState,
    IworkPrincipal,
    ManagedFlowAssignment,
    TargetSubmissionPolicy,
)
from iwork.historical_queries import get_target_analysis as get_historical_target_analysis
from iwork.read_model.errors import ReadModelNotReadyError
from iwork.read_model.queries import ReadModelQueries
from iwork.statistics import get_business_date
from iwork.target_responsibility import (
    DEFAULT_TARGET_WORK_MINUTES,
    MAX_TARGET_WORK_MINUTES,
    MIN_TARGET_WORK_MINUTES,
    LOCAL_DB_ALIAS,
    TargetResponsibilityError,
    active_assignment_query,
    cleanup_deleted_principal_assignments,
    deadline_for_date,
    ensure_daily_target_obligations,
    is_group_target_complete,
    require_admin,
    require_iwork_admin,
    require_subject,
    set_submission_policy,
    sync_principal,
    target_submission_status,
    waive_unfinished_obligations,
    workday_end_for_date,
)
from iwork.target_analysis import (
    TARGET_ANALYSIS_STEP_NO,
    TARGET_ANALYSIS_TIME_ZONE,
    build_period_analysis,
    get_period_metadata,
)


# ======
# 版本化实时读模型（Web 进程只读 Redis 快照）
READ_MODEL = ReadModelQueries()

# ======
# Portal账号访问权复验配置
ACCOUNT_ACCESS_VALIDATION_URL = (
    'http://DKT_kc_nginx:8080/api/management/iwork/accounts/'
)
ACCOUNT_ACCESS_VALIDATION_HOST_PATTERN = re.compile(
    r'^[A-Za-z0-9.-]+(?::[0-9]{1,5})?$'
)


def _validate_target_iwork_access(request, *, subject: str, username: str) -> None:
    """通过Portal严格复验目标账号当前拥有iwork访问权。

    Args:
        request (Request): 当前管理员请求，用于转发已认证会话Cookie。
        subject (str): 待分配账号的Keycloak subject。
        username (str): 待分配账号的Keycloak用户名。

    Raises:
        TargetResponsibilityError: 配置不可信、账号不存在、无访问权或
            Portal/Keycloak依赖不可用。
    """
    configured_url = settings.IWORK_ACCOUNT_ACCESS_VALIDATION_URL
    if configured_url != ACCOUNT_ACCESS_VALIDATION_URL:
        raise TargetResponsibilityError(
            'account_access_validation_unavailable',
            '账号访问权校验服务配置无效',
            503,
        )
    host_header = settings.IWORK_ACCOUNT_ACCESS_VALIDATION_HOST_HEADER
    if (
        not isinstance(host_header, str)
        or not ACCOUNT_ACCESS_VALIDATION_HOST_PATTERN.fullmatch(host_header)
    ):
        raise TargetResponsibilityError(
            'account_access_validation_unavailable',
            '账号访问权校验Host配置无效',
            503,
        )
    try:
        response = requests.get(
            ACCOUNT_ACCESS_VALIDATION_URL,
            headers={
                'Cookie': request.META.get('HTTP_COOKIE', ''),
                'Host': host_header,
            },
            params={'username': username, 'access_only': '1'},
            timeout=settings.IWORK_ACCOUNT_ACCESS_VALIDATION_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise TargetResponsibilityError(
            'account_access_validation_unavailable',
            '账号访问权校验服务暂不可用',
            503,
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise TargetResponsibilityError(
            'target_account_not_found',
            '目标Keycloak账号不存在',
            404,
        )
    if response.status_code != status.HTTP_200_OK:
        raise TargetResponsibilityError(
            'account_access_validation_unavailable',
            '账号访问权校验服务暂不可用',
            503,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TargetResponsibilityError(
            'account_access_validation_unavailable',
            '账号访问权校验响应无效',
            503,
        ) from exc
    accounts = payload.get('accounts') if isinstance(payload, dict) else None
    account = accounts[0] if isinstance(accounts, list) and len(accounts) == 1 else None
    if not isinstance(account, dict) or account.get('subject') != subject:
        raise TargetResponsibilityError(
            'target_account_identity_mismatch',
            '目标账号身份与Keycloak当前记录不一致',
            409,
        )
    if not account.get('has_iwork_access'):
        raise TargetResponsibilityError(
            'iwork_access_required',
            '目标账号尚未获得iwork访问权',
            403,
        )


def _identity_or_response(
    request,
    *,
    admin: bool = False,
    iwork_admin: bool = False,
):
    """取得可信身份，失败时返回统一错误响应。

    Args:
        request (Request): 当前REST请求。
        admin (bool): 是否要求主管理员身份。
        iwork_admin (bool): 是否要求主管理员或 iwork 专属管理员身份。

    Returns:
        tuple[IworkIdentity | None, Response | None]: 身份与错误响应二元组。
    """
    try:
        identity = getattr(request, 'iwork_identity', None)
        if admin:
            identity = require_admin(identity)
        elif iwork_admin:
            identity = require_iwork_admin(identity)
        else:
            identity = require_subject(identity)
        return identity, None
    except TargetResponsibilityError as exc:
        return None, Response(
            {'error': exc.message, 'code': exc.code},
            status=exc.http_status,
        )


def _parse_date(value, field_name: str, *, required: bool = True):
    """解析 API 日期字段并返回值或错误响应。

    Args:
        value (object): 待解析的日期值。
        field_name (str): 用于错误提示的字段名。
        required (bool): 是否要求字段非空。

    Returns:
        tuple[date | None, Response | None]: 日期与错误响应二元组。
    """
    if not value and not required:
        return None, None
    try:
        return date.fromisoformat(str(value)), None
    except (TypeError, ValueError):
        return None, Response(
            {'error': f'{field_name} 格式错误，需为 YYYY-MM-DD', 'code': 'invalid_date'},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _assignment_payload(assignment: ManagedFlowAssignment) -> dict[str, object]:
    """序列化 Portal 约定的 Flow 分配字段。

    Args:
        assignment (ManagedFlowAssignment): 待序列化的负责人分配。

    Returns:
        dict[str, object]: Portal接口使用的负责人分配数据。
    """
    return {
        'id': assignment.pk,
        'subject': assignment.principal.subject,
        'username': assignment.principal.username,
        'flow_name': assignment.flow_name,
        'effective_date': assignment.effective_date.isoformat(),
        'expires_date': assignment.expires_date.isoformat() if assignment.expires_date else None,
    }


def _obligation_payload(obligation: DailyTargetObligation) -> dict[str, object]:
    """序列化 Portal 约定的每日目标责任字段。

    Args:
        obligation (DailyTargetObligation): 待序列化的每日目标责任。

    Returns:
        dict[str, object]: Portal接口使用的每日目标责任数据。
    """
    leaders = [
        {'subject': leader.subject, 'username': leader.username}
        for leader in obligation.leader_links.all()
    ]
    return {
        'target_date': obligation.target_date.isoformat(),
        'flow_name': obligation.flow_name,
        'status': obligation.status,
        'deadline_at': obligation.deadline_at.isoformat(),
        'submitted_by_username': obligation.submitted_by_username,
        'submitted_at': obligation.submitted_at.isoformat() if obligation.submitted_at else None,
        'leaders': leaders,
    }


def _today_responsibility_summary(
    groups: list[dict[str, object]],
    obligations: dict[str, DailyTargetObligation],
    *,
    target_date: date,
) -> dict[str, object]:
    """汇总今日目标页面可见分组的责任状态和填写状态。

    Args:
        groups (list[dict[str, object]]): 今日目标页面的分组数据。
        obligations (dict[str, DailyTargetObligation]): 按 Flow 索引的责任记录。
        target_date (date): 当前业务日期。

    Returns:
        dict[str, object]: 与账号职能页兼容的责任摘要，同时包含目标填写字段。
    """
    status_counts = {
        status_name: 0
        for status_name in (
            DailyTargetObligation.Status.PENDING,
            DailyTargetObligation.Status.OVERDUE,
            DailyTargetObligation.Status.FULFILLED,
            DailyTargetObligation.Status.FULFILLED_LATE,
            DailyTargetObligation.Status.WAIVED,
        )
    }
    items = []
    for group in groups:
        flow_name = str(group['flow'])
        status_name = str(group['status'])
        if status_name in status_counts:
            status_counts[status_name] += 1
        obligation = obligations.get(flow_name)
        leaders = []
        if obligation is not None:
            leaders = [
                {'subject': leader.subject, 'username': leader.username}
                for leader in obligation.leader_links.all()
            ]
        items.append({
            'target_date': target_date.isoformat(),
            'flow_name': flow_name,
            'status': status_name,
            'deadline_at': group['deadline_at'],
            'submitted_by_username': (
                obligation.submitted_by_username or str(group.get('submitted_by_username') or '')
                if obligation is not None
                else str(group.get('submitted_by_username') or '')
            ),
            'submitted_at': group['submitted_at'],
            'leaders': leaders,
            'group_target': group['group_target'],
            'work_hours': group['work_hours'],
            'target_set': group['target_set'],
            'work_hours_set': group['work_hours_set'],
            'complete': group['complete'],
        })
    return {
        'pending_count': status_counts[DailyTargetObligation.Status.PENDING],
        'overdue_count': status_counts[DailyTargetObligation.Status.OVERDUE],
        'status_counts': status_counts,
        'items': items,
    }


@api_view(['GET'])
def me(request):
    """返回当前可信身份和当日有效 Flow 分配。

    Args:
        request (Request): 当前账户信息请求。

    Returns:
        Response: 身份、有效分配或身份错误响应。
    """
    identity, error = _identity_or_response(request)
    if error:
        return error
    principal = sync_principal(identity)
    business_date = get_business_date()
    assignments = (
        ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS)
        .filter(active_assignment_query(business_date), principal=principal)
        .select_related('principal')
        .order_by('flow_name')
    )
    payload = identity.as_dict()
    payload['flow_assignments'] = [_assignment_payload(item) for item in assignments]
    return Response(payload)


def _today_target_work_hours(
    target: GroupTargetProduction | None,
    historical_work_minutes: int | None,
    *,
    historical_mode: bool = False,
) -> float | None:
    """计算今日目标页面使用的工作小时草稿值。

    当前记录优先，其次沿用该 Flow 最近一次有工时的历史记录，最后使用
    统一的 10 小时默认值。历史只读模式不使用其他日期或默认值伪造历史数据。

    Args:
        target (GroupTargetProduction | None): 当日目标记录。
        historical_work_minutes (int | None): 最近历史工时分钟数。
        historical_mode (bool): 是否序列化为历史只读数据。

    Returns:
        float | None: 页面显示的工作小时数。
    """
    minutes = getattr(target, 'planned_work_minutes', None)
    if historical_mode:
        return minutes / 60 if minutes is not None else None
    if minutes is None:
        minutes = historical_work_minutes
    if minutes is None:
        minutes = DEFAULT_TARGET_WORK_MINUTES
    return minutes / 60


# ======
# 今日目标产量达标状态
PRODUCTION_STATE_COMPLETED = 'completed'
PRODUCTION_STATE_OVERDUE = 'overdue'
PRODUCTION_STATE_UNFINISHED = 'unfinished'
PRODUCTION_STATE_FILLED = 'filled'
PRODUCTION_STATE_PENDING_FILL = 'pending_fill'


def _flow_production_by_flow(target_date: date) -> dict[str, int] | None:
    """读取指定业务日各 Flow 的白名单工序实际产量。

    Args:
        target_date (date): 业务日期。

    Returns:
        dict[str, int] | None: Flow 名称到实际产量的映射；
        实时快照不可用时返回 ``None``。
    """
    try:
        result = READ_MODEL.detail(target_date, 'flow_overview')
    except ReadModelNotReadyError as exc:
        logger.warning('实时 Flow 产量不可用，按数据缺失处理: {}', exc)
        return None
    except Exception as exc:
        logger.error('读取实时 Flow 产量异常: {}', exc)
        return None

    stepno_key = str(settings.ALLOWED_FLOWS_STEPNO)
    production: dict[str, int] = {}
    for flow_name, overview in (result.data or {}).items():
        stepnos = (overview or {}).get('stepnos') or {}
        row = (
            stepnos.get(stepno_key)
            or stepnos.get(settings.ALLOWED_FLOWS_STEPNO)
            or {}
        )
        production[str(flow_name)] = int(row.get('qty') or 0)
    return production


def _today_target_production_state(
    *,
    submitted_fully: bool,
    target_qty: int | None,
    actual_qty: int | None,
    workday_end_at,
    now,
) -> str:
    """按填写完整性、实际产量达成与下班时间计算今日目标显示状态。

    优先级：达标取决于下班时间（18:30 前=已完成，之后=逾期完成）；
    未达标取决于下班时间（未到=已填写，已过=未完成）；未填写完整=待填写。
    实时产量不可用时按未达标处理，不判已完成。

    Args:
        submitted_fully (bool): 目标产量与计划工时是否均已填写。
        target_qty (int | None): 已填写的目标产量。
        actual_qty (int | None): 当日实际产量；``None`` 表示实时数据不可用。
        workday_end_at: 当日下班时刻（完成判定截止）。
        now: 当前时刻。

    Returns:
        str: ``completed``、``overdue``、``unfinished``、``filled``
        或 ``pending_fill``。
    """
    if not submitted_fully:
        return PRODUCTION_STATE_PENDING_FILL
    after_workday_end = now > workday_end_at
    if (
        actual_qty is not None
        and target_qty is not None
        and actual_qty >= target_qty
    ):
        return (
            PRODUCTION_STATE_OVERDUE
            if after_workday_end
            else PRODUCTION_STATE_COMPLETED
        )
    return (
        PRODUCTION_STATE_UNFINISHED
        if after_workday_end
        else PRODUCTION_STATE_FILLED
    )


def _today_target_payload(
    flow_name: str,
    target: GroupTargetProduction | None,
    obligation: DailyTargetObligation | None,
    historical_work_minutes: int | None,
    *,
    target_date: date,
    now,
    flow_production: dict[str, int] | None = None,
    analysis_available: bool = False,
    analysis_actuals: dict[str, object] | None = None,
    historical_mode: bool = False,
) -> dict[str, object]:
    """序列化今日目标快捷输入页面的单组数据。

    Args:
        flow_name (str): 生产组名称。
        target (GroupTargetProduction | None): 当日目标记录。
        obligation (DailyTargetObligation | None): 当日责任记录。
        historical_work_minutes (int | None): 最近历史工时分钟数。
        target_date (date): 当前业务日期。
        now (datetime): 当前时刻，用于无责任记录时计算状态。
        flow_production (dict[str, int] | None): 当日各 Flow 实际产量；
            ``None`` 表示实时快照不可用。
        analysis_available (bool): 今日目标分析快照是否可用。
        analysis_actuals (dict[str, object] | None): 当前 Flow 的时段实际产量。
        historical_mode (bool): 是否序列化为历史只读数据。

    Returns:
        dict[str, object]: 前端使用的单组目标字段。
    """
    target_set = target is not None and getattr(target, 'target_qty', None) is not None
    work_hours_set = target is not None and target.planned_work_minutes is not None
    submitted_fully = is_group_target_complete(target)
    submitted_target_qty = int(target.target_qty) if target_set else None
    production_available = flow_production is not None
    actual_qty = (
        int(flow_production.get(flow_name, 0))
        if production_available
        else None
    )
    work_hours_source = (
        'current'
        if work_hours_set
        else 'history'
        if not historical_mode and historical_work_minutes is not None
        else 'default'
        if not historical_mode
        else 'missing'
    )
    deadline_at = obligation.deadline_at if obligation else deadline_for_date(target_date)
    if obligation is not None:
        status_value = obligation.status
    elif historical_mode:
        status_value = 'unknown'
    else:
        status_value = target_submission_status(target, deadline_at, now=now)
    submitted_at = None
    if submitted_fully:
        if obligation is not None:
            submitted_at = obligation.submitted_at
        elif target is not None:
            submitted_at = target.submitted_at or target.updated_at
    if historical_mode and submitted_at is None and target is not None:
        # 历史责任记录缺少提交时间时，兼容完整目标的旧更新时间口径。
        submitted_at = target.submitted_at
        if submitted_at is None and submitted_fully:
            submitted_at = target.updated_at
    target_submitter = (
        getattr(target, 'submitted_by_username', '') if target is not None else ''
    )
    submitted_by_username = target_submitter
    if obligation is not None:
        submitted_by_username = obligation.submitted_by_username or target_submitter
    production_state = _today_target_production_state(
        submitted_fully=submitted_fully,
        target_qty=submitted_target_qty,
        actual_qty=actual_qty,
        workday_end_at=workday_end_for_date(target_date),
        now=now,
    )
    analysis = None
    if analysis_available:
        analysis = build_period_analysis(
            analysis_actuals,
            target_qty=submitted_target_qty,
            planned_work_minutes=(
                target.planned_work_minutes if work_hours_set else None
            ),
        )
    return {
        'target_date': target_date.isoformat(),
        'flow': flow_name,
        'group_target': target.target_qty if target_set else None,
        'work_hours': _today_target_work_hours(
            target,
            historical_work_minutes,
            historical_mode=historical_mode,
        ),
        'work_hours_source': work_hours_source,
        'target_set': target_set,
        'work_hours_set': work_hours_set,
        'complete': (
            submitted_fully
            if historical_mode
            else production_state in (
                PRODUCTION_STATE_COMPLETED,
                PRODUCTION_STATE_OVERDUE,
            )
        ),
        'production_state': production_state,
        'production_available': production_available,
        'actual_qty': actual_qty,
        'status': status_value,
        'deadline_at': deadline_at.isoformat(),
        'submitted_by_username': submitted_by_username,
        'submitted_at': submitted_at.isoformat() if submitted_at else None,
        'is_late': bool(getattr(target, 'is_late', False)) if target is not None else False,
        'can_edit': not historical_mode,
        'analysis': analysis,
    }


def _today_target_analysis_metadata(
    status_value: str,
    **extra: object,
) -> dict[str, object]:
    """构造今日目标分析接口使用的固定时段元数据。

    Args:
        status_value (str): 当前分析快照状态，如 ``available`` 或
            ``unavailable``。
        **extra (object): 附加的快照状态字段。

    Returns:
        dict[str, object]: 前端展示所需的工序、时区和时段元数据。
    """
    metadata = {
        'status': status_value,
        'step_no': TARGET_ANALYSIS_STEP_NO,
        'time_zone': TARGET_ANALYSIS_TIME_ZONE,
        'periods': [
            {
                'key': period['key'],
                'label': period['label'],
                'time_range': period['time_range'],
            }
            for period in get_period_metadata()
        ],
    }
    metadata.update(extra)
    return metadata


def _load_target_analysis(
    target_date: date,
    business_date: date,
) -> tuple[str, dict[str, dict[str, object]], dict[str, object]]:
    """读取当前或历史目标分析，并返回前端状态元数据。

    Args:
        target_date (date): 请求中的目标业务日期。
        business_date (date): 当前缅甸业务日期。

    Returns:
        tuple[str, dict[str, dict[str, object]], dict[str, object]]:
            分析状态、按 Flow 的实际产量和附加元数据。
    """
    if target_date == business_date:
        analysis_by_flow: dict[str, dict[str, object]] = {}
        try:
            analysis_result = READ_MODEL.target_analysis(target_date)
            analysis_data = analysis_result.data
            if not isinstance(analysis_data, dict) or not isinstance(
                analysis_data.get('flows'),
                dict,
            ):
                raise ReadModelNotReadyError('今日目标分析快照结构无效')
            analysis_by_flow = analysis_data['flows']
            return 'available', analysis_by_flow, {}
        except ReadModelNotReadyError as exc:
            logger.warning('今日目标分析暂不可用: date={} error={}', target_date, exc)
            return 'unavailable', {}, {}

    state = (
        HistoricalSyncState.objects.using(LOCAL_DB_ALIAS)
        .filter(snapshot_date=target_date)
        .first()
    )
    extra = {
        'source': 'local_snapshot',
        'snapshot_date': target_date.isoformat(),
        'snapshot_status': state.status if state is not None else 'missing',
        'snapshot_version': state.snapshot_version if state is not None else None,
    }
    if state is None or state.status != HistoricalSyncState.Status.SUCCESS:
        return 'unavailable', {}, extra

    try:
        analysis_data = get_historical_target_analysis(target_date)
        analysis_by_flow = analysis_data.get('flows', {})
        if not isinstance(analysis_by_flow, dict):
            raise ValueError('历史目标分析视图结构无效')
    except Exception as exc:
        logger.warning('历史目标分析暂不可用: date={} error={}', target_date, exc)
        extra['snapshot_status'] = 'error'
        return 'unavailable', {}, extra
    extra['snapshot_status'] = 'available'
    return 'available', analysis_by_flow, extra


@api_view(['GET'])
def today_targets(request):
    """返回当前或指定历史日期的目标及完整性汇总。

    普通组长只看到当前有效负责的 Flow；管理员看到 ``VISIBLE_FLOWS``
    全部 Flow。当前业务日允许编辑，历史日期只读。当前目标缺少工时的
    旧记录仍会返回，且 ``complete`` 为 ``False``，不会被接口读取时自动补写。

    Args:
        request (Request): 当前可信身份请求。

    Returns:
        Response: 业务日期、截止时间、汇总、分析和分组目标列表。
    """
    identity, error = _identity_or_response(request)
    if error:
        return error

    try:
        business_date = get_business_date()
        target_date, date_error = _parse_date(
            request.query_params.get('date') or business_date.isoformat(),
            'date',
        )
        if date_error:
            return date_error
        if target_date > business_date:
            return Response(
                {
                    'error': '不能查询未来业务日期',
                    'code': 'future_date_not_allowed',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        historical_mode = target_date < business_date
        now = timezone.now()
        if identity.can_manage_all_flows:
            flow_names = list(settings.VISIBLE_FLOWS)
        else:
            assigned_flows = ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS).filter(
                active_assignment_query(business_date),
                principal__subject=identity.subject,
                flow_name__in=settings.VISIBLE_FLOWS,
            ).values_list('flow_name', flat=True)
            assigned_flow_set = set(assigned_flows)
            flow_names = [flow for flow in settings.VISIBLE_FLOWS if flow in assigned_flow_set]

        analysis_status, analysis_by_flow, analysis_extra = _load_target_analysis(
            target_date,
            business_date,
        )

        if not historical_mode:
            ensure_daily_target_obligations(target_date, now=now)
        targets = {
            item.flow_name: item
            for item in GroupTargetProduction.objects.using(LOCAL_DB_ALIAS).filter(
                target_date=target_date,
                flow_name__in=flow_names,
            )
        }
        obligations = {
            item.flow_name: item
            for item in DailyTargetObligation.objects.using(LOCAL_DB_ALIAS).filter(
                target_date=target_date,
                flow_name__in=flow_names,
            ).prefetch_related('leader_links')
        }
        historical_work_minutes: dict[str, int] = {}
        if flow_names and not historical_mode:
            historical_rows = (
                GroupTargetProduction.objects.using(LOCAL_DB_ALIAS)
                .filter(
                    flow_name__in=flow_names,
                    target_date__lt=business_date,
                )
                .exclude(planned_work_minutes__isnull=True)
                .order_by('flow_name', '-target_date', '-updated_at')
                .values_list('flow_name', 'planned_work_minutes')
            )
            for flow_name, work_minutes in historical_rows:
                if flow_name not in historical_work_minutes:
                    historical_work_minutes[flow_name] = int(work_minutes)

        flow_production = None if historical_mode else _flow_production_by_flow(target_date)
        groups = [
            _today_target_payload(
                flow_name,
                targets.get(flow_name),
                obligations.get(flow_name),
                historical_work_minutes.get(flow_name),
                target_date=target_date,
                now=now,
                flow_production=flow_production,
                analysis_available=analysis_status == 'available',
                analysis_actuals=analysis_by_flow.get(flow_name, {}),
                historical_mode=historical_mode,
            )
            for flow_name in flow_names
        ]
        state_counts = {
            state: 0
            for state in (
                PRODUCTION_STATE_COMPLETED,
                PRODUCTION_STATE_OVERDUE,
                PRODUCTION_STATE_UNFINISHED,
                PRODUCTION_STATE_FILLED,
                PRODUCTION_STATE_PENDING_FILL,
            )
        }
        for item in groups:
            state_counts[item['production_state']] += 1
        completed_count = (
            sum(1 for item in groups if item['complete'])
            if historical_mode
            else state_counts[PRODUCTION_STATE_COMPLETED]
        )
        total_count = len(groups)
        summary = {
            'completed_count': completed_count,
            'overdue_count': state_counts[PRODUCTION_STATE_OVERDUE],
            'unfinished_count': state_counts[PRODUCTION_STATE_UNFINISHED],
            'filled_count': state_counts[PRODUCTION_STATE_FILLED],
            'pending_fill_count': state_counts[PRODUCTION_STATE_PENDING_FILL],
            'incomplete_count': total_count - completed_count,
            'total_count': total_count,
            'all_complete': completed_count == total_count,
        }
        responsibility_summary = _today_responsibility_summary(
            groups,
            obligations,
            target_date=target_date,
        )
        return Response({
            'business_date': target_date.isoformat(),
            'current_business_date': business_date.isoformat(),
            'is_historical': historical_mode,
            'deadline_at': deadline_for_date(target_date).isoformat(),
            'default_work_hours': DEFAULT_TARGET_WORK_MINUTES / 60,
            'min_work_hours': MIN_TARGET_WORK_MINUTES / 60,
            'max_work_hours': MAX_TARGET_WORK_MINUTES / 60,
            'summary': summary,
            'completed_count': completed_count,
            'overdue_count': state_counts[PRODUCTION_STATE_OVERDUE],
            'unfinished_count': state_counts[PRODUCTION_STATE_UNFINISHED],
            'filled_count': state_counts[PRODUCTION_STATE_FILLED],
            'pending_fill_count': state_counts[PRODUCTION_STATE_PENDING_FILL],
            'incomplete_count': total_count - completed_count,
            'total_count': total_count,
            'all_complete': summary['all_complete'],
            'analysis': _today_target_analysis_metadata(
                analysis_status,
                **analysis_extra,
            ),
            'groups': groups,
            'is_admin': identity.is_admin,
            'is_iwork_admin': identity.is_iwork_admin,
            'responsibility_summary': responsibility_summary,
        })
    except Exception as exc:
        logger.exception('读取今日目标失败: subject={} error={}', identity.subject, exc)
        return Response(
            {
                'error': '今日目标数据暂不可用',
                'code': 'target_data_unavailable',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(['GET'])
def flow_list(request):
    """管理员获取可分配 Flow 清单，供 Portal 管理页输入候选。

    Args:
        request (Request): GET 请求。

    Returns:
        Response: ``{'flows': [...]}`` 或管理员权限错误。
    """
    identity, error = _identity_or_response(request, iwork_admin=True)
    if error:
        return error
    return Response({'flows': list(settings.VISIBLE_FLOWS)})


@api_view(['GET', 'PUT'])
def flow_assignments(request):
    """管理员列出或创建 Flow 负责人分配。

    新建分配默认在分配当日立即生效（未传 effective_date 时取当前业务日），
    且保存后立即生成/刷新生效日期当日的目标责任。

    Args:
        request (Request): GET列表或PUT保存请求。

    Returns:
        Response: 分配列表、保存结果或错误响应。
    """
    identity, error = _identity_or_response(request, iwork_admin=True)
    if error:
        return error
    if request.method == 'GET':
        assignments = (
            ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS)
            .select_related('principal')
            .order_by('flow_name', 'principal__username', 'effective_date')
        )
        return Response({'assignments': [_assignment_payload(item) for item in assignments]})

    subject = str(request.data.get('subject', '')).strip()
    flow_name = str(request.data.get('flow_name', '')).strip()
    username = str(request.data.get('username', '')).strip()
    effective_date, date_error = _parse_date(
        request.data.get('effective_date'),
        'effective_date',
        required=False,
    )
    if date_error:
        return date_error
    expires_date, expires_error = _parse_date(
        request.data.get('expires_date'),
        'expires_date',
        required=False,
    )
    if expires_error:
        return expires_error
    assignment_id = request.data.get('id')
    if not subject or not flow_name:
        return Response(
            {'error': 'subject 和 flow_name 均为必填项', 'code': 'invalid_assignment'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if flow_name not in settings.VISIBLE_FLOWS:
        return Response(
            {'error': '生产组不在允许范围内', 'code': 'invalid_flow'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    business_date = get_business_date()
    if effective_date is None:
        effective_date = business_date
    if expires_date and expires_date < effective_date:
        return Response(
            {'error': 'expires_date 不能早于 effective_date', 'code': 'invalid_assignment_dates'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        _validate_target_iwork_access(
            request,
            subject=subject,
            username=username,
        )
    except TargetResponsibilityError as exc:
        return Response(
            {'error': exc.message, 'code': exc.code},
            status=exc.http_status,
        )
    try:
        with transaction.atomic(using=LOCAL_DB_ALIAS):
            principal, _ = IworkPrincipal.objects.using(LOCAL_DB_ALIAS).update_or_create(
                subject=subject,
                defaults={'username': username},
            )
            assignment = None
            old_flow_name = None
            if assignment_id is not None:
                assignment = ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS).select_for_update().filter(
                    pk=assignment_id,
                ).first()
                if assignment is None:
                    return Response(
                        {'error': '负责人分配不存在', 'code': 'assignment_not_found'},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                old_flow_name = assignment.flow_name
            created = assignment is None
            if created:
                assignment = ManagedFlowAssignment(created_by_subject=identity.subject)
            assignment.principal = principal
            assignment.flow_name = flow_name
            assignment.effective_date = effective_date
            assignment.expires_date = expires_date
            assignment.save(using=LOCAL_DB_ALIAS)
            if old_flow_name:
                waive_unfinished_obligations(flow_name=old_flow_name, identity=identity)
    except IntegrityError:
        return Response(
            {'error': '相同负责人、Flow和生效日期的分配已存在', 'code': 'assignment_conflict'},
            status=status.HTTP_409_CONFLICT,
        )
    if effective_date <= business_date:
        ensure_daily_target_obligations(effective_date)
    return Response(
        _assignment_payload(assignment),
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['DELETE'])
def flow_assignment_detail(request, assignment_id: int):
    """管理员删除单条 Flow 负责人分配。

    Args:
        request (Request): 删除负责人分配的请求。
        assignment_id (int): 待删除的负责人分配主键。

    Returns:
        Response: 空成功响应或错误响应。
    """
    identity, error = _identity_or_response(request, iwork_admin=True)
    if error:
        return error
    assignment = (
        ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS)
        .select_related('principal')
        .filter(pk=assignment_id)
        .first()
    )
    if assignment is None:
        return Response(
            {'error': '负责人分配不存在', 'code': 'assignment_not_found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    flow_name = assignment.flow_name
    with transaction.atomic(using=LOCAL_DB_ALIAS):
        assignment.delete(using=LOCAL_DB_ALIAS)
        waive_unfinished_obligations(flow_name=flow_name, identity=identity)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
def cleanup_deleted_principals(request):
    """清理已从Portal账号全量快照中消失的iwork身份职能。

    Args:
        request (Request): 管理员请求，JSON体包含非空 ``subjects`` 字符串数组。

    Returns:
        Response: 清理数量和保留/删除的本地身份快照。
    """
    identity, error = _identity_or_response(request, iwork_admin=True)
    if error:
        return error
    subjects = request.data.get('subjects')
    if (
        not isinstance(subjects, list)
        or not subjects
        or any(not isinstance(subject, str) or not subject.strip() for subject in subjects)
    ):
        return Response(
            {
                'error': 'subjects必须是非空字符串数组',
                'code': 'subjects_required',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(subjects) > 1000:
        return Response(
            {
                'error': 'subjects一次最多只能提交1000个账号',
                'code': 'subjects_too_many',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        payload = cleanup_deleted_principal_assignments(
            subjects=subjects,
            identity=identity,
        )
    except TargetResponsibilityError as exc:
        return Response(
            {'error': exc.message, 'code': exc.code},
            status=exc.http_status,
        )
    return Response(payload)


@api_view(['GET'])
def target_obligations(request):
    """返回管理员全部或当前组长自己的每日目标责任。

    Args:
        request (Request): 带可选日期参数的责任查询请求。

    Returns:
        Response: 每日目标责任列表或错误响应。
    """
    identity, error = _identity_or_response(request, iwork_admin=True)
    if error:
        return error
    target_date, date_error = _parse_date(
        request.query_params.get('date') or get_business_date().isoformat(),
        'date',
    )
    if date_error:
        return date_error
    if identity.is_iwork_admin and not identity.is_admin and target_date != get_business_date():
        return Response(
            {
                'error': 'iwork专属管理员只能查询当前业务日责任',
                'code': 'current_business_date_required',
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    ensure_daily_target_obligations(target_date)
    obligations = (
        DailyTargetObligation.objects.using(LOCAL_DB_ALIAS)
        .filter(target_date=target_date)
        .prefetch_related('leader_links')
        .order_by('flow_name')
    )
    return Response({'obligations': [_obligation_payload(item) for item in obligations]})


@api_view(['GET', 'PUT'])
def target_policy(request):
    """读取当前策略，或由管理员设置下一业务日生效的策略。

    Args:
        request (Request): GET读取或PUT设置策略请求。

    Returns:
        Response: 当前策略、保存后的策略或错误响应。
    """
    identity, error = _identity_or_response(request, admin=True)
    if error:
        return error
    if request.method == 'GET':
        business_date = get_business_date()
        policy = TargetSubmissionPolicy.objects.using(LOCAL_DB_ALIAS).filter(
            effective_date__lte=business_date,
        ).order_by('-effective_date').first()
        return Response({
            'effective_date': policy.effective_date.isoformat() if policy else None,
            'deadline_time': (
                policy.deadline_time
                if policy
                else time.fromisoformat(settings.IWORK_TARGET_SUBMISSION_DEFAULT_DEADLINE)
            ).strftime('%H:%M'),
            'timezone_name': policy.timezone_name if policy else getattr(
                settings,
                'IWORK_BUSINESS_TIME_ZONE',
                settings.IWORK_BUSINESS_TIME_ZONE,
            ),
        })

    raw_deadline = str(request.data.get('deadline_time', ''))
    try:
        if len(raw_deadline) != 5:
            raise ValueError
        deadline_time = time.fromisoformat(raw_deadline)
        if deadline_time.second or deadline_time.microsecond or deadline_time.tzinfo is not None:
            raise ValueError
    except (TypeError, ValueError):
        return Response(
            {'error': 'deadline_time 格式错误，需为 HH:MM', 'code': 'invalid_deadline_time'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    timezone_name = str(
        request.data.get('timezone_name', settings.IWORK_BUSINESS_TIME_ZONE)
    ).strip()
    policy = set_submission_policy(
        identity=identity,
        deadline_time=deadline_time,
        timezone_name=timezone_name,
        as_of_date=get_business_date(),
    )
    return Response({
        'effective_date': policy.effective_date.isoformat(),
        'deadline_time': policy.deadline_time.strftime('%H:%M'),
        'timezone_name': policy.timezone_name,
    })
