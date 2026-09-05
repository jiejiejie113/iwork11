"""账号订阅、站内通知与已读接口行为测试。"""

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone


AUTH_HEADERS = {
    "REMOTE_ADDR": "127.0.0.1",
    "HTTP_REMOTE_SUBJECT": "admin-subject",
    "HTTP_REMOTE_USER": "admin",
    "HTTP_REMOTE_GROUPS": "/admin,/apps/iwork",
}


def _production_csrf_origins() -> list[str]:
    """读取版本化生产环境中的CSRF可信源站。"""
    production_env = Path("env/production.env").read_text(encoding="utf-8")
    prefix = "DJANGO_CSRF_TRUSTED_ORIGINS="
    for line in production_env.splitlines():
        if line.startswith(prefix):
            return [value.strip() for value in line.removeprefix(prefix).split(",") if value.strip()]
    return []


def _create_role_alert(audience_key):
    """创建一条仅指定角色可见的逾期警报。"""
    from iwork.alert_models import AlertAudience, AlertEvent
    from iwork.alerts.service import AlertService

    rule = AlertService().ensure_builtin_rules()["target_submission_overdue"]
    event = AlertEvent.objects.using("iwork_local").create(
        rule=rule,
        business_date=date(2026, 8, 18),
        dimension_key="SO3-L3A",
        title="生产组目标逾期未填",
        message="生产组 SO3-L3A 尚未提交今日目标。",
        payload={"flow": "SO3-L3A"},
    )
    AlertAudience.objects.using("iwork_local").create(
        event=event,
        audience_type="role",
        audience_key=audience_key,
    )
    return event


def _create_admin_alert():
    """创建一条仅主管理员可见的逾期警报。"""
    return _create_role_alert("admin")


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_notification_api_requires_stable_subject(client):
    """缺少可信subject时通知接口必须拒绝访问。"""
    response = client.get("/api/account/notifications/", REMOTE_ADDR="127.0.0.1")

    assert response.status_code == 401
    assert response.json()["code"] == "identity_required"


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_admin_role_audience_is_resolved_when_notifications_are_read(client):
    """管理员角色受众应在读取时解析，不需要预先枚举管理员账号。"""
    event = _create_admin_alert()

    admin_response = client.get("/api/account/notifications/", **AUTH_HEADERS)
    user_response = client.get(
        "/api/account/notifications/",
        REMOTE_ADDR="127.0.0.1",
        HTTP_REMOTE_SUBJECT="user-subject",
        HTTP_REMOTE_USER="user",
        HTTP_REMOTE_GROUPS="/apps/iwork",
    )

    assert admin_response.status_code == 200
    assert admin_response.json()["unread_count"] == 1
    assert admin_response.json()["notifications"][0]["id"] == event.pk
    assert user_response.status_code == 200
    assert user_response.json() == {"notifications": [], "unread_count": 0}


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_iwork_admin_role_audience_is_resolved_when_notifications_are_read(client):
    """iwork 专属管理员应收到 iwork 角色受众的通知，但普通用户不可见。"""
    event = _create_role_alert("iwork_admin")
    iwork_admin_headers = {
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_REMOTE_SUBJECT": "iwork-admin-subject",
        "HTTP_REMOTE_USER": "iwork-admin",
        "HTTP_REMOTE_GROUPS": "/iwork-admin,/apps/iwork",
    }

    admin_response = client.get(
        "/api/account/notifications/",
        **iwork_admin_headers,
    )
    user_response = client.get(
        "/api/account/notifications/",
        REMOTE_ADDR="127.0.0.1",
        HTTP_REMOTE_SUBJECT="user-subject",
        HTTP_REMOTE_USER="user",
        HTTP_REMOTE_GROUPS="/apps/iwork",
    )

    assert admin_response.status_code == 200
    assert admin_response.json()["unread_count"] == 1
    assert admin_response.json()["notifications"][0]["id"] == event.pk
    assert user_response.status_code == 200
    assert user_response.json() == {"notifications": [], "unread_count": 0}


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_read_endpoint_marks_current_event_revision_only(client):
    """已读应记录当前事件修订，事件恢复后应重新成为未读。"""
    event = _create_admin_alert()

    response = client.post(
        f"/api/account/notifications/{event.pk}/read/",
        data=json.dumps({}),
        content_type="application/json",
        **AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert client.get("/api/account/notifications/", **AUTH_HEADERS).json()["unread_count"] == 0

    event.revision = 2
    event.status = "recovered"
    event.recovered_at = timezone.now()
    event.save(using="iwork_local")

    assert client.get("/api/account/notifications/", **AUTH_HEADERS).json()["unread_count"] == 1


@override_settings(ALLOWED_HOSTS=["dituportal.dongming.local"])
@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_production_https_origin_can_mark_notification_read_with_csrf_checks():
    """新旧Portal HTTPS页面携带合法CSRF令牌时均应能标记通知已读。"""
    event = _create_admin_alert()
    production_origins = _production_csrf_origins()
    expected_origins = {
        "https://dituportal.dongming.local",
        "https://dktportal.dongming.local",
    }
    assert set(production_origins) == expected_origins

    with override_settings(CSRF_TRUSTED_ORIGINS=production_origins):
        for index, origin in enumerate(sorted(expected_origins)):
            csrf_client = Client(enforce_csrf_checks=True)
            csrf_token = chr(ord("a") + index) * 32
            csrf_client.cookies["csrftoken"] = csrf_token
            response = csrf_client.post(
                f"/api/account/notifications/{event.pk}/read/",
                data=json.dumps({}),
                content_type="application/json",
                HTTP_HOST="dituportal.dongming.local",
                HTTP_ORIGIN=origin,
                HTTP_X_CSRFTOKEN=csrf_token,
                **AUTH_HEADERS,
            )

            assert response.status_code == 200
            assert response.json() == {"status": "read", "notification_id": event.pk}


@override_settings(ALLOWED_HOSTS=["dituportal.dongming.local"])
@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_untrusted_https_origin_cannot_mark_notification_read():
    """生产配置不得允许未知HTTPS源站提交通知已读请求。"""
    event = _create_admin_alert()
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_token = "a" * 32
    csrf_client.cookies["csrftoken"] = csrf_token

    with override_settings(CSRF_TRUSTED_ORIGINS=_production_csrf_origins()):
        response = csrf_client.post(
            f"/api/account/notifications/{event.pk}/read/",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_HOST="dituportal.dongming.local",
            HTTP_ORIGIN="https://untrusted.example",
            HTTP_X_CSRFTOKEN=csrf_token,
            **AUTH_HEADERS,
        )

    assert response.status_code == 403


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_leader_can_only_subscribe_to_an_assigned_flow(client):
    """组长只能保存当前有效分配Flow范围的订阅。"""
    from iwork.alerts.service import AlertService
    from iwork.local_models import IworkPrincipal, ManagedFlowAssignment

    rule = AlertService().ensure_builtin_rules()["data_watermark_anomaly"]
    rule.enabled = True
    rule.save(using="iwork_local", update_fields=["enabled"])
    principal = IworkPrincipal.objects.using("iwork_local").create(
        subject="leader-subject",
        username="leader",
    )
    assignment = ManagedFlowAssignment.objects.using("iwork_local").create(
        principal=principal,
        flow_name="SO3-L3A",
        effective_date=date(2026, 8, 1),
        created_by_subject="admin-subject",
    )
    headers = {
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_REMOTE_SUBJECT": "leader-subject",
        "HTTP_REMOTE_USER": "leader",
        "HTTP_REMOTE_GROUPS": "/apps/iwork",
    }
    allowed = client.put(
        "/api/account/subscriptions/",
        data=json.dumps({
            "subscriptions": [{
                "rule_code": "data_watermark_anomaly",
                "scope_type": "flow",
                "scope_value": "SO3-L3A",
            }],
        }),
        content_type="application/json",
        **headers,
    )
    denied = client.put(
        "/api/account/subscriptions/",
        data=json.dumps({
            "subscriptions": [{
                "rule_code": "data_watermark_anomaly",
                "scope_type": "flow",
                "scope_value": "OTHER-FLOW",
            }],
        }),
        content_type="application/json",
        **headers,
    )

    assert allowed.status_code == 200
    assert allowed.json()["subscriptions"][0]["scope_value"] == "SO3-L3A"
    assert denied.status_code == 403
    assert denied.json()["code"] == "managed_flow_required"

    assignment.delete(using="iwork_local")
    refreshed = client.get("/api/account/subscriptions/", **headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["subscriptions"] == []


@pytest.mark.django_db(databases=["default", "iwork_local"])
def test_admin_notification_list_serializes_payload(client):
    """管理员通知列表应返回每日摘要事件的业务负载供详情弹窗使用。"""
    from iwork.alert_models import AlertEvent
    from iwork.alerts.service import AlertService
    from iwork.local_models import DailyTargetObligation

    DailyTargetObligation.objects.using("iwork_local").create(
        target_date=date(2026, 8, 18),
        flow_name="SO1",
        status="overdue",
        deadline_at=timezone.now(),
    )
    AlertService().evaluate_daily_responsibility_summary(date(2026, 8, 18))

    response = client.get("/api/account/notifications/", **AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()["notifications"][0]["payload"]
    assert payload["type"] == "daily_summary"
    assert payload["status_counts"]["overdue"] == 1
    assert payload["flows"][0]["flow"] == "SO1"
    assert AlertEvent.objects.using("iwork_local").get().rule.code == "daily_responsibility_summary"


@pytest.mark.asyncio
async def test_notification_sse_only_emits_generic_wakeup():
    """通知SSE不得携带用户名、Flow或警报正文。"""
    from iwork.alerts.api import notification_stream
    from iwork.alerts.notification_events import notification_wakeup_broker
    from iwork.identity import IworkIdentity

    request = RequestFactory().get("/api/account/notifications/stream/")
    request.iwork_identity = IworkIdentity(
        subject="leader-subject",
        username="secret-user",
        keycloak_groups=["/apps/iwork"],
    )
    response = await notification_stream(request)
    iterator = response.streaming_content.__aiter__()

    assert "retry:" in (await iterator.__anext__()).decode()
    next_chunk = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)
    notification_wakeup_broker.broadcast(subjects={"leader-subject"})
    content = (await asyncio.wait_for(next_chunk, timeout=1)).decode()

    assert '"type": "notification_changed"' in content
    assert "secret-user" not in content
    assert "SO3" not in content
