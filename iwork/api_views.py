import json
import time
import asyncio

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from django.http import StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import sync_to_async
from datetime import date, datetime
from loguru import logger

from iwork.statistics import (
    PRODUCT_OVERVIEW_CACHE_KEY,
    _seconds_to_midnight,
    get_realtime_stats,
)
from iwork.queries import (
    get_hourly_stats,
    get_flow_detail,
    get_workorder_detail,
    get_monthly_total_trend,
    get_process_by_flow,
    get_process_stats,
    get_heatmap_data,
    get_station_ranking,
    get_workorders_paginated,
    get_all_stepnos as remote_get_all_stepnos,
    get_batch_flow_overview as remote_get_batch_flow_overview,
    get_batch_flow_hourly as remote_get_batch_flow_hourly,
    get_batch_flow_employees as remote_get_batch_flow_employees,
    get_batch_stepno_employees as remote_get_batch_stepno_employees,
    get_batch_product_overview as remote_get_batch_product_overview,
    get_kanban_stats as remote_get_kanban_stats,
    get_kanban_ranking as remote_get_kanban_ranking,
    get_kanban_filter_options as remote_get_kanban_filter_options,
)
from iwork.local_queries import (
    get_all_stepnos as local_get_all_stepnos,
    get_batch_flow_overview as local_get_batch_flow_overview,
    get_batch_flow_hourly as local_get_batch_flow_hourly,
    get_batch_flow_employees as local_get_batch_flow_employees,
    get_batch_stepno_employees as local_get_batch_stepno_employees,
    get_batch_product_overview as local_get_batch_product_overview,
)
from iwork.local_models import TargetProduction
from iwork.request_params import parse_stepno_filter


def _parse_stepno(request) -> list[int] | None:
    """从请求参数解析 StepNo 过滤列表，无参数返回 None（全工序）"""
    return parse_stepno_filter(request)


@api_view(['GET'])
def realtime_stats(request):
    """获取实时统计数据（支持 ?stepno=70,69 过滤工序）"""
    t0 = time.time()
    try:
        stepno_filter = _parse_stepno(request)
        stats = get_realtime_stats(stepno_filter=stepno_filter)
        elapsed = (time.time() - t0) * 1000
        logger.info('GET /api/dashboard/realtime stepno={} qty={} ({:.0f}ms)',
                    stepno_filter or 'all', stats.get('total_qty', 0), elapsed)
        logger.debug('[工序产量对比] /api/dashboard/realtime 完成 stepno={} total_qty={} '
                     'process_flow_stats={}行 hourly_stats={}行 elapsed={:.0f}ms',
                     stepno_filter or 'all',
                     stats.get('total_qty', 0),
                     len(stats.get('process_flow_stats', [])),
                     len(stats.get('hourly_stats', [])),
                     elapsed)
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/dashboard/realtime 失败 ({:.0f}ms): {}', (time.time() - t0) * 1000, e)
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def process_list(request):
    """获取可用工序号列表（实时+历史共用，支持 ?mode=local&date=2026-05-12）"""
    try:
        mode = request.query_params.get('mode', 'remote')
        date_str = request.query_params.get('date', date.today().isoformat())
        date_obj = date.fromisoformat(date_str)

        stepnos = local_get_all_stepnos(date_obj) if mode == 'local' else remote_get_all_stepnos(date_obj)

        return Response({
            'date': date_obj.isoformat(),
            'mode': mode,
            'stepnos': stepnos,
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取工序列表失败: {e}')
        return Response({'error': '获取工序列表失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def hourly_stats(request):
    """获取按小时统计数据"""
    target_date = request.query_params.get('date', date.today().isoformat())
    stepno_filter = _parse_stepno(request)
    cache_key = f'dashboard:hourly:{target_date}:{stepno_filter}'

    stats = cache.get(cache_key)
    if stats is None:
        try:
            target = date.fromisoformat(target_date)
            stats = get_hourly_stats(target, stepno_filter=stepno_filter)
            cache.set(cache_key, stats, 86400)
        except Exception as e:
            logger.error(f'获取小时统计失败: {e}')
            return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(stats, status=status.HTTP_200_OK)


@api_view(['GET'])
def flow_stats(request, flow_name):
    """获取指定 Flow 组统计数据"""
    try:
        today = date.today()
        stats = get_flow_detail(today, flow_name)
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取 Flow 统计失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def workorder_list(request):
    """获取工单列表（分页），支持 ?mode=local&date=2026-05-18"""
    try:
        mode = request.query_params.get('mode', 'remote')
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        stepno_filter = _parse_stepno(request)

        if mode == 'local':
            from iwork.local_queries import get_workorders_paginated as local_paginated
            result = local_paginated(target_date, page=page, page_size=page_size,
                                     stepno_filter=stepno_filter)
        else:
            result = get_workorders_paginated(target_date, page=page, page_size=page_size,
                                              stepno_filter=stepno_filter)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取工单列表失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def workorder_detail(request, wrk_order):
    """获取工单详情"""
    target_date = request.query_params.get('date', date.today().isoformat())

    try:
        target = date.fromisoformat(target_date)
        detail = get_workorder_detail(wrk_order, target)
        return Response(detail, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取工单详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# 新增 API 端点（看板改版 v2）

@api_view(['GET'])
def monthly_trend(request):
    """获取当月总产量日趋势（主题 3c）"""
    try:
        target_date = request.query_params.get('date', date.today().isoformat())
        target = date.fromisoformat(target_date)
        month_start = date(target.year, target.month, 1)
        stepno_filter = _parse_stepno(request)

        stats = get_monthly_total_trend(month_start, target, stepno_filter=stepno_filter)
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取月趋势失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def process_compare(request):
    """获取工序×Flow 产量对比（主题 3a）"""
    t0 = time.time()
    try:
        target_date = request.query_params.get('date', date.today().isoformat())
        target = date.fromisoformat(target_date)

        stepnos_raw = request.query_params.get('stepnos', '')
        if not stepnos_raw:
            # 默认取当天 Top 8 工序
            top = get_process_stats(target, limit=8)
            stepno_list = [p['step'] for p in top]
        else:
            stepno_list = [int(s.strip()) for s in stepnos_raw.split(',') if s.strip().isdigit()]

        stats = get_process_by_flow(target, stepno_list)
        elapsed = (time.time() - t0) * 1000
        logger.info('GET /api/dashboard/process-compare date={} stepnos={} → {}行 ({:.0f}ms)',
                    target_date, stepno_list, len(stats), elapsed)
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('获取工序对比失败 ({:.0f}ms): {}', (time.time() - t0) * 1000, e)
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def heatmap(request):
    """获取热力图数据（主题 5）"""
    try:
        target_date = request.query_params.get('date', date.today().isoformat())
        target = date.fromisoformat(target_date)
        stepno_filter = _parse_stepno(request)

        stats = get_heatmap_data(target, stepno_filter=stepno_filter)
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取热力图数据失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def station_ranking(request):
    """获取工站产量排行（主题 6）"""
    try:
        target_date = request.query_params.get('date', date.today().isoformat())
        target = date.fromisoformat(target_date)
        limit = int(request.query_params.get('limit', 15))
        stepno_filter = _parse_stepno(request)

        stats = get_station_ranking(target, limit=limit, stepno_filter=stepno_filter)
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取工站排行失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# 生产详情 API 端点


def _get_targets_with_fallback(target_date):
    """
    获取目标产量（优先 Redis → 回退数据库）

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {employee_id_str: target_qty}
    """
    date_str = target_date.isoformat()

    # 1. 优先读 Redis
    key = f'targets:{date_str}'
    cached = cache.get(key)
    if cached:
        return json.loads(cached)

    # 2. Redis 未命中，读数据库
    try:
        targets = TargetProduction.objects.filter(
            target_date=target_date, workorder=''
        ).values_list('employee_id', 'target_qty')
        targets_dict = {eid: qty for eid, qty in targets}

        # 3. 回写 Redis 缓存
        if targets_dict:
            cache.set(key, json.dumps(targets_dict), timeout=_seconds_to_midnight())

        return targets_dict
    except Exception as e:
        logger.error(f'从数据库读取目标产量失败: {e}')
        return {}


def _get_wo_targets_with_fallback(target_date):
    """
    获取工单级目标产量（优先 Redis → 回退数据库）

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {f"{employee_id}@{workorder}": target_qty}
    """
    date_str = target_date.isoformat()
    key = f'wo_targets:{date_str}'
    cached = cache.get(key)
    if cached:
        return json.loads(cached)

    try:
        rows = TargetProduction.objects.filter(
            target_date=target_date
        ).exclude(workorder='').values_list('employee_id', 'workorder', 'target_qty')
        result = {}
        for eid, wo, qty in rows:
            result[f'{eid}@{wo}'] = qty
        if result:
            cache.set(key, json.dumps(result), timeout=_seconds_to_midnight())
        return result
    except Exception as e:
        logger.error(f'从数据库读取工单目标产量失败: {e}')
        return {}


def _get_flow_detail_data(flow_name, target_date, mode='remote'):
    """
    获取指定 Flow 的完整详情数据

    Args:
        flow_name (str): Flow 名称
        target_date (date): 目标日期
        mode (str): 'remote' 远程数据库 / 'local' 本地数据库

    Returns:
        dict: 包含 flow、date、total_qty、worker_count、hourly_trend、employees
    """
    if mode == 'local':
        employees_data = local_get_batch_flow_employees(target_date)
        hourly_data = local_get_batch_flow_hourly(target_date)
    else:
        employees_data = remote_get_batch_flow_employees(target_date)
        hourly_data = remote_get_batch_flow_hourly(target_date)

    employees = employees_data.get(flow_name, [])
    total_qty = sum(e['total_qty'] for e in employees)

    # 读取已保存的目标产量并注入到员工数据中
    targets_dict = _get_targets_with_fallback(target_date)
    wo_targets_dict = _get_wo_targets_with_fallback(target_date)
    for emp in employees:
        eid = str(emp['reg_per_sys_id'])
        emp['target'] = int(targets_dict.get(eid, 0))
        emp['wo_targets'] = {k.split('@')[1]: v for k, v in wo_targets_dict.items() if k.startswith(eid + '@')}

    return {
        'flow': flow_name,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'worker_count': len(employees),
        'hourly_trend': hourly_data.get(flow_name, []),
        'employees': employees,
    }


def _get_stepno_detail_data(stepno, target_date, mode='remote'):
    """
    获取指定 StepNo 的完整详情数据

    Args:
        stepno (int): 工序号
        target_date (date): 目标日期
        mode (str): 'remote' 远程数据库 / 'local' 本地数据库

    Returns:
        dict: 包含 stepno、date、total_qty、worker_count、employees
    """
    if mode == 'local':
        stepno_data = local_get_batch_stepno_employees(target_date)
    else:
        stepno_data = remote_get_batch_stepno_employees(target_date)

    employees = stepno_data.get(stepno, [])
    total_qty = sum(e['qty'] for e in employees)

    # 读取已保存的目标产量并注入到员工数据中
    targets_dict = _get_targets_with_fallback(target_date)
    for emp in employees:
        emp['target'] = int(targets_dict.get(str(emp['reg_per_sys_id']), 0))

    return {
        'stepno': stepno,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'worker_count': len(employees),
        'employees': employees,
    }


@api_view(['GET'])
def stepno_overview(request):
    """
    获取工序概览汇总（从 Redis 缓存一次读取，消除 N+1 查询）

    支持参数：
        ?date=...    目标日期（默认今日）
    """
    try:
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)

        if target_date == date.today():
            cached = cache.get('stats:detail:stepno_overview')
            if cached is not None:
                result = {}
                for stepno, emps in cached.items():
                    total_qty = sum(e['qty'] for e in emps)
                    result[stepno] = {'total_qty': total_qty, 'worker_count': len(emps)}
                return Response(result, status=status.HTTP_200_OK)

        # 历史日期或缓存未命中，实时查询
        stepno_data = remote_get_batch_stepno_employees(target_date)
        result = {}
        for stepno, emps in stepno_data.items():
            total_qty = sum(e['qty'] for e in emps)
            result[stepno] = {'total_qty': total_qty, 'worker_count': len(emps)}
        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f'获取工序概览失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def flow_overview(request):
    """
    获取 Flow 概览（今日优先读取 Redis 缓存）

    支持参数：
        ?date=...    目标日期（默认今日）
        ?mode=local  历史视图模式
    """
    try:
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = request.query_params.get('mode', 'remote')

        # 今日优先读 Redis
        if target_date == date.today() and mode == 'remote':
            cached = cache.get('stats:detail:flow_overview')
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        if mode == 'local':
            result = local_get_batch_flow_overview(target_date)
        else:
            result = remote_get_batch_flow_overview(target_date)

        # 今日结果写入 Redis（当天有效）
        if target_date == date.today() and mode == 'remote':
            cache.set('stats:detail:flow_overview', result, 3600)

        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取 Flow 概览失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def flow_detail(request, flow_name):
    """
    获取指定 Flow 的员工明细

    支持参数：
        ?date=...    目标日期（默认今日）
        ?mode=local  历史视图模式
    """
    try:
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = request.query_params.get('mode', 'remote')

        # 今日优先读缓存，所有字段统一来自 Redis 快照，避免混用新旧数据
        if target_date == date.today() and mode == 'remote':
            cached_employees = cache.get(f'stats:detail:flow:{flow_name}')
            if cached_employees is not None:
                total_qty = sum(e['total_qty'] for e in cached_employees)
                hourly_cache = cache.get('stats:detail:flow_hourly') or {}
                hourly_trend = hourly_cache.get(flow_name, [])
                targets_key = f'targets:{target_date.isoformat()}:{flow_name}'
                cached_targets = cache.get(targets_key)
                targets_dict = json.loads(cached_targets) if cached_targets else {}
                wo_targets_dict = _get_wo_targets_with_fallback(target_date)
                for emp in cached_employees:
                    eid = str(emp['reg_per_sys_id'])
                    emp['target'] = int(targets_dict.get(eid, 0))
                    emp['wo_targets'] = {k.split('@')[1]: v for k, v in wo_targets_dict.items() if k.startswith(eid + '@')}
                return Response({
                    'flow': flow_name,
                    'date': target_date.isoformat(),
                    'total_qty': total_qty,
                    'worker_count': len(cached_employees),
                    'hourly_trend': hourly_trend,
                    'employees': cached_employees,
                }, status=status.HTTP_200_OK)

        result = _get_flow_detail_data(flow_name, target_date, mode)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取 Flow 详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def stepno_detail(request, stepno):
    """
    获取指定工序的员工明细

    支持参数：
        ?date=...    目标日期（默认今日）
        ?mode=local  历史视图模式
    """
    try:
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = request.query_params.get('mode', 'remote')

        result = _get_stepno_detail_data(stepno, target_date, mode)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取工序详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def product_overview(request):
    """
    获取按产品名称分组的概览数据（今日优先读取 Redis 缓存）

    支持参数：
        ?date=...    目标日期（默认今日）
        ?mode=local  历史视图模式
    """
    try:
        date_str = request.query_params.get('date', date.today().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = request.query_params.get('mode', 'remote')

        if target_date == date.today() and mode == 'remote':
            cached = cache.get(PRODUCT_OVERVIEW_CACHE_KEY)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        if mode == 'local':
            result = local_get_batch_product_overview(target_date)
        else:
            result = remote_get_batch_product_overview(target_date)

        if target_date == date.today() and mode == 'remote':
            cache.set(PRODUCT_OVERVIEW_CACHE_KEY, result, 3600)

        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取产品概览失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# SSE 实时推送 + 目标产量设置
# ============================================================================


@csrf_exempt
async def dashboard_stream(request):
    """
    SSE 实时推送流（异步，每 60s 从 Redis 读缓存推送给客户端）

    支持参数：
        ?stepno=70    过滤工序号（可选）

    异步实现：每个连接仅占一个 asyncio 协程（~KB 级），不占用 worker 进程。
    通过 sync_to_async 将同步 Redis 读取放到线程池，不阻塞事件循环。
    """
    stepno_filter = _parse_stepno(request)

    @sync_to_async
    def _get_data():
        stats = get_realtime_stats(stepno_filter=stepno_filter)
        process_list = cache.get('stats:realtime:_process_list') or []
        detail_overview = cache.get('stats:detail:flow_overview') or []
        return stats, process_list, detail_overview

    async def event_stream():
        while True:
            try:
                stats, process_list, detail_overview = await _get_data()
                data = {
                    'type': 'dashboard_update',
                    'timestamp': datetime.now().isoformat(),
                    'data': stats,
                    'process_list': process_list,
                    'detail_overview': detail_overview,
                }
                yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            except Exception as e:
                logger.error('SSE 数据获取失败: {}', e)
            # 心跳保活：60秒内每15秒发一次SSE注释，防止Nginx/浏览器断开
            for _ in range(4):
                await asyncio.sleep(15)
                yield ": heartbeat\n\n"

    return StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@api_view(['POST'])
def set_targets(request):
    """
    设置目标产量（HTTP POST）

    请求体（支持两种格式，向后兼容）：
        targets (dict): {reg_per_sys_id: target_qty}（旧格式，仍支持）
        wo_targets (dict): {"1001@WO-001": 150, "1001@WO-002": 150}（新格式）

    工单级目标：每个工单独立一行存储
    员工总目标：由工单目标自动聚合计算
    """
    targets = request.data.get('targets', {})
    wo_targets = request.data.get('wo_targets', {})
    today = date.today()

    # 1. 保存工单级目标到数据库
    if wo_targets:
        for key, qty in wo_targets.items():
            parts = key.split('@', 1)
            if len(parts) != 2:
                continue
            emp_id, workorder = parts
            qty_int = int(qty) if qty else 0
            TargetProduction.objects.update_or_create(
                target_date=today,
                employee_id=str(emp_id),
                workorder=workorder,
                defaults={'target_qty': qty_int},
            )
        logger.info(f'工单目标已保存: {len(wo_targets)} 条')

        # 自动聚合计算员工总目标
        targets = {}
        for key, qty in wo_targets.items():
            emp_id = key.split('@')[0]
            targets[emp_id] = targets.get(emp_id, 0) + (int(qty) or 0)

    # 2. 保存员工总目标到数据库（兼容旧格式 + 工单聚合结果）
    if targets:
        try:
            for emp_id, qty in targets.items():
                qty_int = int(qty) if qty else 0
                if qty_int > 0:
                    TargetProduction.objects.update_or_create(
                        target_date=today,
                        employee_id=str(emp_id),
                        workorder='',
                        defaults={'target_qty': qty_int}
                    )
            logger.info(f'员工总目标已保存: {len(targets)} 条')
        except Exception as e:
            logger.error(f'目标产量保存到数据库失败: {e}')

    # 3. 写入 Redis 缓存
    if targets:
        key = f'targets:{today.isoformat()}'
        cache.set(key, json.dumps(targets), timeout=_seconds_to_midnight())
    if wo_targets:
        key = f'wo_targets:{today.isoformat()}'
        cache.set(key, json.dumps(wo_targets), timeout=_seconds_to_midnight())
        logger.info(f'工单目标已缓存到 Redis: {key}')

    return Response({'status': 'ok', 'count': len(targets), 'wo_count': len(wo_targets)})


# ============================================================================
# 产量看板 API
# ============================================================================

def _parse_kanban_date(request):
    """解析产量看板日期参数，返回 (date对象, None) 或 (None, 错误Response)"""
    params = getattr(request, 'query_params', request.GET)
    date_str = params.get('date', '')
    if not date_str:
        return None, Response(
            {'error': '缺少日期参数，格式为 YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date(), None
    except ValueError:
        return None, Response(
            {'error': '日期格式错误，需为 YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET'])
def kanban_stats(request):
    """产量看板统计汇总 API

    Query params:
        date (str): YYYY-MM-DD（必填）
        stepno (str): 工序号（选填，可多传，默认 ['70']）
        wrk_order (str): 款号（选填，可多传）
        flow (str): 分组（选填，可多传）
        reg_per_sys_id (str): 员工（选填，可多传）
    """
    target_date, err = _parse_kanban_date(request)
    if err:
        return err

    params = request.query_params
    stepnos = params.getlist('stepno') or None
    wrk_orders = params.getlist('wrk_order') or None
    flows = params.getlist('flow') or None
    reg_per_sys_ids = params.getlist('reg_per_sys_id') or None
    show_all_flows = params.get('show_all_flows', 'false').lower() == 'true'

    try:
        stats = remote_get_kanban_stats(
            target_date, stepnos=stepnos, wrk_orders=wrk_orders,
            flows=flows, reg_per_sys_ids=reg_per_sys_ids,
            show_all_flows=show_all_flows,
        )
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/kanban/stats/ 失败: {}', e)
        return Response(
            {'error': '获取统计数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def kanban_ranking(request):
    """产量看板排行榜 API

    Query params:
        date (str): YYYY-MM-DD（必填）
        stepno (str): 工序号（选填，可多传，默认 ['70']）
        wrk_order (str): 款号（选填，可多传）
        flow (str): 分组（选填，可多传）
        reg_per_sys_id (str): 员工（选填，可多传）
        page (int): 页码（选填，默认 1）
        page_size (int): 每页条数（选填，默认 50）
    """
    target_date, err = _parse_kanban_date(request)
    if err:
        return err

    params = request.query_params
    stepnos = params.getlist('stepno') or None
    wrk_orders = params.getlist('wrk_order') or None
    flows = params.getlist('flow') or None
    reg_per_sys_ids = params.getlist('reg_per_sys_id') or None
    show_all_flows = params.get('show_all_flows', 'false').lower() == 'true'

    try:
        page = int(params.get('page', 1))
        page_size = int(params.get('page_size', 50))
    except ValueError:
        return Response(
            {'error': 'page 和 page_size 需为整数'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        result = remote_get_kanban_ranking(
            target_date, stepnos=stepnos, wrk_orders=wrk_orders,
            flows=flows, reg_per_sys_ids=reg_per_sys_ids,
            page=page, page_size=page_size,
            show_all_flows=show_all_flows,
        )
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/kanban/ranking/ 失败: {}', e)
        return Response(
            {'error': '获取排行榜数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def kanban_filter_options(request):
    """产量看板筛选项 API（级联筛选）

    Query params:
        date (str): YYYY-MM-DD（必填）
        stepno (str): 当前工序（选填，可多传）
        wrk_order (str): 当前款号（选填，可多传）
        flow (str): 当前分组（选填，可多传）
        reg_per_sys_id (str): 当前员工（选填，可多传）
    """
    target_date, err = _parse_kanban_date(request)
    if err:
        return err

    params = request.query_params
    stepnos = params.getlist('stepno') or None
    wrk_orders = params.getlist('wrk_order') or None
    flows = params.getlist('flow') or None
    reg_per_sys_ids = params.getlist('reg_per_sys_id') or None
    show_all_flows = params.get('show_all_flows', 'false').lower() == 'true'

    try:
        options = remote_get_kanban_filter_options(
            target_date, stepnos=stepnos, wrk_orders=wrk_orders,
            flows=flows, reg_per_sys_ids=reg_per_sys_ids,
            show_all_flows=show_all_flows,
        )
        return Response(options, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error('GET /api/kanban/filter-options/ 失败: {}', e)
        return Response(
            {'error': '获取筛选项失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
