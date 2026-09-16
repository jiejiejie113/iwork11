"""今日目标完整性、API、门禁和快捷输入页面测试。"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings


TARGET_DATE = date(2026, 9, 2)
BUSINESS_ZONE = ZoneInfo('Asia/Yangon')
EARLY_TIME = datetime(2026, 9, 2, 8, 30, tzinfo=BUSINESS_ZONE)


@pytest.fixture
def fixed_business_clock(monkeypatch):
    """固定今日业务日和当前时刻，避免测试依赖运行机器时间。"""
    from django.core.cache import cache
    from django.utils import timezone

    cache.clear()
    current = {'value': EARLY_TIME}
    modules = (
        'iwork.middleware',
        'iwork.api_views',
        'iwork.api_views_account',
        'iwork.target_responsibility',
    )
    for module_name in modules:
        monkeypatch.setattr(f'{module_name}.get_business_date', lambda: TARGET_DATE)
    monkeypatch.setattr(timezone, 'now', lambda: current['value'])
    try:
        yield current
    finally:
        cache.clear()


def _identity_headers(
    *,
    subject: str,
    username: str,
    groups: str = '/apps/iwork',
) -> dict[str, str]:
    """构造可信代理身份请求头。"""
    return {
        'REMOTE_ADDR': '127.0.0.1',
        'HTTP_REMOTE_SUBJECT': subject,
        'HTTP_REMOTE_USER': username,
        'HTTP_REMOTE_GROUPS': groups,
    }


def _create_assignment(subject: str, flow_name: str):
    """创建当前业务日有效的负责人和 Flow 分配。"""
    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment

    principal = IworkPrincipal.objects.using('iwork_local').create(
        subject=subject,
        username=subject,
    )
    ManagedFlowAssignment.objects.using('iwork_local').create(
        principal=principal,
        flow_name=flow_name,
        effective_date=TARGET_DATE - timedelta(days=1),
    )
    return principal


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_old_target_without_work_hours_is_incomplete_and_not_backfilled(fixed_business_clock):
    """旧目标缺少工时时必须继续阻断，读取责任不会回填工时。"""
    from iwork.local_models import DailyTargetObligation, GroupTargetProduction
    from iwork.target_responsibility import (
        ensure_daily_target_obligations,
        is_group_target_complete,
    )

    _create_assignment('leader-old', 'Sewing-A1')
    target = GroupTargetProduction.objects.using('iwork_local').create(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        target_qty=0,
    )

    obligations = ensure_daily_target_obligations(TARGET_DATE, now=EARLY_TIME)

    target.refresh_from_db(using='iwork_local')
    obligation = obligations[0]
    assert is_group_target_complete(target) is False
    assert target.planned_work_minutes is None
    assert obligation.status == DailyTargetObligation.Status.PENDING


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_missing_target_does_not_reuse_a_stale_fulfilled_obligation(fixed_business_clock):
    """目标记录被删除后，现行负责人的旧完成状态不得绕过门禁。"""
    from iwork.local_models import DailyTargetObligation
    from iwork.target_responsibility import ensure_daily_target_obligations

    _create_assignment('leader-deleted-target', 'Sewing-A1')
    DailyTargetObligation.objects.using('iwork_local').create(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        status=DailyTargetObligation.Status.FULFILLED,
        deadline_at=datetime(2026, 9, 2, 9, 0, tzinfo=BUSINESS_ZONE),
        submitted_by_subject='former-leader',
        submitted_by_username='former-leader',
        submitted_at=EARLY_TIME,
    )

    ensure_daily_target_obligations(TARGET_DATE, now=EARLY_TIME)

    obligation = DailyTargetObligation.objects.using('iwork_local').get(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
    )
    assert obligation.status == DailyTargetObligation.Status.PENDING
    assert obligation.submitted_at is None


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_missing_work_hours_becomes_overdue_then_late_save_fulfills(fixed_business_clock):
    """缺少工时的旧目标逾期后补齐，提交状态应为逾期完成。"""
    from iwork.identity import IworkIdentity
    from iwork.local_models import DailyTargetObligation, GroupTargetProduction
    from iwork.target_responsibility import ensure_daily_target_obligations, save_group_target

    _create_assignment('leader-late', 'Sewing-A1')
    GroupTargetProduction.objects.using('iwork_local').create(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        target_qty=100,
    )
    fixed_business_clock['value'] = datetime(2026, 9, 2, 9, 1, tzinfo=BUSINESS_ZONE)
    ensure_daily_target_obligations(TARGET_DATE)

    obligation = DailyTargetObligation.objects.using('iwork_local').get(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
    )
    assert obligation.status == DailyTargetObligation.Status.OVERDUE

    save_group_target(
        identity=IworkIdentity(subject='leader-late', username='leader-late'),
        flow_name='Sewing-A1',
        target_date=TARGET_DATE,
        target_qty=0,
        planned_work_minutes=600,
    )

    obligation.refresh_from_db(using='iwork_local')
    assert obligation.status == DailyTargetObligation.Status.FULFILLED_LATE


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_service_rejects_new_submission_without_work_hours(fixed_business_clock):
    """服务层不得让缺少工时的新提交绕过目标完整性门禁。"""
    from iwork.identity import IworkIdentity
    from iwork.target_responsibility import TargetResponsibilityError, save_group_target

    _create_assignment('leader-required', 'Sewing-A1')
    with pytest.raises(TargetResponsibilityError) as raised:
        save_group_target(
            identity=IworkIdentity(subject='leader-required', username='leader-required'),
            flow_name='Sewing-A1',
            target_date=TARGET_DATE,
            target_qty=0,
            planned_work_minutes=None,
        )

    assert raised.value.code == 'work_hours_required'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@override_settings(VISIBLE_FLOWS=['Sewing-A1', 'Sewing-A2'])
def test_today_targets_api_lists_multiple_assigned_flows_and_preserves_zero(
    fixed_business_clock,
):
    """组长可一次读取多个负责分组，显式零目标和历史工时均正确序列化。"""
    from iwork.local_models import GroupTargetProduction

    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment

    principal = IworkPrincipal.objects.using('iwork_local').create(
        subject='leader-api',
        username='leader-api',
    )
    ManagedFlowAssignment.objects.using('iwork_local').create(
        principal=principal,
        flow_name='Sewing-A1',
        effective_date=TARGET_DATE - timedelta(days=1),
    )
    assignment = ManagedFlowAssignment.objects.using('iwork_local').create(
        principal=principal,
        flow_name='Sewing-A2',
        effective_date=TARGET_DATE - timedelta(days=1),
    )
    assert assignment.pk

    GroupTargetProduction.objects.using('iwork_local').create(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        target_qty=0,
        planned_work_minutes=600,
        submitted_by_subject='leader-api',
        submitted_by_username='leader-api',
        submitted_at=EARLY_TIME,
    )
    GroupTargetProduction.objects.using('iwork_local').create(
        target_date=TARGET_DATE - timedelta(days=1),
        flow_name='Sewing-A2',
        target_qty=200,
        planned_work_minutes=480,
    )

    response = Client().get(
        '/api/account/today-targets/',
        **_identity_headers(subject='leader-api', username='leader-api'),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['business_date'] == TARGET_DATE.isoformat()
    assert payload['summary'] == {
        'completed_count': 1,
        'incomplete_count': 1,
        'total_count': 2,
        'all_complete': False,
    }
    assert [item['flow'] for item in payload['groups']] == ['Sewing-A1', 'Sewing-A2']
    first, second = payload['groups']
    assert first['group_target'] == 0
    assert first['target_set'] is True
    assert first['work_hours'] == 10
    assert first['work_hours_set'] is True
    assert first['complete'] is True
    assert first['status'] == 'fulfilled'
    assert second['work_hours'] == 8
    assert second['work_hours_set'] is False
    assert second['complete'] is False
    assert second['status'] == 'pending'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@override_settings(VISIBLE_FLOWS=['Sewing-A1', 'Sewing-A2'])
def test_today_targets_api_returns_all_visible_flows_to_admin(fixed_business_clock):
    """管理员今日目标页应显示全部可见 Flow，并全部允许编辑。"""
    response = Client().get(
        '/api/account/today-targets/',
        **_identity_headers(subject='today-admin', username='today-admin', groups='/admin'),
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item['flow'] for item in payload['groups']] == ['Sewing-A1', 'Sewing-A2']
    assert all(item['can_edit'] for item in payload['groups'])
    assert payload['summary']['all_complete'] is False


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@override_settings(VISIBLE_FLOWS=['Sewing-A1', 'Sewing-A2'])
def test_today_targets_api_returns_all_visible_flows_to_iwork_admin(fixed_business_clock):
    """iwork 专属管理员应看到全部可见 Flow，并可编辑当日目标。"""
    response = Client().get(
        '/api/account/today-targets/',
        **_identity_headers(
            subject='today-iwork-admin',
            username='today-iwork-admin',
            groups='/iwork-admin,/apps/iwork',
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item['flow'] for item in payload['groups']] == ['Sewing-A1', 'Sewing-A2']
    assert all(item['can_edit'] for item in payload['groups'])
    assert payload['is_admin'] is False
    assert payload['is_iwork_admin'] is True
    assert payload['responsibility_summary']['pending_count'] == 2


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@override_settings(VISIBLE_FLOWS=['Sewing-A1', 'Sewing-A2'])
def test_today_targets_admin_summary_covers_all_visible_flows_and_leaders(
    fixed_business_clock,
):
    """管理员今日目标摘要应覆盖全部 Flow，并保留责任负责人信息。"""
    from iwork.local_models import GroupTargetProduction

    _create_assignment('summary-leader', 'Sewing-A1')
    GroupTargetProduction.objects.using('iwork_local').create(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        target_qty=100,
        planned_work_minutes=600,
        submitted_by_subject='summary-leader',
        submitted_by_username='summary-leader',
        submitted_at=EARLY_TIME,
    )

    response = Client().get(
        '/api/account/today-targets/',
        **_identity_headers(subject='summary-admin', username='summary-admin', groups='/admin'),
    )

    assert response.status_code == 200
    summary = response.json()['responsibility_summary']
    assert [item['flow_name'] for item in summary['items']] == ['Sewing-A1', 'Sewing-A2']
    assert summary['status_counts']['fulfilled'] == 1
    assert summary['status_counts']['pending'] == 1
    assert summary['items'][0]['leaders'] == [
        {'subject': 'summary-leader', 'username': 'summary-leader'},
    ]
    assert summary['items'][0]['complete'] is True
    assert summary['items'][1]['complete'] is False


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_today_targets_entry_only_renders_for_leader_or_admin(fixed_business_clock):
    """今日目标入口只对当前有效组长或管理员渲染。"""
    _create_assignment('navigation-leader', 'Sewing-A1')
    client = Client()

    leader_response = client.get(
        '/targets/today/',
        **_identity_headers(subject='navigation-leader', username='navigation-leader'),
    )
    user_response = client.get(
        '/targets/today/',
        **_identity_headers(subject='ordinary-user', username='ordinary-user'),
    )
    admin_response = client.get(
        '/targets/today/',
        **_identity_headers(subject='navigation-admin', username='navigation-admin', groups='/admin'),
    )

    marker = b"basePath + 'targets/today/'"
    assert marker in leader_response.content
    assert marker not in user_response.content
    assert marker in admin_response.content


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_today_targets_entry_and_summary_render_for_iwork_admin(fixed_business_clock):
    """iwork 专属管理员应显示今日目标入口和全部责任摘要。"""
    response = Client().get(
        '/targets/today/',
        **_identity_headers(
            subject='navigation-iwork-admin',
            username='navigation-iwork-admin',
            groups='/iwork-admin,/apps/iwork',
        ),
    )

    assert response.status_code == 200
    assert b"basePath + 'targets/today/'" in response.content
    assert b'id="today-target-responsibility-summary"' in response.content


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_deleted_principal_cleanup_removes_assignments_but_keeps_history_snapshot(
    fixed_business_clock,
):
    """删除账号清理职能时保留历史责任快照，避免破坏审计关联。"""
    from iwork.local_models import (
        DailyTargetObligation,
        DailyTargetObligationLeader,
        IworkPrincipal,
        ManagedFlowAssignment,
    )

    retained = _create_assignment('deleted-with-history', 'Sewing-A1')
    removed = _create_assignment('deleted-without-history', 'Sewing-A2')
    obligation = DailyTargetObligation.objects.using('iwork_local').create(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        deadline_at=datetime(2026, 9, 2, 9, 0, tzinfo=BUSINESS_ZONE),
    )
    DailyTargetObligationLeader.objects.using('iwork_local').create(
        obligation=obligation,
        principal=retained,
        subject=retained.subject,
        username=retained.username,
    )

    response = Client().post(
        '/api/account-admin/principals/cleanup-deleted/',
        data=json.dumps({'subjects': [retained.subject, removed.subject]}),
        content_type='application/json',
        **_identity_headers(subject='cleanup-admin', username='cleanup-admin', groups='/admin'),
    )

    assert response.status_code == 200
    assert response.json()['removed_assignment_count'] == 2
    assert not ManagedFlowAssignment.objects.using('iwork_local').filter(
        principal_id__in=[retained.pk, removed.pk],
    ).exists()
    assert IworkPrincipal.objects.using('iwork_local').filter(pk=retained.pk).exists()
    assert not IworkPrincipal.objects.using('iwork_local').filter(pk=removed.pk).exists()
    assert DailyTargetObligationLeader.objects.using('iwork_local').filter(
        principal=retained,
    ).exists()


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_set_targets_requires_work_hours_and_csrf_is_still_enforced(fixed_business_clock):
    """现有逐组接口要求工作时间，真实 HTTP POST 仍受 CSRF 保护。"""
    from rest_framework.test import APIRequestFactory

    from iwork.api_views import set_targets
    from iwork.identity import IworkIdentity

    _create_assignment('leader-validation', 'Sewing-A1')
    request = APIRequestFactory().post(
        '/api/dashboard/set-targets/',
        data={'flow': 'Sewing-A1', 'group_target': 0},
        format='json',
    )
    request.iwork_identity = IworkIdentity(subject='leader-validation', username='leader-validation')
    response = set_targets(request)
    assert response.status_code == 400
    assert response.data['code'] == 'work_hours_required'

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_response = csrf_client.post(
        '/api/dashboard/set-targets/',
        data=json.dumps({'flow': 'Sewing-A1', 'group_target': 0, 'work_hours': 10}),
        content_type='application/json',
        **_identity_headers(subject='leader-validation', username='leader-validation'),
    )
    assert csrf_response.status_code == 403


@pytest.mark.django_db(databases=['default', 'iwork_local'])
@override_settings(VISIBLE_FLOWS=['Sewing-A1', 'Sewing-A2'])
def test_partial_group_saves_keep_success_when_a_later_group_fails(fixed_business_clock):
    """逐组保存允许部分成功，失败组不会回滚已保存分组。"""
    from iwork.local_models import GroupTargetProduction

    _create_assignment('leader-partial', 'Sewing-A1')
    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment

    principal = IworkPrincipal.objects.using('iwork_local').get(subject='leader-partial')
    ManagedFlowAssignment.objects.using('iwork_local').create(
        principal=principal,
        flow_name='Sewing-A2',
        effective_date=TARGET_DATE - timedelta(days=1),
    )
    client = Client()
    valid = client.post(
        '/api/dashboard/set-targets/',
        data=json.dumps({'flow': 'Sewing-A1', 'group_target': 0, 'work_hours': 10}),
        content_type='application/json',
        **_identity_headers(subject='leader-partial', username='leader-partial'),
    )
    failed = client.post(
        '/api/dashboard/set-targets/',
        data=json.dumps({'flow': 'Sewing-A2', 'group_target': 100, 'work_hours': 0}),
        content_type='application/json',
        **_identity_headers(subject='leader-partial', username='leader-partial'),
    )

    assert valid.status_code == 200
    assert failed.status_code == 400
    assert GroupTargetProduction.objects.using('iwork_local').filter(
        target_date=TARGET_DATE,
        flow_name='Sewing-A1',
        target_qty=0,
        planned_work_minutes=600,
    ).exists()
    assert not GroupTargetProduction.objects.using('iwork_local').filter(
        target_date=TARGET_DATE,
        flow_name='Sewing-A2',
    ).exists()


def _middleware_request(path: str, *, subject: str, username: str, groups: str = '/apps/iwork'):
    """构造直接测试目标门禁的 Django 请求。"""
    from iwork.identity import IworkIdentity

    request = RequestFactory().get(path, REMOTE_ADDR='127.0.0.1')
    request.iwork_identity = IworkIdentity(
        subject=subject,
        username=username,
        keycloak_groups=[item for item in groups.split(',') if item],
        is_admin='/admin' in groups.split(','),
    )
    return request


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_target_gate_redirects_pages_and_blocks_business_api_with_stable_code(fixed_business_clock):
    """待提交负责人访问页面被带回地址，业务 API 返回稳定 403。"""
    from iwork.middleware import TargetSubmissionGateMiddleware

    _create_assignment('leader-gate', 'Sewing-A1')
    captured = []

    def endpoint(request):
        """记录门禁放行请求。"""
        captured.append(request.path)
        return HttpResponse('passed')

    middleware = TargetSubmissionGateMiddleware(endpoint)
    page_response = middleware(_middleware_request('/production/detail-data/?tab=1', subject='leader-gate', username='leader-gate'))
    assert page_response.status_code == 302
    location = page_response['Location']
    assert location.startswith('/iwork/targets/today/?')
    assert parse_qs(urlsplit(location).query)['next'] == ['/production/detail-data/?tab=1']

    api_response = middleware(_middleware_request('/api/dashboard/realtime/', subject='leader-gate', username='leader-gate'))
    assert api_response.status_code == 403
    assert json.loads(api_response.content)['code'] == 'target_submission_required'
    assert captured == []


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_target_gate_exempts_admin_without_local_admin_snapshot(fixed_business_clock):
    """管理员是否放行只看当前代理组声明，不依赖本地管理员快照。"""
    from iwork.middleware import TargetSubmissionGateMiddleware

    _create_assignment('leader-other', 'Sewing-A1')
    response = TargetSubmissionGateMiddleware(
        lambda _request: HttpResponse('admin-passed'),
    )(_middleware_request('/', subject='current-admin', username='current-admin', groups='/admin'))

    assert response.status_code == 200
    assert response.content == b'admin-passed'


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_target_gate_allows_unassigned_target_page_static_notifications_and_health(fixed_business_clock):
    """今日目标页、静态资源、个人通知和匿名健康请求不会被目标门禁拦截。"""
    from iwork.middleware import TargetSubmissionGateMiddleware

    _create_assignment('leader-exempt', 'Sewing-A1')
    middleware = TargetSubmissionGateMiddleware(lambda _request: HttpResponse('passed'))
    for path in (
        '/targets/today/',
        '/static/iwork/notifications.js',
        '/api/account/notifications/',
        '/api/account/notifications/stream/',
        '/health/',
    ):
        response = middleware(_middleware_request(path, subject='leader-exempt', username='leader-exempt'))
        assert response.status_code == 200, path

    response = middleware(_middleware_request('/', subject='unassigned', username='unassigned'))
    assert response.status_code == 200


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_target_gate_fails_closed_with_503_when_local_check_raises(monkeypatch):
    """目标责任库异常时，已认证请求不能被误放行。"""
    from iwork.middleware import TargetSubmissionGateMiddleware

    def raise_unavailable(_identity):
        """模拟本地目标责任库不可用。"""
        raise RuntimeError('local db unavailable')

    monkeypatch.setattr('iwork.middleware._has_unfinished_target_submission', raise_unavailable)
    response = TargetSubmissionGateMiddleware(lambda _request: HttpResponse('passed'))(
        _middleware_request('/', subject='leader-error', username='leader-error'),
    )

    assert response.status_code == 503
    assert json.loads(response.content)['code'] == 'target_submission_check_unavailable'


def test_today_targets_template_contains_shortcuts_sequential_save_and_return_flow():
    """快捷输入模板应包含 8/10 小时、零值校验、顺序保存和完成返回。"""
    template_path = Path(__file__).resolve().parents[1] / 'iwork' / 'templates' / 'iwork' / 'today_targets.html'
    template = template_path.read_text(encoding='utf-8')

    assert '全部 8 小时' in template
    assert '全部 10 小时' in template
    assert "target === ''" in template
    assert 'Number(item.group_target)' in template
    assert 'for (const item of groups.value)' in template
    assert 'await saveGroup(item)' in template
    assert "window.location.assign(returnTo)" in template
    assert 'responsibility_summary' in template
    assert 'today_targets_is_admin' in template
    assert '请完成填写今日目标产量' in template
    assert '快捷设置工时：' in template
    assert '已提交，可修改' in template
    assert 'v-if="item.work_hours_set"' in template
    assert "正在保存..." in template
    assert "return item.complete && !item.dirty ? '已完成' : '待填写';" in template
    for detailed_status_copy in (
        '草稿待保存',
        '按时完成',
        '已逾期待填',
        '逾期已补填',
        '已免除',
        '状态未知',
    ):
        assert detailed_status_copy not in template
    for removed_copy in (
        '只修改当前页面草稿，点击保存后才会提交。',
        '可填写 0，空白不算完成。',
        '默认 {[ defaultWorkHours ]} 小时草稿',
        '保存后才算已填写。',
        '请填写非负整数目标和 {[ minWorkHours ]}～{[ maxWorkHours ]} 小时内的工作时间。',
    ):
        assert removed_copy not in template


@pytest.mark.django_db(databases=['default', 'iwork_local'])
def test_today_targets_page_renders_public_return_parameter_safely(fixed_business_clock):
    """今日目标页面保留合法站内返回地址，拒绝外部地址。"""
    client = Client()
    safe = client.get('/targets/today/?next=%2Fproduction%2Fdetail-data%2F')
    unsafe = client.get('/targets/today/?next=https%3A%2F%2Fevil.example%2F')

    assert safe.status_code == 200
    assert b'/production/detail-data/' in safe.content
    assert unsafe.status_code == 200
    assert b'https://evil.example' not in unsafe.content
