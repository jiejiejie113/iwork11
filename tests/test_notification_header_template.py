"""共享标题栏站内通知中心模板测试。"""

import json
import shutil
import subprocess
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
    assert "data-notification-modal" in TEMPLATE
    assert "data-notification-modal-panel" in TEMPLATE


def test_notification_client_uses_generic_sse_wakeup_then_refetches_content():
    """前端收到SSE唤醒后应重新读取个人通知而非信任推送正文。"""
    assert 'new EventSource(basePath + "api/account/notifications/stream/")' in SCRIPT
    assert 'source.addEventListener("notification_changed", loadNotifications)' in SCRIPT
    assert 'requestJson("api/account/notifications/")' in SCRIPT
    assert "X-CSRFToken" in SCRIPT


def test_notification_list_prefers_unread_and_collapses_read():
    """未读消息优先展示，已读消息折叠为可展开条目。"""
    assert "notifications.filter((notification) => !notification.is_read)" in SCRIPT
    assert "已读消息（" in SCRIPT
    assert "readExpanded" in SCRIPT
    assert "data-notification-read-section" in SCRIPT


def test_notification_expandable_detail_has_indicator():
    """仅可展开详情的通知（每日责任摘要）显示查看详情标识。"""
    assert "查看详情 ›" in SCRIPT
    assert 'payload.type === "daily_summary"' in SCRIPT


def test_notification_detail_opens_before_mark_read_request_finishes():
    """已读POST失败或变慢时，每日摘要详情仍应立即打开。"""
    node_executable = shutil.which("node")
    assert node_executable is not None
    result = subprocess.run(  # noqa: S603 - 仅执行PATH解析出的本机Node和仓库内固定测试脚本
        [node_executable, "tests/js/notification_detail_harness.cjs"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads(result.stdout)
    assert payload["modal_hidden"] is False
    assert payload["requests"] == [
        ["/iwork/api/account/notifications/", "GET"],
        ["/iwork/api/account/notifications/7/read/", "POST"],
    ]
    assert "标记通知已读失败" in payload["warning"]
    assert "CSRF失败" in payload["warning"]


def test_subscription_settings_can_return_to_notification_list():
    """订阅设置面板应提供返回入口且抽屉重新打开时回到通知列表。"""
    assert "← 返回通知" in SCRIPT
    assert 'subscriptionsPanel.hidden = true;\n                list.hidden = false;' in SCRIPT
    assert "保存失败：" in SCRIPT


def test_static_url_carries_subpath_prefix():
    """STATIC_URL 必须携带 /iwork/ 前缀，staticfiles 不会把相对路径留给浏览器。"""
    from django.conf import settings

    assert settings.STATIC_URL == "/iwork/static/"


def test_csrf_trusted_origins_include_port_bearing_local_hosts():
    """Django 5.2 Origin 校验要求带端口的对外源站进入信任列表。"""
    from django.conf import settings

    trusted = settings.CSRF_TRUSTED_ORIGINS
    assert "http://192.168.30.190:8080" in trusted
    assert "http://localhost:8080" in trusted


def test_static_notifications_js_is_served_by_app(client):
    """uvicorn 不自动服务静态文件，应用必须自带路由吐出通知脚本。"""
    response = client.get("/static/iwork/notifications.js")

    assert response.status_code == 200
    assert "application/javascript" in response["Content-Type"]
    body = b"".join(response.streaming_content).decode("utf-8")
    assert "data-iwork-notification-center" in body


def test_shared_header_page_bootstraps_csrf_cookie(client):
    """包含通知中心的页面应主动签发CSRF Cookie供已读POST使用。"""
    response = client.get("/", REMOTE_ADDR="127.0.0.1")

    assert response.status_code == 200
    assert "csrftoken" in response.cookies
