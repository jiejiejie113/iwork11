"""可信代理身份与目标责任后端测试。"""

from datetime import date, datetime, time

import pytest
from django.test import RequestFactory, override_settings
from django.utils import timezone


@override_settings(IWORK_ADMIN_GROUPS=['/admin'])
def test_trusted_proxy_builds_complete_identity_from_remote_headers():
    """可信来源应将代理头解析为不可变身份对象。"""
    from iwork.middleware import TrustedProxyMiddleware

    captured = {}

    def endpoint(request):
        """记录中间件写入的身份。"""
        captured['identity'] = request.iwork_identity
        return None

    request = RequestFactory().get(
        '/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='keycloak-subject',
        HTTP_REMOTE_USER='leader',
        HTTP_REMOTE_EMAIL='leader@example.com',
        HTTP_REMOTE_NAME='生产组长',
        HTTP_REMOTE_GROUPS='/users, /admin',
    )

    TrustedProxyMiddleware(endpoint)(request)

    assert captured['identity'].as_dict() == {
        'subject': 'keycloak-subject',
        'username': 'leader',
        'email': 'leader@example.com',
        'display_name': '生产组长',
        'keycloak_groups': ['/users', '/admin'],
        'is_admin': True,
    }


def test_trusted_proxy_keeps_anonymous_dashboard_requests_available():
    """可信来源缺少身份头时仍应允许普通看板请求。"""
    from iwork.middleware import TrustedProxyMiddleware

    captured = {}

    def endpoint(request):
        """记录匿名身份。"""
        captured['identity'] = request.iwork_identity
        return None

    request = RequestFactory().get('/', REMOTE_ADDR='127.0.0.1')

    TrustedProxyMiddleware(endpoint)(request)

    assert captured['identity'].subject == ''
    assert captured['identity'].is_authenticated is False


@override_settings(IWORK_TRUSTED_PROXY_HOSTS=[])
def test_shared_private_network_address_cannot_sign_remote_identity():
    """共享Docker私网中的普通容器不得自行签发管理员身份。"""
    from iwork.middleware import TrustedProxyMiddleware

    request = RequestFactory().get(
        '/',
        REMOTE_ADDR='172.30.0.99',
        HTTP_REMOTE_SUBJECT='forged-subject',
        HTTP_REMOTE_GROUPS='/admin',
    )

    response = TrustedProxyMiddleware(lambda _request: None)(request)

    assert response.status_code == 403


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_any_active_leader_can_complete_a_daily_obligation(monkeypatch):
    """同一 Flow 的任一有效组长提交非负目标后应完成每日责任。"""
    from iwork.identity import IworkIdentity
    from iwork.local_models import (
        DailyTargetObligation,
        IworkPrincipal,
        ManagedFlowAssignment,
    )
    from iwork.target_responsibility import ensure_daily_target_obligations, save_group_target

    leader_a = IworkPrincipal.objects.create(subject='subject-a', username='leader-a')
    leader_b = IworkPrincipal.objects.create(subject='subject-b', username='leader-b')
    for leader in (leader_a, leader_b):
        ManagedFlowAssignment.objects.create(
            principal=leader,
            flow_name='SO3-L3A',
            effective_date=date(2026, 8, 1),
        )
    target_date = date(2026, 8, 19)
    monkeypatch.setattr('iwork.target_responsibility.get_business_date', lambda: target_date)
    ensure_daily_target_obligations(target_date)

    result = save_group_target(
        identity=IworkIdentity(subject='subject-b', username='leader-b'),
        flow_name='SO3-L3A',
        target_date=target_date,
        target_qty=0,
        planned_work_minutes=None,
    )

    obligation = DailyTargetObligation.objects.get(
        target_date=target_date,
        flow_name='SO3-L3A',
    )
    assert result.target_qty == 0
    assert obligation.status == DailyTargetObligation.Status.FULFILLED
    assert obligation.submitted_by_subject == 'subject-b'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_pending_obligation_becomes_overdue_after_bangkok_deadline():
    """曼谷 09:00 后未提交的责任应标记为逾期。"""
    from zoneinfo import ZoneInfo

    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment
    from iwork.target_responsibility import ensure_daily_target_obligations

    principal = IworkPrincipal.objects.create(subject='subject-a', username='leader-a')
    ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='SO3-L3A',
        effective_date=date(2026, 8, 1),
    )
    now = datetime.combine(
        date(2026, 8, 18),
        time(9, 1),
        tzinfo=ZoneInfo('Asia/Bangkok'),
    )

    obligations = ensure_daily_target_obligations(date(2026, 8, 18), now=now)

    assert obligations[0].status == 'overdue'
    assert timezone.localtime(obligations[0].deadline_at, ZoneInfo('Asia/Bangkok')).time() == time(9, 0)


def test_policy_change_uses_next_business_day():
    """目标策略变更不得在当天追溯生效。"""
    from iwork.target_responsibility import next_business_date

    assert next_business_date(date(2026, 8, 21)) == date(2026, 8, 24)


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_generated_obligation_freezes_leader_snapshot_and_deadline():
    """责任生成后新增组长和策略变更不得改写当天快照。"""
    from iwork.local_models import (
        IworkPrincipal,
        ManagedFlowAssignment,
        TargetSubmissionPolicy,
    )
    from iwork.target_responsibility import ensure_daily_target_obligations

    target_date = date(2026, 8, 18)
    leader_a = IworkPrincipal.objects.create(subject='subject-a', username='leader-a')
    ManagedFlowAssignment.objects.create(
        principal=leader_a,
        flow_name='SO3-L3A',
        effective_date=date(2026, 8, 1),
    )
    obligation = ensure_daily_target_obligations(target_date)[0]
    original_deadline = obligation.deadline_at

    leader_b = IworkPrincipal.objects.create(subject='subject-b', username='leader-b')
    ManagedFlowAssignment.objects.create(
        principal=leader_b,
        flow_name='SO3-L3A',
        effective_date=date(2026, 8, 18),
    )
    TargetSubmissionPolicy.objects.create(
        effective_date=target_date,
        deadline_time=time(8, 0),
        created_by_subject='admin',
    )
    obligation = ensure_daily_target_obligations(target_date)[0]

    assert obligation.deadline_at == original_deadline
    assert list(obligation.leader_links.values_list('subject', flat=True)) == ['subject-a']


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_late_submission_preserves_overdue_fact():
    """截止后提交应进入 fulfilled_late，而不是普通完成。"""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from iwork.identity import IworkIdentity
    from iwork.local_models import DailyTargetObligation, IworkPrincipal, ManagedFlowAssignment
    from iwork.target_responsibility import ensure_daily_target_obligations, save_group_target

    target_date = date(2026, 8, 18)
    principal = IworkPrincipal.objects.create(subject='subject-a', username='leader-a')
    ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='SO3-L3A',
        effective_date=date(2026, 8, 1),
    )
    late_time = datetime.combine(target_date, time(9, 1), tzinfo=ZoneInfo('Asia/Bangkok'))
    ensure_daily_target_obligations(target_date, now=late_time)

    with patch('iwork.target_responsibility.timezone.now', return_value=late_time):
        save_group_target(
            identity=IworkIdentity(subject='subject-a', username='leader-a'),
            flow_name='SO3-L3A',
            target_date=target_date,
            target_qty=1,
            planned_work_minutes=None,
        )

    obligation = DailyTargetObligation.objects.get(target_date=target_date, flow_name='SO3-L3A')
    assert obligation.status == DailyTargetObligation.Status.FULFILLED_LATE


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_admin_authorization_uses_current_proxy_groups_not_principal_snapshot():
    """本地旧管理员快照不得授权当前已移出管理员组的请求。"""
    from django.test import Client

    from iwork.local_models import IworkPrincipal

    IworkPrincipal.objects.create(subject='former-admin', username='former', is_admin=True)
    response = Client().get(
        '/api/account-admin/flow-assignments/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='former-admin',
        HTTP_REMOTE_USER='former',
        HTTP_REMOTE_GROUPS='/users',
    )

    assert response.status_code == 403
    assert response.json()['code'] == 'admin_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_admin_assignment_api_uses_portal_contract_fields():
    """管理员 PUT 创建分配时应返回 Portal 约定字段。"""
    import json

    from django.test import Client

    response = Client().put(
        '/api/account-admin/flow-assignments/',
        data=json.dumps({
            'subject': 'leader-subject',
            'username': 'leader',
            'flow_name': 'SO3-L3A',
            'effective_date': '2026-08-18',
            'expires_date': None,
        }),
        content_type='application/json',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='admin-subject',
        HTTP_REMOTE_USER='admin',
        HTTP_REMOTE_GROUPS='/users,/admin',
    )

    assert response.status_code == 201
    assert set(response.json()) == {
        'id',
        'subject',
        'username',
        'flow_name',
        'effective_date',
        'expires_date',
    }


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_leader_cannot_rewrite_historical_target(monkeypatch):
    """已失效组长不能利用历史有效期回写历史目标。"""
    from iwork.identity import IworkIdentity
    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment
    from iwork.target_responsibility import TargetResponsibilityError, save_group_target

    principal = IworkPrincipal.objects.create(subject='leader-subject', username='leader')
    ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='SO3-L3A',
        effective_date=date(2026, 7, 1),
        expires_date=date(2026, 7, 31),
    )
    monkeypatch.setattr('iwork.target_responsibility.get_business_date', lambda: date(2026, 8, 18))

    with pytest.raises(TargetResponsibilityError) as exc_info:
        save_group_target(
            identity=IworkIdentity(subject='leader-subject', username='leader'),
            flow_name='SO3-L3A',
            target_date=date(2026, 7, 18),
            target_qty=100,
            planned_work_minutes=None,
        )

    assert exc_info.value.code == 'current_business_date_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_assignment_date_change_waives_future_unfinished_obligation():
    """修改唯一分配的生效日期后应免除已不再负责的未来责任。"""
    import json

    from django.test import Client

    from iwork.local_models import DailyTargetObligation, IworkPrincipal, ManagedFlowAssignment
    from iwork.target_responsibility import ensure_daily_target_obligations

    principal = IworkPrincipal.objects.create(subject='leader-subject', username='leader')
    assignment = ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='SO3-L3A',
        effective_date=date(2026, 8, 1),
    )
    target_date = date(2026, 8, 19)
    ensure_daily_target_obligations(target_date)

    response = Client().put(
        '/api/account-admin/flow-assignments/',
        data=json.dumps({
            'id': assignment.pk,
            'subject': principal.subject,
            'username': principal.username,
            'flow_name': 'SO3-L3A',
            'effective_date': '2026-08-20',
            'expires_date': None,
        }),
        content_type='application/json',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='admin-subject',
        HTTP_REMOTE_USER='admin',
        HTTP_REMOTE_GROUPS='/admin',
    )

    assert response.status_code == 200
    obligation = DailyTargetObligation.objects.get(target_date=target_date, flow_name='SO3-L3A')
    assert obligation.status == DailyTargetObligation.Status.WAIVED


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_assignment_created_after_deadline_starts_next_business_day():
    """截止后新增组长不得立即产生当天逾期责任。"""
    import json
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from django.test import Client

    current_date = date(2026, 8, 18)
    after_deadline = datetime.combine(current_date, time(9, 1), tzinfo=ZoneInfo('Asia/Bangkok'))
    with (
        patch('iwork.api_views_account.get_business_date', return_value=current_date),
        patch('iwork.api_views_account.timezone.now', return_value=after_deadline),
    ):
        response = Client().put(
            '/api/account-admin/flow-assignments/',
            data=json.dumps({
                'subject': 'leader-subject',
                'username': 'leader',
                'flow_name': 'SO3-L3A',
                'effective_date': current_date.isoformat(),
                'expires_date': None,
            }),
            content_type='application/json',
            REMOTE_ADDR='127.0.0.1',
            HTTP_REMOTE_SUBJECT='admin-subject',
            HTTP_REMOTE_USER='admin',
            HTTP_REMOTE_GROUPS='/admin',
        )

    assert response.status_code == 201
    assert response.json()['effective_date'] == '2026-08-19'
