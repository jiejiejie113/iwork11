import json

from django.shortcuts import render
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.http import require_http_methods
from iwork.statistics import get_realtime_stats


@require_http_methods(['GET'])
def dashboard(request):
    """看板主页面（实时视图）"""
    stats = get_realtime_stats()
    stats_json = json.dumps(stats, cls=DjangoJSONEncoder)
    context = {
        'stats': stats,
        'stats_json': stats_json,
        'page_title': '生产看板',
        'initial_view': 'realtime',
    }
    return render(request, 'iwork/dashboard.html', context)


@require_http_methods(['GET'])
def history_dashboard(request):
    """看板历史数据页面（独立 URL，不连 WebSocket）"""
    context = {
        'stats': {'total_qty': 0, 'workorder_count': 0},
        'stats_json': '{}',
        'page_title': '生产看板 - 历史数据',
        'initial_view': 'history',
    }
    return render(request, 'iwork/dashboard.html', context)


@require_http_methods(['GET'])
def production_detail(request):
    """生产详情 — Flow 概览页"""
    context = {
        'page_title': '生产看板 - 生产详情',
        'initial_view': 'overview',
        'detail_type': '',
        'detail_key': '',
    }
    return render(request, 'iwork/production_detail.html', context)


@require_http_methods(['GET'])
def production_detail_flow(request, flow_name):
    """生产详情 — Flow 员工明细"""
    context = {
        'page_title': f'生产看板 - 生产详情 - {flow_name}',
        'initial_view': 'detail',
        'detail_type': 'flow',
        'detail_key': flow_name,
    }
    return render(request, 'iwork/production_detail.html', context)


@require_http_methods(['GET'])
def production_detail_stepno(request, stepno):
    """生产详情 — 工序员工明细"""
    context = {
        'page_title': f'生产看板 - 生产详情 - 工序 {stepno}',
        'initial_view': 'detail',
        'detail_type': 'stepno',
        'detail_key': stepno,
    }
    return render(request, 'iwork/production_detail.html', context)