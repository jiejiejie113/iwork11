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
    _seconds_to_midnight,
    calculate_employee_efficiency,
    get_business_date,
    get_effective_work_minutes,
    get_local_date_stats,
)
from iwork.historical_queries import (
    get_all_stepnos as local_get_all_stepnos,
    get_batch_flow_overview as local_get_batch_flow_overview,
    get_batch_flow_hourly as local_get_batch_flow_hourly,
    get_batch_flow_employees as local_get_batch_flow_employees,
    get_batch_product_overview as local_get_batch_product_overview,
    get_batch_stepno_employees as local_get_batch_stepno_employees,
    get_workorders_paginated as local_get_workorders_paginated,
)
from iwork.local_queries import (
    get_kanban_filter_options as local_get_kanban_filter_options,
    get_kanban_ranking as local_get_kanban_ranking,
    get_kanban_stats as local_get_kanban_stats,
    get_workorder_detail as local_get_workorder_detail,
)
from iwork.local_models import HistoricalSyncState, TargetProduction
from iwork.read_model.errors import ReadModelNotReadyError
from iwork.read_model.queries import ReadModelQueries
from iwork.read_model.store import SnapshotReadResult
from iwork.request_params import parse_stepno_filter


# ======
# 统一实时读模型
READ_MODEL = ReadModelQueries()


def _parse_stepno(request) -> list[int] | None:
    """从请求参数解析 StepNo 过滤列表，无参数返回 None（全工序）"""
    return parse_stepno_filter(request)


def _detail_mode(request, target_date: date) -> str:
    """历史日期只读本地快照，今日数据读取实时源。"""
    return 'local' if target_date < get_business_date() else 'remote'


def _snapshot_state(target_date: date):
    """获取指定日期已成功发布的历史快照状态。

    Args:
        target_date: 需要查询的生产日期。

    Returns:
        成功状态记录；不存在时返回 None。
    """
    return HistoricalSyncState.objects.using('iwork_local').filter(
        snapshot_date=target_date,
        status=HistoricalSyncState.Status.SUCCESS,
    ).first()


def _snapshot_not_found_response():
    """构造历史快照不存在的统一 HTTP 404 响应。"""
    return Response(
        {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
        status=status.HTTP_404_NOT_FOUND,
    )


def _snapshot_response(
    result: SnapshotReadResult,
    response_status: int = status.HTTP_200_OK,
) -> Response:
    """构造带快照版本、生成时间和陈旧标记的响应。

    Args:
        result: 统一读模型查询结果。
        response_status: HTTP 状态码。

    Returns:
        注入快照响应头的 DRF 响应。
    """
    response = Response(result.data, status=response_status)
    response["X-Iwork-Snapshot-Version"] = result.metadata["snapshot_version"]
    response["X-Iwork-Generated-At"] = result.metadata["generated_at"]
    response["X-Iwork-Stale"] = "true" if result.stale else "false"
    return response


def _read_model_unavailable_response(exc: ReadModelNotReadyError) -> Response:
    """将实时读模型不可用转换为统一 503 响应。"""
    logger.warning("实时读模型暂不可用: {}", exc)
    return Response(
        {
            "error": "实时数据暂不可用，请稍后重试",
            "code": "realtime_snapshot_unavailable",
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@api_view(['GET'])
def realtime_stats(request):
    """获取实时统计数据（支持 ?stepno=70,69 过滤工序）"""
    t0 = time.time()
    try:
        stepno_filter = _parse_stepno(request)
        result = READ_MODEL.realtime(get_business_date(), stepno_filter)
        stats = result.data
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
        return _snapshot_response(result)
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error('GET /api/dashboard/realtime 失败 ({:.0f}ms): {}', (time.time() - t0) * 1000, e)
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def process_list(request):
    """获取可用工序号列表；历史日期自动读取本地快照。"""
    try:
        date_str = request.query_params.get('date', get_business_date().isoformat())
        date_obj = date.fromisoformat(date_str)
        mode = _detail_mode(request, date_obj)

        if mode == 'local' and _snapshot_state(date_obj) is None:
            return _snapshot_not_found_response()

        if mode == 'local':
            stepnos = local_get_all_stepnos(date_obj)
            return Response({
                'date': date_obj.isoformat(),
                'mode': mode,
                'stepnos': stepnos,
            }, status=status.HTTP_200_OK)

        result = READ_MODEL.processes(date_obj)
        stepnos = result.data

        return _snapshot_response(SnapshotReadResult(data={
            'date': date_obj.isoformat(),
            'mode': mode,
            'stepnos': stepnos,
        }, metadata=result.metadata, stale=result.stale))

    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取工序列表失败: {e}')
        return Response({'error': '获取工序列表失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def hourly_stats(request):
    """获取按小时统计数据"""
    try:
        target = date.fromisoformat(
            request.query_params.get('date', get_business_date().isoformat())
        )
        stepno_filter = _parse_stepno(request)
        if target < get_business_date():
            if _snapshot_state(target) is None:
                return _snapshot_not_found_response()
            return Response(
                get_local_date_stats(target, stepno_filter=stepno_filter)['hourly_stats'],
                status=status.HTTP_200_OK,
            )
        result = READ_MODEL.realtime(target, stepno_filter)
        return _snapshot_response(SnapshotReadResult(
            data=result.data.get('hourly_stats', []),
            metadata=result.metadata,
            stale=result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as exc:
        logger.error('获取小时统计失败: {}', exc)
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def flow_stats(request, flow_name):
    """获取指定 Flow 组统计数据"""
    try:
        today = get_business_date()
        result = READ_MODEL.details(today)
        employees = result.data.get('flow_employees', {}).get(flow_name, [])
        stats = {
            'flow': flow_name,
            'total_qty': sum(item.get('total_qty', 0) for item in employees),
            'worker_count': len(employees),
        }
        return _snapshot_response(SnapshotReadResult(
            data=stats,
            metadata=result.metadata,
            stale=result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取 Flow 统计失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def workorder_list(request):
    """获取工单列表（分页）；历史日期自动读取本地快照。"""
    try:
        date_str = request.query_params.get('date', get_business_date().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        stepno_filter = _parse_stepno(request)

        if mode == 'local' and _snapshot_state(target_date) is None:
            return _snapshot_not_found_response()

        if mode == 'local':
            result = local_get_workorders_paginated(
                target_date,
                page=page,
                page_size=page_size,
                stepno_filter=stepno_filter,
            )
            return Response(result, status=status.HTTP_200_OK)
        result = READ_MODEL.workorders(
            target_date,
            page=page,
            page_size=page_size,
            stepnos=stepno_filter,
        )
        return _snapshot_response(result)
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取工单列表失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def workorder_detail(request, wrk_order):
    """获取工单详情；历史日期自动读取本地快照。"""
    target_date = request.query_params.get('date', get_business_date().isoformat())

    try:
        target = date.fromisoformat(target_date)
        mode = _detail_mode(request, target)
        if mode == 'local' and _snapshot_state(target) is None:
            return _snapshot_not_found_response()
        if mode == 'local':
            detail = local_get_workorder_detail(wrk_order, target)
            return Response(detail, status=status.HTTP_200_OK)
        return _snapshot_response(READ_MODEL.workorder_detail(target, wrk_order))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取工单详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# 新增 API 端点（看板改版 v2）

@api_view(['GET'])
def monthly_trend(request):
    """获取当月总产量日趋势（主题 3c）"""
    try:
        target_date = request.query_params.get('date', get_business_date().isoformat())
        target = date.fromisoformat(target_date)
        stepno_filter = _parse_stepno(request)
        if target < get_business_date():
            if _snapshot_state(target) is None:
                return _snapshot_not_found_response()
            return Response(
                get_local_date_stats(target, stepno_filter=stepno_filter)['monthly_total_trend'],
                status=status.HTTP_200_OK,
            )
        result = READ_MODEL.realtime(target, stepno_filter)
        return _snapshot_response(SnapshotReadResult(
            data=result.data.get('monthly_total_trend', []),
            metadata=result.metadata,
            stale=result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取月趋势失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def process_compare(request):
    """获取工序×Flow 产量对比（主题 3a）"""
    t0 = time.time()
    try:
        target_date = request.query_params.get('date', get_business_date().isoformat())
        target = date.fromisoformat(target_date)

        stepnos_raw = request.query_params.get('stepnos', '')
        stepno_list = [int(s.strip()) for s in stepnos_raw.split(',') if s.strip().isdigit()]
        if target < get_business_date():
            if _snapshot_state(target) is None:
                return _snapshot_not_found_response()
            local_stats = get_local_date_stats(
                target,
                stepno_filter=stepno_list or None,
            )
            stats = local_stats.get('process_flow_stats', [])
            if not stepno_list:
                top_steps = {
                    item.get('step')
                    for item in local_stats.get('top_processes', [])[:8]
                }
                stats = [item for item in stats if item.get('step') in top_steps]
            return Response(stats, status=status.HTTP_200_OK)

        result = READ_MODEL.realtime(target, stepno_list or None)
        stats = result.data.get('process_flow_stats', [])
        if not stepno_list:
            top_steps = {
                item.get('step')
                for item in result.data.get('top_processes', [])[:8]
            }
            stats = [item for item in stats if item.get('step') in top_steps]
        elapsed = (time.time() - t0) * 1000
        logger.info('GET /api/dashboard/process-compare date={} stepnos={} → {}行 ({:.0f}ms)',
                    target_date, stepno_list, len(stats), elapsed)
        return _snapshot_response(SnapshotReadResult(
            data=stats,
            metadata=result.metadata,
            stale=result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error('获取工序对比失败 ({:.0f}ms): {}', (time.time() - t0) * 1000, e)
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def heatmap(request):
    """获取热力图数据（主题 5）"""
    try:
        target_date = request.query_params.get('date', get_business_date().isoformat())
        target = date.fromisoformat(target_date)
        stepno_filter = _parse_stepno(request)

        if target < get_business_date():
            if _snapshot_state(target) is None:
                return _snapshot_not_found_response()
            return Response(
                get_local_date_stats(
                    target,
                    stepno_filter=stepno_filter,
                ).get('heatmap_matrix', {}),
                status=status.HTTP_200_OK,
            )

        result = READ_MODEL.realtime(target, stepno_filter)
        return _snapshot_response(SnapshotReadResult(
            data=result.data.get('heatmap_matrix', {}),
            metadata=result.metadata,
            stale=result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取热力图数据失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def station_ranking(request):
    """获取工站产量排行（主题 6）"""
    try:
        target_date = request.query_params.get('date', get_business_date().isoformat())
        target = date.fromisoformat(target_date)
        limit = int(request.query_params.get('limit', 15))
        stepno_filter = _parse_stepno(request)

        if target < get_business_date():
            if _snapshot_state(target) is None:
                return _snapshot_not_found_response()
            return Response(
                get_local_date_stats(
                    target,
                    stepno_filter=stepno_filter,
                ).get('station_ranking', [])[:limit],
                status=status.HTTP_200_OK,
            )

        result = READ_MODEL.realtime(target, stepno_filter)
        return _snapshot_response(SnapshotReadResult(
            data=result.data.get('station_ranking', [])[:limit],
            metadata=result.metadata,
            stale=result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
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


def _with_employee_efficiency(employees, target_date):
    """复制员工快照并按请求时刻注入有效上班分钟对应的效率。"""
    work_minutes = get_effective_work_minutes(target_date)
    enriched = []
    for employee in employees:
        item = dict(employee)
        item['employee_efficiency'] = calculate_employee_efficiency(
            item.get('output_value'),
            work_minutes,
        )
        enriched.append(item)
    return work_minutes, enriched


def _get_flow_detail_data(flow_name, target_date, mode='remote', detail_payload=None):
    """
    获取指定 Flow 的完整详情数据

    Args:
        flow_name (str): Flow 名称
        target_date (date): 目标日期
        mode (str): 'remote' 实时快照 / 'local' 本地历史数据库。
        detail_payload (dict | None): 已固定版本的完整详情快照。

    Returns:
        dict: 包含 flow、date、total_qty、worker_count、hourly_trend、employees
    """
    if mode == 'local':
        employees_data = local_get_batch_flow_employees(target_date)
        hourly_data = local_get_batch_flow_hourly(target_date)
    else:
        detail_payload = detail_payload or READ_MODEL.details(target_date).data
        employees_data = detail_payload.get('flow_employees', {})
        hourly_data = detail_payload.get('flow_hourly', {})

    employees = [dict(item) for item in employees_data.get(flow_name, [])]
    total_qty = sum(e['total_qty'] for e in employees)

    # 读取已保存的目标产量并注入到员工数据中
    targets_dict = _get_targets_with_fallback(target_date)
    wo_targets_dict = _get_wo_targets_with_fallback(target_date)
    for emp in employees:
        eid = str(emp['reg_per_sys_id'])
        emp['target'] = int(targets_dict.get(eid, 0))
        emp['wo_targets'] = {k.split('@')[1]: v for k, v in wo_targets_dict.items() if k.startswith(eid + '@')}

    work_minutes, employees = _with_employee_efficiency(employees, target_date)

    result = {
        'flow': flow_name,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'worker_count': len(employees),
        'work_minutes': work_minutes,
        'hourly_trend': hourly_data.get(flow_name, []),
        'employees': employees,
    }
    if mode == 'local':
        state = _snapshot_state(target_date)
        result.update({
            'source': 'local_snapshot',
            'snapshot_date': target_date.isoformat(),
            'snapshot_version': state.snapshot_version if state else None,
        })
    else:
        result['source'] = 'redis_snapshot'
    return result


def _get_stepno_detail_data(stepno, target_date, mode='remote', detail_payload=None):
    """
    获取指定 StepNo 的完整详情数据

    Args:
        stepno (int): 工序号
        target_date (date): 目标日期
        mode (str): 'remote' 实时快照 / 'local' 本地历史数据库。
        detail_payload (dict | None): 已固定版本的完整详情快照。

    Returns:
        dict: 包含 stepno、date、total_qty、worker_count、employees
    """
    if mode == 'local':
        stepno_data = local_get_batch_stepno_employees(target_date)
    else:
        detail_payload = detail_payload or READ_MODEL.details(target_date).data
        stepno_data = detail_payload.get('stepno_employees', {})

    employees = [dict(item) for item in stepno_data.get(stepno, [])]
    total_qty = sum(e['qty'] for e in employees)

    # 读取已保存的目标产量并注入到员工数据中
    targets_dict = _get_targets_with_fallback(target_date)
    for emp in employees:
        emp['target'] = int(targets_dict.get(str(emp['reg_per_sys_id']), 0))

    result = {
        'stepno': stepno,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'worker_count': len(employees),
        'employees': employees,
    }
    result['source'] = 'local_snapshot' if mode == 'local' else 'redis_snapshot'
    if mode == 'local':
        result['snapshot_date'] = target_date.isoformat()
    return result


@api_view(['GET'])
def stepno_overview(request):
    """
    获取工序概览汇总（从 Redis 缓存一次读取，消除 N+1 查询）

    支持参数：
        ?date=...    目标日期（默认今日）
    """
    try:
        business_today = get_business_date()
        date_str = request.query_params.get('date', business_today.isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)

        if mode == 'local' and _snapshot_state(target_date) is None:
            return Response(
                {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if mode == 'local':
            stepno_data = local_get_batch_stepno_employees(target_date)
            snapshot_result = None
        else:
            snapshot_result = READ_MODEL.details(target_date)
            stepno_data = snapshot_result.data.get('stepno_employees', {})
        result = {}
        for stepno, emps in stepno_data.items():
            total_qty = sum(e['qty'] for e in emps)
            result[stepno] = {'total_qty': total_qty, 'worker_count': len(emps)}
        if snapshot_result is None:
            return Response(result, status=status.HTTP_200_OK)
        return _snapshot_response(SnapshotReadResult(
            data=result,
            metadata=snapshot_result.metadata,
            stale=snapshot_result.stale,
        ))

    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取工序概览失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def flow_overview(request):
    """
    获取 Flow 概览（今日优先读取 Redis 缓存）

    支持参数：
        ?date=...    目标日期（默认今日）
    """
    try:
        business_today = get_business_date()
        date_str = request.query_params.get('date', business_today.isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)

        if mode == 'local' and _snapshot_state(target_date) is None:
            return Response(
                {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if mode == 'local':
            result = local_get_batch_flow_overview(target_date)
            return Response(result, status=status.HTTP_200_OK)
        return _snapshot_response(READ_MODEL.detail(target_date, 'flow_overview'))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取 Flow 概览失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def flow_detail(request, flow_name):
    """
    获取指定 Flow 的员工明细

    支持参数：
        ?date=...    目标日期（默认今日）
    """
    try:
        business_today = get_business_date()
        date_str = request.query_params.get('date', business_today.isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)

        if mode == 'local' and _snapshot_state(target_date) is None:
            return Response(
                {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if mode == 'local':
            return Response(
                _get_flow_detail_data(flow_name, target_date, mode),
                status=status.HTTP_200_OK,
            )
        snapshot_result = READ_MODEL.details(target_date)
        result = _get_flow_detail_data(
            flow_name,
            target_date,
            mode,
            detail_payload=snapshot_result.data,
        )
        return _snapshot_response(SnapshotReadResult(
            data=result,
            metadata=snapshot_result.metadata,
            stale=snapshot_result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取 Flow 详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def stepno_detail(request, stepno):
    """
    获取指定工序的员工明细

    支持参数：
        ?date=...    目标日期（默认今日）
    """
    try:
        date_str = request.query_params.get('date', get_business_date().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)

        if mode == 'local' and _snapshot_state(target_date) is None:
            return Response(
                {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if mode == 'local':
            return Response(
                _get_stepno_detail_data(stepno, target_date, mode),
                status=status.HTTP_200_OK,
            )
        snapshot_result = READ_MODEL.details(target_date)
        result = _get_stepno_detail_data(
            stepno,
            target_date,
            mode,
            detail_payload=snapshot_result.data,
        )
        return _snapshot_response(SnapshotReadResult(
            data=result,
            metadata=snapshot_result.metadata,
            stale=snapshot_result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error(f'获取工序详情失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def product_overview(request):
    """
    获取按产品名称分组的概览数据（今日优先读取 Redis 缓存）

    支持参数：
        ?date=...    目标日期（默认今日）
    """
    try:
        business_today = get_business_date()
        date_str = request.query_params.get('date', business_today.isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)

        if mode == 'local' and _snapshot_state(target_date) is None:
            return Response(
                {'error': '该日期尚未生成本地历史快照', 'code': 'history_snapshot_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if mode == 'local':
            result = local_get_batch_product_overview(target_date)
            state = _snapshot_state(target_date)
            result.update({
                'source': 'local_snapshot',
                'snapshot_date': target_date.isoformat(),
                'snapshot_version': state.snapshot_version if state else None,
            })
            return Response(result, status=status.HTTP_200_OK)
        snapshot_result = READ_MODEL.detail(target_date, 'product_overview')
        result = dict(snapshot_result.data)
        result['source'] = 'redis_snapshot'
        return _snapshot_response(SnapshotReadResult(
            data=result,
            metadata=snapshot_result.metadata,
            stale=snapshot_result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
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
        return READ_MODEL.stream_payload(get_business_date(), stepno_filter)

    async def event_stream():
        while True:
            try:
                result = await _get_data()
                data = {
                    'type': 'dashboard_update',
                    'timestamp': datetime.now().isoformat(),
                    'snapshot_version': result.metadata['snapshot_version'],
                    'generated_at': result.metadata['generated_at'],
                    'stale': result.stale,
                    **result.data,
                }
                yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            except ReadModelNotReadyError as exc:
                logger.warning('SSE 实时快照暂不可用: {}', exc)
                data = {
                    'type': 'snapshot_unavailable',
                    'timestamp': datetime.now().isoformat(),
                    'code': 'realtime_snapshot_unavailable',
                }
                yield f"event: snapshot_unavailable\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
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
    today = get_business_date()

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
        if target_date < get_business_date():
            if _snapshot_state(target_date) is None:
                return _snapshot_not_found_response()
            stats = local_get_kanban_stats(
                target_date, stepnos=stepnos, wrk_orders=wrk_orders,
                flows=flows, reg_per_sys_ids=reg_per_sys_ids,
                show_all_flows=show_all_flows,
            )
            return Response(stats, status=status.HTTP_200_OK)
        result = READ_MODEL.kanban_stats(
            target_date, stepnos=stepnos, wrk_orders=wrk_orders,
            flows=flows, reg_per_sys_ids=reg_per_sys_ids,
            show_all_flows=show_all_flows,
        )
        return _snapshot_response(result)
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
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
        if target_date < get_business_date():
            if _snapshot_state(target_date) is None:
                return _snapshot_not_found_response()
            result = local_get_kanban_ranking(
                target_date, stepnos=stepnos, wrk_orders=wrk_orders,
                flows=flows, reg_per_sys_ids=reg_per_sys_ids,
                page=page, page_size=page_size,
                show_all_flows=show_all_flows,
            )
            return Response(result, status=status.HTTP_200_OK)
        result = READ_MODEL.kanban_ranking(
            target_date, stepnos=stepnos, wrk_orders=wrk_orders,
            flows=flows, reg_per_sys_ids=reg_per_sys_ids,
            page=page, page_size=page_size,
            show_all_flows=show_all_flows,
        )
        return _snapshot_response(result)
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
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
        if target_date < get_business_date():
            if _snapshot_state(target_date) is None:
                return _snapshot_not_found_response()
            options = local_get_kanban_filter_options(
                target_date, stepnos=stepnos, wrk_orders=wrk_orders,
                flows=flows, reg_per_sys_ids=reg_per_sys_ids,
                show_all_flows=show_all_flows,
            )
            return Response(options, status=status.HTTP_200_OK)
        result = READ_MODEL.kanban_filter_options(
            target_date, stepnos=stepnos, wrk_orders=wrk_orders,
            flows=flows, reg_per_sys_ids=reg_per_sys_ids,
            show_all_flows=show_all_flows,
        )
        return _snapshot_response(result)
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as e:
        logger.error('GET /api/kanban/filter-options/ 失败: {}', e)
        return Response(
            {'error': '获取筛选项失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
