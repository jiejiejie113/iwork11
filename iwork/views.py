import json
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.shortcuts import redirect, render
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.http import require_http_methods
from django.views.decorators.vary import vary_on_headers
from loguru import logger

from iwork.local_models import ManagedFlowAssignment
from iwork.read_model.errors import ReadModelNotReadyError
from iwork.statistics import get_business_date, get_realtime_stats
from iwork.target_responsibility import LOCAL_DB_ALIAS, active_assignment_query


MOBILE_USER_AGENT_RE = re.compile(
    r"(?:android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini|"
    r"opera mobi|windows phone|mobile|tablet|kindle|silk|fennec)",
    re.IGNORECASE,
)


def _safe_internal_return_path(value: str | None) -> str:
    """校验门禁完成后的站内返回地址，拒绝开放重定向。

    Args:
        value (str | None): 查询参数中携带的候选返回地址。

    Returns:
        str: 仅包含站内绝对路径的地址；非法值返回空字符串。
    """
    if not isinstance(value, str) or not value or '\\' in value:
        return ''
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
        return ''
    if parsed.path.startswith('//'):
        return ''
    return value


def _device_context(request):
    """根据请求的 User-Agent 识别页面设备类型。

    Args:
        request: Django HTTP 请求对象。

    Returns:
        dict: 包含设备类型及移动设备布尔标记的模板上下文。
    """
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    is_mobile_device = bool(MOBILE_USER_AGENT_RE.search(user_agent))
    return {
        'device_type': 'mobile' if is_mobile_device else 'desktop',
        'is_mobile_device': is_mobile_device,
    }


def _today_target_navigation_context(request):
    """判断当前身份是否可以看到今日目标入口。

    Args:
        request: Django HTTP 请求对象。

    Returns:
        dict: 今日目标入口和管理员页面状态的模板上下文。
    """
    identity = getattr(request, 'iwork_identity', None)
    is_admin = bool(identity and identity.subject and identity.is_admin)
    is_iwork_admin = bool(identity and identity.subject and identity.is_iwork_admin)
    can_view_all_targets = is_admin or is_iwork_admin
    can_manage = can_view_all_targets
    if identity and identity.subject and not can_view_all_targets:
        try:
            business_date = get_business_date()
            can_manage = ManagedFlowAssignment.objects.using(LOCAL_DB_ALIAS).filter(
                active_assignment_query(business_date),
                principal__subject=identity.subject,
                flow_name__in=settings.VISIBLE_FLOWS,
            ).exists()
        except Exception as exc:
            # 导航判断失败时隐藏入口，不能把故障误判为有职责权限。
            logger.warning(
                '判断今日目标入口权限失败: subject={} error={}',
                identity.subject,
                exc,
            )
            can_manage = False
    return {
        'can_manage_today_targets': can_manage,
        'today_targets_is_admin': can_view_all_targets,
        'today_targets_is_iwork_admin': is_iwork_admin,
    }


def _with_device_context(request, context):
    """把 User-Agent 设备标记合并到页面上下文。

    Args:
        request: Django HTTP 请求对象。
        context (dict): 页面原有模板上下文。

    Returns:
        dict: 包含设备标记的模板上下文副本。
    """
    return {
        **context,
        **_device_context(request),
        **_today_target_navigation_context(request),
    }


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def dashboard(request):
    """看板主页面（实时视图）"""
    try:
        stats = get_realtime_stats()
    except ReadModelNotReadyError as exc:
        logger.warning('实时首页加载时快照尚未准备好: {}', exc)
        stats = {
            'total_qty': 0,
            'workorder_count': 0,
            'hourly_stats': [],
            'process_flow_stats': [],
            'workorders': [],
            'all_stepnos': [],
        }
    stats_json = json.dumps(stats, cls=DjangoJSONEncoder)
    context = _with_device_context(request, {
        'stats': stats,
        'stats_json': stats_json,
        'page_title': 'PCI生产看板',
        'initial_view': 'realtime',
    })
    return render(request, 'iwork/dashboard.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def history_dashboard(request):
    """看板历史数据页面（独立 URL，不建立 SSE 连接）。"""
    context = _with_device_context(request, {
        'stats': {'total_qty': 0, 'workorder_count': 0},
        'stats_json': '{}',
        'page_title': 'PCI生产看板 - 历史数据',
        'initial_view': 'history',
    })
    return render(request, 'iwork/dashboard.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def today_targets(request):
    """渲染今日目标强制填报和多组快捷输入页面。

    Args:
        request: 当前页面请求；可选 ``next`` 为门禁完成后的站内返回地址。

    Returns:
        HttpResponse: 今日目标输入页面。
    """
    context = _with_device_context(request, {
        'page_title': '今日目标',
        'initial_view': 'today_targets',
        'return_to': _safe_internal_return_path(request.GET.get('next')),
    })
    return render(request, 'iwork/today_targets.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def production_detail(request):
    """生产详情 — Flow 概览页"""
    context = _with_device_context(request, {
        'page_title': 'PCI生产看板 - 生产详情',
        'initial_view': 'overview',
        'detail_type': '',
        'detail_key': '',
    })
    return render(request, 'iwork/production_detail.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def production_detail_flow(request, flow_name):
    """生产详情 — Flow 员工明细"""
    context = _with_device_context(request, {
        'page_title': f'PCI生产看板 - 生产详情 - {flow_name}',
        'initial_view': 'detail',
        'detail_type': 'flow',
        'detail_key': flow_name,
    })
    return render(request, 'iwork/production_detail.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def production_detail_stepno(request, stepno):
    """生产详情 — 工序员工明细"""
    context = _with_device_context(request, {
        'page_title': f'PCI生产看板 - 生产详情 - 工序 {stepno}',
        'initial_view': 'detail',
        'detail_type': 'stepno',
        'detail_key': stepno,
    })
    return render(request, 'iwork/production_detail.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def production_detail_initial_style(request):
    """生产详情 — 初版款号跨生产线员工明细。

    Args:
        request: 必须显式提供 ``initial_style_no`` 查询参数的请求。

    Returns:
        HttpResponse: 初版款号详情页；缺少参数时返回生产详情概览。
    """
    if 'initial_style_no' not in request.GET:
        return redirect('production-detail')
    initial_style_no = str(request.GET.get('initial_style_no') or '').strip()
    label = initial_style_no or '未设置'
    context = _with_device_context(request, {
        'page_title': f'PCI生产看板 - 生产详情 - 初版款号 {label}',
        'initial_view': 'detail',
        'detail_type': 'initial_style',
        'detail_key': initial_style_no,
    })
    return render(request, 'iwork/production_detail.html', context)


@require_http_methods(['GET'])
def kanban_page(request):
    """产量看板页面"""
    context = _with_device_context(request, {
        'page_title': 'PCI生产看板 - 产量看板',
    })
    return render(request, 'iwork/kanban.html', context)
