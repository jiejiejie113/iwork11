"""可信账户、Flow 分配和每日目标责任 API。"""

from datetime import date, time

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from iwork.local_models import (
    DailyTargetObligation,
    IworkPrincipal,
    ManagedFlowAssignment,
    TargetSubmissionPolicy,
)
from iwork.statistics import get_business_date
from iwork.target_responsibility import (
    DEFAULT_DEADLINE_TIME,
    DEFAULT_TIMEZONE_NAME,
    LOCAL_DB_ALIAS,
    TargetResponsibilityError,
    active_assignment_query,
    deadline_for_date,
    ensure_daily_target_obligations,
    require_admin,
    require_subject,
    next_business_date,
    set_submission_policy,
    sync_principal,
    waive_unfinished_obligations,
)


def _identity_or_response(request, *, admin: bool = False):
    """取得可信身份，失败时返回统一错误响应。

    Args:
        request (Request): 当前REST请求。
        admin (bool): 是否要求管理员身份。

    Returns:
        tuple[IworkIdentity | None, Response | None]: 身份与错误响应二元组。
    """
    try:
        identity = getattr(request, 'iwork_identity', None)
        identity = require_admin(identity) if admin else require_subject(identity)
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


@api_view(['GET', 'PUT'])
def flow_assignments(request):
    """管理员列出或创建 Flow 负责人分配。

    Args:
        request (Request): GET列表或PUT保存请求。

    Returns:
        Response: 分配列表、保存结果或错误响应。
    """
    identity, error = _identity_or_response(request, admin=True)
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
    effective_date, date_error = _parse_date(request.data.get('effective_date'), 'effective_date')
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
    if expires_date and expires_date < effective_date:
        return Response(
            {'error': 'expires_date 不能早于 effective_date', 'code': 'invalid_assignment_dates'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    business_date = get_business_date()
    if (
        assignment_id is None
        and effective_date <= business_date
        and timezone.now() > deadline_for_date(business_date)
    ):
        effective_date = next_business_date(business_date)
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
    identity, error = _identity_or_response(request, admin=True)
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


@api_view(['GET'])
def target_obligations(request):
    """返回管理员全部或当前组长自己的每日目标责任。

    Args:
        request (Request): 带可选日期参数的责任查询请求。

    Returns:
        Response: 每日目标责任列表或错误响应。
    """
    identity, error = _identity_or_response(request, admin=True)
    if error:
        return error
    target_date, date_error = _parse_date(
        request.query_params.get('date') or get_business_date().isoformat(),
        'date',
    )
    if date_error:
        return date_error
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
            'deadline_time': (policy.deadline_time if policy else DEFAULT_DEADLINE_TIME).strftime('%H:%M'),
            'timezone_name': policy.timezone_name if policy else getattr(
                settings,
                'IWORK_BUSINESS_TIME_ZONE',
                DEFAULT_TIMEZONE_NAME,
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
    timezone_name = str(request.data.get('timezone_name', DEFAULT_TIMEZONE_NAME)).strip()
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
