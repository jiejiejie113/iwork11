"""可信代理身份与目标责任后端测试。"""

from datetime import date, datetime, time, timedelta

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
        'is_iwork_admin': False,
    }


@override_settings(IWORK_DEDICATED_ADMIN_GROUPS=['iwork-admin', '/iwork-admin'])
def test_trusted_proxy_recognizes_iwork_dedicated_admin_without_master_admin():
    """专属管理员组应获得 iwork 管理身份但不能升级为主管理员。"""
    from iwork.middleware import TrustedProxyMiddleware

    captured = {}

    def endpoint(request):
        """记录中间件写入的身份。"""
        captured['identity'] = request.iwork_identity
        return None

    request = RequestFactory().get(
        '/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='iwork-admin-subject',
        HTTP_REMOTE_USER='iwork-admin',
        HTTP_REMOTE_GROUPS='/users, /iwork-admin, /apps/iwork',
    )

    TrustedProxyMiddleware(endpoint)(request)

    identity = captured['identity']
    assert identity.is_iwork_admin is True
    assert identity.is_admin is False
    assert identity.can_manage_all_flows is True


@override_settings(IWORK_ADMIN_GROUPS=['admin', '/admin'])
def test_trusted_proxy_accepts_keycloak_short_admin_group():
    """Keycloak短组名声明应被识别为iwork管理员。"""
    from iwork.middleware import TrustedProxyMiddleware

    captured = {}

    def endpoint(request):
        """记录中间件写入的短组名身份。"""
        captured['identity'] = request.iwork_identity
        return None

    request = RequestFactory().get(
        '/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='keycloak-short-admin',
        HTTP_REMOTE_USER='short-admin',
        HTTP_REMOTE_GROUPS='users,admin,apps/iwork',
    )

    TrustedProxyMiddleware(endpoint)(request)

    assert captured['identity'].is_admin is True


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
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

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
            flow_name='Sewing-A1',
            effective_date=date(2026, 8, 1),
        )
    target_date = date(2026, 8, 19)
    # 截止时间 09:00；必须固定 now，否则测试在 09:00 后运行时会被判为逾期补交。
    early_time = datetime.combine(
        target_date,
        time(8, 30),
        tzinfo=ZoneInfo('Asia/Bangkok'),
    )
    monkeypatch.setattr('iwork.target_responsibility.get_business_date', lambda: target_date)
    monkeypatch.setattr('iwork.target_responsibility.timezone.now', lambda: early_time)
    ensure_daily_target_obligations(target_date)

    result = save_group_target(
        identity=IworkIdentity(subject='subject-b', username='leader-b'),
        flow_name='Sewing-A1',
        target_date=target_date,
        target_qty=0,
        planned_work_minutes=600,
    )

    obligation = DailyTargetObligation.objects.get(
        target_date=target_date,
        flow_name='Sewing-A1',
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
        flow_name='Sewing-A1',
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
def test_generated_obligation_freezes_deadline_and_appends_new_leaders():
    """责任生成后截止时间冻结，当日新增的有效组长会追加进快照。"""
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
        flow_name='Sewing-A1',
        effective_date=date(2026, 8, 1),
    )
    obligation = ensure_daily_target_obligations(target_date)[0]
    original_deadline = obligation.deadline_at

    leader_b = IworkPrincipal.objects.create(subject='subject-b', username='leader-b')
    ManagedFlowAssignment.objects.create(
        principal=leader_b,
        flow_name='Sewing-A1',
        effective_date=date(2026, 8, 18),
    )
    TargetSubmissionPolicy.objects.create(
        effective_date=target_date,
        deadline_time=time(8, 0),
        created_by_subject='admin',
    )
    obligation = ensure_daily_target_obligations(target_date)[0]

    assert obligation.deadline_at == original_deadline
    assert list(
        obligation.leader_links.order_by('pk').values_list('subject', flat=True)
    ) == ['subject-a', 'subject-b']


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_waived_obligation_revives_when_leader_reassigned():
    """豁免后重新出现组长时，责任应恢复为待提交或逾期。"""
    from zoneinfo import ZoneInfo

    from iwork.local_models import (
        DailyTargetObligation,
        IworkPrincipal,
        ManagedFlowAssignment,
    )
    from iwork.target_responsibility import (
        ensure_daily_target_obligations,
        waive_unfinished_obligations,
    )
    from iwork.identity import IworkIdentity

    target_date = date(2026, 8, 18)
    early_time = datetime.combine(target_date, time(8, 30), tzinfo=ZoneInfo('Asia/Bangkok'))
    leader_a = IworkPrincipal.objects.create(subject='subject-a', username='leader-a')
    assignment = ManagedFlowAssignment.objects.create(
        principal=leader_a,
        flow_name='Sewing-A1',
        effective_date=date(2026, 8, 1),
    )
    ensure_daily_target_obligations(target_date, now=early_time)
    assignment.delete()
    waive_unfinished_obligations(
        flow_name='Sewing-A1',
        identity=IworkIdentity(subject='admin-subject', username='admin', is_admin=True),
        now=early_time,
    )
    obligation = DailyTargetObligation.objects.get(target_date=target_date, flow_name='Sewing-A1')
    assert obligation.status == DailyTargetObligation.Status.WAIVED

    leader_b = IworkPrincipal.objects.create(subject='subject-b', username='leader-b')
    ManagedFlowAssignment.objects.create(
        principal=leader_b,
        flow_name='Sewing-A1',
        effective_date=target_date,
    )
    ensure_daily_target_obligations(target_date, now=early_time)

    obligation.refresh_from_db()
    assert obligation.status == DailyTargetObligation.Status.PENDING
    assert obligation.waived_at is None
    assert list(
        obligation.leader_links.order_by('pk').values_list('subject', flat=True)
    ) == ['subject-a', 'subject-b']


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_late_submission_preserves_overdue_fact():
    """截止后提交应进入 fulfilled_late，而不是普通完成。"""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from iwork.identity import IworkIdentity
    from iwork.local_models import DailyTargetObligation, IworkPrincipal, ManagedFlowAssignment
    from iwork.statistics import get_business_date
    from iwork.target_responsibility import ensure_daily_target_obligations, save_group_target

    # 组长只能修改当前业务日；日期必须动态获取，硬编码日期跨日后必然被拒绝。
    target_date = get_business_date()
    principal = IworkPrincipal.objects.create(subject='subject-a', username='leader-a')
    ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='Sewing-A1',
        effective_date=target_date - timedelta(days=30),
    )
    late_time = datetime.combine(target_date, time(9, 1), tzinfo=ZoneInfo('Asia/Bangkok'))
    ensure_daily_target_obligations(target_date, now=late_time)

    with patch('iwork.target_responsibility.timezone.now', return_value=late_time):
        save_group_target(
            identity=IworkIdentity(subject='subject-a', username='leader-a'),
            flow_name='Sewing-A1',
            target_date=target_date,
            target_qty=1,
            planned_work_minutes=600,
        )

    obligation = DailyTargetObligation.objects.get(target_date=target_date, flow_name='Sewing-A1')
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
def test_admin_assignment_api_uses_portal_contract_fields(monkeypatch):
    """管理员 PUT 创建分配时应返回 Portal 约定字段。"""
    import json

    from django.test import Client

    monkeypatch.setattr(
        'iwork.api_views_account._validate_target_iwork_access',
        lambda request, subject, username: None,
    )

    response = Client().put(
        '/api/account-admin/flow-assignments/',
        data=json.dumps({
            'subject': 'leader-subject',
            'username': 'leader',
            'flow_name': 'Sewing-A1',
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
def test_admin_flows_endpoint_returns_visible_flows():
    """管理员 GET flows 端点应返回与配置一致的候选清单。"""
    from django.conf import settings
    from django.test import Client

    response = Client().get(
        '/api/account-admin/flows/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='admin-subject',
        HTTP_REMOTE_USER='admin',
        HTTP_REMOTE_GROUPS='/users,/admin',
    )

    assert response.status_code == 200
    assert response.json() == {'flows': list(settings.VISIBLE_FLOWS)}


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_iwork_admin_flows_endpoint_returns_visible_flows():
    """iwork 专属管理员应能读取全部可分配 Flow 清单。"""
    from django.conf import settings
    from django.test import Client

    response = Client().get(
        '/api/account-admin/flows/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='iwork-admin-subject',
        HTTP_REMOTE_USER='iwork-admin',
        HTTP_REMOTE_GROUPS='/users,/iwork-admin,/apps/iwork',
    )

    assert response.status_code == 200
    assert response.json() == {'flows': list(settings.VISIBLE_FLOWS)}


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_iwork_admin_cannot_query_historical_target_obligations():
    """iwork 专属管理员只能查询当前业务日责任，不能读取历史责任。"""
    from django.test import Client
    from iwork.statistics import get_business_date

    historical_date = (get_business_date() - timedelta(days=1)).isoformat()
    response = Client().get(
        '/api/account-admin/target-obligations/',
        {'date': historical_date},
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='iwork-admin-subject',
        HTTP_REMOTE_USER='iwork-admin',
        HTTP_REMOTE_GROUPS='/users,/iwork-admin,/apps/iwork',
    )

    assert response.status_code == 403
    assert response.json()['code'] == 'current_business_date_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_flows_endpoint_requires_admin():
    """非管理员访问 flows 端点必须被拒绝。"""
    from django.test import Client

    response = Client().get(
        '/api/account-admin/flows/',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='subject-a',
        HTTP_REMOTE_USER='leader',
        HTTP_REMOTE_GROUPS='/users',
    )

    assert response.status_code == 403
    assert response.json()['code'] == 'admin_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_iwork_admin_cannot_change_target_submission_policy():
    """iwork 专属管理员不能修改全局目标提交策略。"""
    import json

    from django.test import Client

    response = Client().put(
        '/api/account-admin/target-policy/',
        data=json.dumps({
            'deadline_time': '10:00',
            'timezone_name': 'Asia/Bangkok',
        }),
        content_type='application/json',
        REMOTE_ADDR='127.0.0.1',
        HTTP_REMOTE_SUBJECT='iwork-admin-subject',
        HTTP_REMOTE_USER='iwork-admin',
        HTTP_REMOTE_GROUPS='/iwork-admin,/apps/iwork',
    )

    assert response.status_code == 403
    assert response.json()['code'] == 'admin_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_leader_cannot_rewrite_historical_target(monkeypatch):
    """已失效组长不能利用历史有效期回写历史目标。"""
    from iwork.identity import IworkIdentity
    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment
    from iwork.target_responsibility import TargetResponsibilityError, save_group_target

    principal = IworkPrincipal.objects.create(subject='leader-subject', username='leader')
    ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='Sewing-A1',
        effective_date=date(2026, 7, 1),
        expires_date=date(2026, 7, 31),
    )
    monkeypatch.setattr('iwork.target_responsibility.get_business_date', lambda: date(2026, 8, 18))

    with pytest.raises(TargetResponsibilityError) as exc_info:
        save_group_target(
            identity=IworkIdentity(subject='leader-subject', username='leader'),
            flow_name='Sewing-A1',
            target_date=date(2026, 7, 18),
            target_qty=100,
            planned_work_minutes=None,
        )

    assert exc_info.value.code == 'current_business_date_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_iwork_admin_can_save_current_target_but_not_historical_target(monkeypatch):
    """iwork 专属管理员可管理当前全部 Flow，但不能回写历史目标。"""
    from iwork.identity import IworkIdentity
    from iwork.local_models import GroupTargetProduction
    from iwork.target_responsibility import TargetResponsibilityError, save_group_target

    current_date = date(2026, 8, 18)
    monkeypatch.setattr('iwork.target_responsibility.get_business_date', lambda: current_date)
    identity = IworkIdentity(
        subject='iwork-admin-subject',
        username='iwork-admin',
        is_iwork_admin=True,
    )

    saved = save_group_target(
        identity=identity,
        flow_name='SO3-L3A',
        target_date=current_date,
        target_qty=100,
        planned_work_minutes=600,
    )

    assert saved.target_qty == 100
    assert GroupTargetProduction.objects.using('iwork_local').filter(
        target_date=current_date,
        flow_name='SO3-L3A',
    ).exists()

    with pytest.raises(TargetResponsibilityError) as exc_info:
        save_group_target(
            identity=identity,
            flow_name='SO3-L3A',
            target_date=current_date - timedelta(days=1),
            target_qty=100,
            planned_work_minutes=600,
        )

    assert exc_info.value.code == 'current_business_date_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_assignment_date_change_waives_future_unfinished_obligation(monkeypatch):
    """修改唯一分配的生效日期后应免除已不再负责的未来责任。"""
    import json
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from django.test import Client

    from iwork.local_models import DailyTargetObligation, IworkPrincipal, ManagedFlowAssignment
    from iwork.target_responsibility import ensure_daily_target_obligations

    monkeypatch.setattr(
        'iwork.api_views_account._validate_target_iwork_access',
        lambda request, subject, username: None,
    )

    principal = IworkPrincipal.objects.create(subject='leader-subject', username='leader')
    assignment = ManagedFlowAssignment.objects.create(
        principal=principal,
        flow_name='Sewing-A1',
        effective_date=date(2026, 8, 1),
    )
    target_date = date(2026, 8, 19)
    # 豁免逻辑要求 now 早于截止时间；固定 now 避免真实时钟跨过 09:00 后，
    # 责任先被创建为 overdue、waive 退化为逾期保留。
    early_time = datetime.combine(
        target_date,
        time(8, 30),
        tzinfo=ZoneInfo('Asia/Bangkok'),
    )
    monkeypatch.setattr('iwork.target_responsibility.timezone.now', lambda: early_time)
    ensure_daily_target_obligations(target_date)

    response = Client().put(
        '/api/account-admin/flow-assignments/',
        data=json.dumps({
            'id': assignment.pk,
            'subject': principal.subject,
            'username': principal.username,
            'flow_name': 'Sewing-A1',
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
    obligation = DailyTargetObligation.objects.get(target_date=target_date, flow_name='Sewing-A1')
    assert obligation.status == DailyTargetObligation.Status.WAIVED


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_assignment_after_deadline_takes_effect_same_day_as_overdue():
    """截止后新增组长当日立即生效，并直接生成逾期责任。"""
    import json
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from django.test import Client

    from iwork.local_models import DailyTargetObligation

    current_date = date(2026, 8, 18)
    after_deadline = datetime.combine(current_date, time(9, 1), tzinfo=ZoneInfo('Asia/Bangkok'))
    with (
        patch('iwork.api_views_account.get_business_date', return_value=current_date),
        patch('iwork.api_views_account._validate_target_iwork_access'),
        patch('iwork.target_responsibility.timezone.now', return_value=after_deadline),
    ):
        response = Client().put(
            '/api/account-admin/flow-assignments/',
            data=json.dumps({
                'subject': 'leader-subject',
                'username': 'leader',
                'flow_name': 'Sewing-A1',
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
    assert response.json()['effective_date'] == '2026-08-18'
    obligation = DailyTargetObligation.objects.get(
        target_date=current_date,
        flow_name='Sewing-A1',
    )
    assert obligation.status == DailyTargetObligation.Status.OVERDUE
    assert list(obligation.leader_links.values_list('subject', flat=True)) == ['leader-subject']


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_assignment_without_effective_date_defaults_to_business_date():
    """未传 effective_date 的分配应在当前业务日立即生效。"""
    import json
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from django.test import Client

    current_date = date(2026, 8, 18)
    early_time = datetime.combine(current_date, time(8, 30), tzinfo=ZoneInfo('Asia/Bangkok'))
    with (
        patch('iwork.api_views_account.get_business_date', return_value=current_date),
        patch('iwork.api_views_account._validate_target_iwork_access'),
        patch('iwork.target_responsibility.timezone.now', return_value=early_time),
    ):
        response = Client().put(
            '/api/account-admin/flow-assignments/',
            data=json.dumps({
                'subject': 'leader-subject',
                'username': 'leader',
                'flow_name': 'Sewing-A1',
                'expires_date': None,
            }),
            content_type='application/json',
            REMOTE_ADDR='127.0.0.1',
            HTTP_REMOTE_SUBJECT='admin-subject',
            HTTP_REMOTE_USER='admin',
            HTTP_REMOTE_GROUPS='/admin',
        )

    assert response.status_code == 201
    assert response.json()['effective_date'] == current_date.isoformat()


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_direct_assignment_revalidates_target_iwork_access(monkeypatch):
    """绕过Portal代理直调iwork时仍必须复验目标账号访问权。"""
    import json

    from django.test import Client

    from iwork.local_models import ManagedFlowAssignment

    captured = {}

    class PortalResponse:
        """提供目标账号无iwork访问权的Portal响应。"""

        status_code = 200

        @staticmethod
        def json():
            """返回严格Keycloak账号查询结果。

            Returns:
                dict: 目标账号当前访问权快照。
            """
            return {
                'accounts': [{
                    'subject': 'leader-subject',
                    'username': 'leader',
                    'has_iwork_access': False,
                }],
            }

    def fake_get(url, **kwargs):
        """记录Portal复验请求并返回无权限账号。

        Args:
            url (str): Portal复验地址。
            **kwargs: HTTP请求参数。

        Returns:
            PortalResponse: 固定的无访问权响应。
        """
        captured['url'] = url
        captured.update(kwargs)
        return PortalResponse()

    monkeypatch.setattr('iwork.api_views_account.requests.get', fake_get)
    response = Client().put(
        '/api/account-admin/flow-assignments/',
        data=json.dumps({
            'subject': 'leader-subject',
            'username': 'leader',
            'flow_name': 'Sewing-A1',
            'effective_date': '2026-08-18',
            'expires_date': None,
        }),
        content_type='application/json',
        REMOTE_ADDR='127.0.0.1',
        HTTP_COOKIE='_oauth2_proxy=session',
        HTTP_REMOTE_SUBJECT='admin-subject',
        HTTP_REMOTE_USER='admin',
        HTTP_REMOTE_GROUPS='/admin',
    )

    assert response.status_code == 403
    assert response.json()['code'] == 'iwork_access_required'
    assert captured['params'] == {'username': 'leader', 'access_only': '1'}
    assert captured['headers'] == {
        'Cookie': '_oauth2_proxy=session',
        'Host': 'localhost',
    }
    assert captured['allow_redirects'] is False
    assert not ManagedFlowAssignment.objects.exists()


@override_settings(IWORK_ACCOUNT_ACCESS_VALIDATION_HOST_HEADER='DKT_kc_nginx')
@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_direct_assignment_rejects_invalid_validation_host(monkeypatch):
    """二次复验Host含下划线时应返回503且不发起Portal请求。"""
    import json

    from django.test import Client

    from iwork.local_models import ManagedFlowAssignment

    called = False

    def fake_get(*args, **kwargs):
        """记录不应发生的Portal请求。"""
        nonlocal called
        called = True
        raise AssertionError('无效Host配置不应发起Portal请求')

    monkeypatch.setattr('iwork.api_views_account.requests.get', fake_get)
    response = Client().put(
        '/api/account-admin/flow-assignments/',
        data=json.dumps({
            'subject': 'leader-subject',
            'username': 'leader',
            'flow_name': 'Sewing-A1',
            'effective_date': '2026-08-18',
            'expires_date': None,
        }),
        content_type='application/json',
        REMOTE_ADDR='127.0.0.1',
        HTTP_COOKIE='_oauth2_proxy=session',
        HTTP_REMOTE_SUBJECT='admin-subject',
        HTTP_REMOTE_USER='admin',
        HTTP_REMOTE_GROUPS='/admin',
    )

    assert response.status_code == 503
    assert response.json()['code'] == 'account_access_validation_unavailable'
    assert called is False
    assert not ManagedFlowAssignment.objects.exists()
