"""账号订阅、站内通知和已读状态HTTP接口。"""

import json
import asyncio

from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from iwork.alert_models import AlertEvent, AlertRule, AlertSubscription, NotificationReceipt
from iwork.alerts.notification_events import notification_wakeup_broker
from iwork.alerts.service import AlertService
from iwork.identity import ANONYMOUS_IDENTITY, IworkIdentity
from iwork.local_models import ManagedFlowAssignment
from iwork.statistics import get_business_date
from iwork.target_responsibility import active_assignment_query, identity_can_manage_flow


# ======
# 本地通知接口配置
LOCAL_DB_ALIAS = "iwork_local"


def _request_identity(request: HttpRequest) -> IworkIdentity:
    """读取中间件挂载的可信身份，缺失时返回匿名身份。"""
    return getattr(request, "iwork_identity", ANONYMOUS_IDENTITY)


def _identity_error() -> JsonResponse:
    """返回稳定的缺少subject错误。"""
    return JsonResponse(
        {"code": "identity_required", "message": "此接口需要可信用户身份"},
        status=401,
    )


def _load_json(request: HttpRequest) -> dict:
    """解析JSON对象请求体。

    Raises:
        ValueError: 请求体不是合法JSON对象。
    """
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("请求体必须是合法JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是JSON对象")
    return payload


def _active_flow_scopes(identity: IworkIdentity) -> set[str]:
    """返回身份当前仍有效的可管理Flow集合。"""
    if identity.is_admin:
        return set(settings.VISIBLE_FLOWS)
    return set(
        ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS)
        .filter(active_assignment_query(get_business_date()), principal__subject=identity.subject)
        .values_list("flow_name", flat=True)
        .distinct()
    )


def _current_role(identity: IworkIdentity, flow_scopes: set[str] | None = None) -> str:
    """按当前Keycloak管理员身份和有效Flow分配推导职能。"""
    if identity.is_admin:
        return "admin"
    return "leader" if (flow_scopes if flow_scopes is not None else _active_flow_scopes(identity)) else "user"


def _valid_subscriptions(identity: IworkIdentity) -> list[AlertSubscription]:
    """重新校验当前职能和Flow范围后返回仍有效的订阅。"""
    flow_scopes = _active_flow_scopes(identity)
    role = _current_role(identity, flow_scopes)
    rows = (
        AlertSubscription.objects.using(LOCAL_DB_ALIAS)
        .filter(subject=identity.subject, enabled=True, rule__enabled=True)
        .select_related("rule")
        .order_by("rule__code", "scope_type", "scope_value")
    )
    return [
        row
        for row in rows
        if role in row.rule.allowed_roles
        and (row.scope_type != "flow" or row.scope_value in flow_scopes)
    ]


def _serialize_subscriptions(identity: IworkIdentity) -> list[dict[str, object]]:
    """序列化一个用户当前仍有权访问的订阅。"""
    return [
        {
            "rule_code": row.rule.code,
            "scope_type": row.scope_type,
            "scope_value": row.scope_value,
        }
        for row in _valid_subscriptions(identity)
    ]


def _available_rules(identity: IworkIdentity) -> list[dict[str, object]]:
    """返回当前角色可配置的规则、强制状态和允许范围。"""
    flow_scopes = sorted(_active_flow_scopes(identity))
    role = _current_role(identity, set(flow_scopes))
    result = []
    for rule in AlertRule.objects.using(LOCAL_DB_ALIAS).filter(enabled=True).order_by("code"):
        mandatory = role in rule.mandatory_roles
        if role not in rule.allowed_roles and not mandatory:
            continue
        result.append({
            "rule_code": rule.code,
            "name": rule.name,
            "scope_type": rule.scope_type,
            "scopes": flow_scopes if rule.scope_type == "flow" else [],
            "mandatory": mandatory,
        })
    return result


@require_http_methods(["GET", "PUT"])
def subscriptions(request: HttpRequest) -> JsonResponse:
    """读取或整体替换当前用户的可选站内订阅。"""
    identity = _request_identity(request)
    if not identity.subject:
        return _identity_error()
    if request.method == "GET":
        AlertService().ensure_builtin_rules()
        return JsonResponse({
            "subscriptions": _serialize_subscriptions(identity),
            "available_rules": _available_rules(identity),
        })
    try:
        payload = _load_json(request)
        requested = payload.get("subscriptions", [])
        if not isinstance(requested, list):
            raise ValueError("subscriptions必须是数组")
        validated: list[tuple[AlertRule, str, str]] = []
        for item in requested:
            if not isinstance(item, dict):
                raise ValueError("每项订阅必须是对象")
            rule_code = str(item.get("rule_code", "")).strip()
            rule = AlertRule.objects.using(LOCAL_DB_ALIAS).filter(code=rule_code, enabled=True).first()
            if rule is None:
                return JsonResponse(
                    {"code": "alert_rule_not_available", "message": "警报规则不存在或未启用"},
                    status=400,
                )
            role = _current_role(identity)
            if role not in rule.allowed_roles:
                return JsonResponse(
                    {"code": "subscription_role_required", "message": "当前职能不能订阅此规则"},
                    status=403,
                )
            scope_type = str(item.get("scope_type", "none")).strip() or "none"
            scope_value = str(item.get("scope_value", "")).strip()
            if scope_type != rule.scope_type:
                raise ValueError("订阅范围类型与规则不一致")
            if scope_type == "flow" and (
                not scope_value
                or scope_value not in settings.VISIBLE_FLOWS
                or (not identity.is_admin and not identity_can_manage_flow(
                    identity,
                    scope_value,
                    get_business_date(),
                ))
            ):
                return JsonResponse(
                    {"code": "managed_flow_required", "message": "只能订阅当前负责的生产组"},
                    status=403,
                )
            validated.append((rule, scope_type, scope_value))
    except ValueError as exc:
        return JsonResponse({"code": "invalid_request", "message": str(exc)}, status=400)

    with transaction.atomic(using=LOCAL_DB_ALIAS):
        AlertSubscription.objects.using(LOCAL_DB_ALIAS).filter(subject=identity.subject).delete()
        AlertSubscription.objects.using(LOCAL_DB_ALIAS).bulk_create([
            AlertSubscription(
                subject=identity.subject,
                rule=rule,
                scope_type=scope_type,
                scope_value=scope_value,
            )
            for rule, scope_type, scope_value in validated
        ])
    return JsonResponse({"subscriptions": _serialize_subscriptions(identity)})


def _visible_events(identity: IworkIdentity):
    """构造当前身份可见事件查询集。"""
    audience_filter = Q(audiences__audience_type="subject", audiences__audience_key=identity.subject)
    if identity.is_admin:
        audience_filter |= Q(audiences__audience_type="role", audiences__audience_key="admin")
    for subscription in _valid_subscriptions(identity):
        subscription_filter = Q(rule=subscription.rule)
        if subscription.scope_type == "flow":
            subscription_filter &= Q(payload__flow=subscription.scope_value)
        audience_filter |= subscription_filter
    return (
        AlertEvent.objects.using(LOCAL_DB_ALIAS)
        .filter(audience_filter)
        .select_related("rule")
        .distinct()
        .order_by("-last_seen_at", "-pk")
    )


@require_GET
def notifications(request: HttpRequest) -> JsonResponse:
    """返回当前身份可见的通知历史和未读数。"""
    identity = _request_identity(request)
    if not identity.subject:
        return _identity_error()
    events = list(_visible_events(identity)[:100])
    receipts = {
        receipt.event_id: receipt
        for receipt in NotificationReceipt.objects.using(LOCAL_DB_ALIAS).filter(
            subject=identity.subject,
            event_id__in=[event.pk for event in events],
        )
    }
    serialized = []
    unread_count = 0
    for event in events:
        receipt = receipts.get(event.pk)
        is_read = receipt is not None and receipt.read_revision >= event.revision
        if not is_read:
            unread_count += 1
        serialized.append({
            "id": event.pk,
            "rule_code": event.rule.code,
            "title": event.title,
            "message": event.message,
            "severity": event.severity,
            "status": event.status,
            "business_date": event.business_date.isoformat(),
            "revision": event.revision,
            "is_read": is_read,
            "updated_at": event.last_seen_at.isoformat(),
        })
    return JsonResponse({"notifications": serialized, "unread_count": unread_count})


@require_POST
def mark_notification_read(request: HttpRequest, notification_id: int) -> JsonResponse:
    """将当前用户可见事件的当前修订标记为已读。"""
    identity = _request_identity(request)
    if not identity.subject:
        return _identity_error()
    event = _visible_events(identity).filter(pk=notification_id).first()
    if event is None:
        return JsonResponse({"code": "notification_not_found", "message": "通知不存在"}, status=404)
    NotificationReceipt.objects.using(LOCAL_DB_ALIAS).update_or_create(
        event=event,
        subject=identity.subject,
        defaults={"read_revision": event.revision, "read_at": timezone.now()},
    )
    return JsonResponse({"status": "read", "notification_id": event.pk})


@require_POST
def mark_all_notifications_read(request: HttpRequest) -> JsonResponse:
    """将当前用户全部可见事件的当前修订标记为已读。"""
    identity = _request_identity(request)
    if not identity.subject:
        return _identity_error()
    now = timezone.now()
    count = 0
    with transaction.atomic(using=LOCAL_DB_ALIAS):
        for event in _visible_events(identity):
            NotificationReceipt.objects.using(LOCAL_DB_ALIAS).update_or_create(
                event=event,
                subject=identity.subject,
                defaults={"read_revision": event.revision, "read_at": now},
            )
            count += 1
    return JsonResponse({"status": "read", "count": count})


async def notification_stream(request: HttpRequest) -> StreamingHttpResponse | JsonResponse:
    """建立只发送通用唤醒、最长六十秒的账号通知SSE连接。"""
    identity = _request_identity(request)
    if not identity.subject:
        return _identity_error()

    async def event_generator():
        """生成心跳和不含业务数据的通知变化事件。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.SSE_CONNECTION_LEASE_SECONDS
        yield "retry: 3000\n\n"
        async with notification_wakeup_broker.subscribe(
            identity.subject,
            is_admin=identity.is_admin,
        ) as queue:
            while loop.time() < deadline:
                timeout = min(15.0, max(0.0, deadline - loop.time()))
                if timeout <= 0:
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=timeout)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: notification_changed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    response = StreamingHttpResponse(event_generator(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-store"
    response["X-Accel-Buffering"] = "no"
    return response
