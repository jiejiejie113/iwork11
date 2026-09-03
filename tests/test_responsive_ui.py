from pathlib import Path
from unittest.mock import patch

from django.test import Client, RequestFactory


ROOT = Path(__file__).parents[1]
PRODUCTION_DETAIL_TEMPLATE = (
    ROOT / "iwork" / "templates" / "iwork" / "production_detail.html"
).read_text(encoding="utf-8")
DASHBOARD_TEMPLATE = (
    ROOT / "iwork" / "templates" / "iwork" / "dashboard.html"
).read_text(encoding="utf-8")


def test_mobile_user_agent_is_exposed_as_mobile_device_context():
    """手机/平板 User-Agent 应被服务端识别并传给页面。"""
    with patch(
        "iwork.views.get_realtime_stats",
        return_value={"date": None, "workorder_count": 0},
    ):
        response = Client().get(
            "/",
            HTTP_USER_AGENT=(
                "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
            ),
        )

    assert response.status_code == 200
    assert response.context["device_type"] == "mobile"
    assert "User-Agent" in response["Vary"]
    assert 'data-device="mobile"' in response.content.decode("utf-8")


def test_desktop_user_agent_keeps_desktop_device_context():
    """桌面 User-Agent 应保持桌面端放大字号配置。"""
    with patch(
        "iwork.views.get_realtime_stats",
        return_value={"date": None, "workorder_count": 0},
    ):
        response = Client().get(
            "/",
            HTTP_USER_AGENT=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
            ),
        )

    assert response.status_code == 200
    assert response.context["device_type"] == "desktop"
    assert 'data-device="desktop"' in response.content.decode("utf-8")


def test_production_detail_view_uses_the_same_user_agent_device_context():
    """生产详情页面也必须收到相同的手机/平板设备标记。"""
    from iwork import views

    request = RequestFactory().get(
        "/production/detail-data/",
        HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14; Tablet) Mobile Safari/537.36",
    )
    response = views.production_detail(request)

    assert response.status_code == 200
    assert 'data-device="mobile"' in response.content.decode("utf-8")


def test_responsive_tailwind_config_restores_default_mobile_font_sizes():
    """移动端应复用 Tailwind 默认字号，桌面端继续使用放大字号。"""
    for template in (DASHBOARD_TEMPLATE, PRODUCTION_DETAIL_TEMPLATE):
        assert "iwork/_tailwind_config.html" in template
    config = (ROOT / "iwork" / "templates" / "iwork" / "_tailwind_config.html").read_text(
        encoding="utf-8"
    )
    assert "_iworkIsMobile" in config
    assert "'xs': ['12px'" in config
    assert "'sm': ['14px'" in config
    assert "'base': ['16px'" in config
    assert "_iworkIsMobile ? _iworkMobileFontSize : _iworkDesktopFontSize" in config


def test_detail_cards_allow_mobile_vertical_scroll_and_long_press_drag():
    """生产详情卡片应保留普通纵向滚动，并允许长按后排序。"""
    assert 'class="iwork-card-view flex-1 min-h-0 overflow-y-auto' in PRODUCTION_DETAIL_TEMPLATE
    assert "touch-action: pan-y" in PRODUCTION_DETAIL_TEMPLATE
    assert "if (e.pointerType === 'touch') return;" not in PRODUCTION_DETAIL_TEMPLATE
    assert 'const CARD_LONG_PRESS_DELAY = 500;' in PRODUCTION_DETAIL_TEMPLATE
    assert 'Math.hypot(dx, dy) > CARD_DRAG_MOVE_THRESHOLD' in PRODUCTION_DETAIL_TEMPLATE
    assert 'if (e.cancelable) e.preventDefault();' in PRODUCTION_DETAIL_TEMPLATE
    assert 'style="touch-action:none;"' not in PRODUCTION_DETAIL_TEMPLATE


def test_mobile_detail_header_uses_compact_layout_classes():
    """移动端详情页应压缩标题、导航和工具栏占位。"""
    assert 'class="iwork-page-header ' in PRODUCTION_DETAIL_TEMPLATE
    assert 'class="iwork-detail-toolbar ' in PRODUCTION_DETAIL_TEMPLATE
    assert "body[data-device=\"mobile\"] .iwork-page-header" in PRODUCTION_DETAIL_TEMPLATE
    assert "body[data-device=\"mobile\"] .iwork-detail-toolbar" in PRODUCTION_DETAIL_TEMPLATE
    assert "body[data-device=\"mobile\"] .iwork-last-update { display: none; }" in PRODUCTION_DETAIL_TEMPLATE
    assert 'class="iwork-detail-summary text-slate-400"' in PRODUCTION_DETAIL_TEMPLATE
