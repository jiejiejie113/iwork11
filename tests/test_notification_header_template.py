"""共享标题栏站内通知中心模板测试。"""

from pathlib import Path


TEMPLATE = Path("iwork/templates/iwork/_header.html").read_text(encoding="utf-8")
SCRIPT = Path("static/iwork/notifications.js").read_text(encoding="utf-8")


def test_shared_header_has_notification_bell_history_and_subscription_settings():
    """所有共用看板页应具备通知铃铛、历史抽屉和订阅设置。"""
    assert "data-iwork-notification-center" in TEMPLATE
    assert "data-notification-count" in TEMPLATE
    assert "data-notification-list" in TEMPLATE
    assert "订阅设置" in TEMPLATE
    assert "notifications.js" in TEMPLATE


def test_notification_client_uses_generic_sse_wakeup_then_refetches_content():
    """前端收到SSE唤醒后应重新读取个人通知而非信任推送正文。"""
    assert 'new EventSource(basePath + "api/account/notifications/stream/")' in SCRIPT
    assert 'source.addEventListener("notification_changed", loadNotifications)' in SCRIPT
    assert 'requestJson("api/account/notifications/")' in SCRIPT
    assert "X-CSRFToken" in SCRIPT
