import json
import re

from django.shortcuts import redirect, render
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.http import require_http_methods
from django.views.decorators.vary import vary_on_headers
from loguru import logger

from iwork.read_model.errors import ReadModelNotReadyError
from iwork.statistics import get_realtime_stats


MOBILE_USER_AGENT_RE = re.compile(
    r"(?:android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini|"
    r"opera mobi|windows phone|mobile|tablet|kindle|silk|fennec)",
    re.IGNORECASE,
)


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


def _with_device_context(request, context):
    """把 User-Agent 设备标记合并到页面上下文。

    Args:
        request: Django HTTP 请求对象。
        context (dict): 页面原有模板上下文。

    Returns:
        dict: 包含设备标记的模板上下文副本。
    """
    return {**context, **_device_context(request)}


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
        'page_title': 'Eastex生产看板',
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
        'page_title': 'Eastex生产看板 - 历史数据',
        'initial_view': 'history',
    })
    return render(request, 'iwork/dashboard.html', context)


@vary_on_headers('User-Agent')
@require_http_methods(['GET'])
def production_detail(request):
    """生产详情 — Flow 概览页"""
    context = _with_device_context(request, {
        'page_title': 'Eastex生产看板 - 生产详情',
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
        'page_title': f'Eastex生产看板 - 生产详情 - {flow_name}',
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
        'page_title': f'Eastex生产看板 - 生产详情 - 工序 {stepno}',
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
        'page_title': f'Eastex生产看板 - 生产详情 - 初版款号 {label}',
        'initial_view': 'detail',
        'detail_type': 'initial_style',
        'detail_key': initial_style_no,
    })
    return render(request, 'iwork/production_detail.html', context)


@require_http_methods(['GET'])
def kanban_page(request):
    """产量看板页面"""
    context = {
        'page_title': 'Eastex生产看板 - 产量看板',
    }
    return render(request, 'iwork/kanban.html', context)
