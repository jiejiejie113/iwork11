import json
import re
import time
import asyncio
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
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
from iwork.local_models import (
    GroupTargetProduction,
    HistoricalSyncState,
    TargetProduction,
)
from iwork.read_model.errors import ReadModelNotReadyError
from iwork.read_model.queries import ReadModelQueries
from iwork.read_model.store import SnapshotReadResult
from iwork.request_params import parse_stepno_filter
from iwork.sse_events import (
    SerializedSSEEvent,
    get_snapshot_notification_broker,
    get_sse_payload_cache,
)


# ======
# 统一实时读模型
READ_MODEL = ReadModelQueries()

# ======
# SSE 保活配置
SSE_HEARTBEAT_SECONDS = settings.SSE_HEARTBEAT_SECONDS
SSE_NOTIFICATION_POLL_SECONDS = settings.SSE_NOTIFICATION_POLL_SECONDS


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


def _natural_sort_key(value: str) -> tuple:
    """生成包含数字片段的自然排序键。

    Args:
        value: 需要排序的文本。

    Returns:
        可用于稳定自然排序的元组。
    """
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r'(\d+)', str(value))
        if part
    )


def _aggregate_initial_style_overview(flow_employees: dict) -> dict:
    """从普通线员工工序快照聚合初版款号概览。

    Args:
        flow_employees: 按生产线组织的员工及工序明细。

    Returns:
        包含自然排序初版款号卡片的概览数据。
    """
    styles: dict[str, dict] = {}
    for flow, employees in flow_employees.items():
        for employee in employees:
            employee_id = employee.get('reg_per_sys_id')
            for step in employee.get('steps', []):
                style_no = str(step.get('initial_style_no') or '').strip()
                style = styles.setdefault(style_no, {
                    'initial_style_no': style_no,
                    'label': style_no or '未设置',
                    'total_qty': 0,
                    'workers': set(),
                    'workorders': set(),
                    'flows': {},
                    'stepnos': {},
                })
                qty = step.get('qty') or 0
                stepno = step.get('stepno')
                step_summary = style['stepnos'].setdefault(stepno, {'qty': 0})
                step_summary['qty'] += qty
                is_output_step = str(stepno).strip() == '70'
                if is_output_step:
                    style['total_qty'] += qty
                style['workers'].add(employee_id)
                workorder = str(step.get('workorder') or '').strip()
                if workorder:
                    style['workorders'].add(workorder)
                flow_summary = style['flows'].setdefault(flow, {
                    'qty': 0,
                    'workers': set(),
                })
                if is_output_step:
                    flow_summary['qty'] += qty
                flow_summary['workers'].add(employee_id)

    items = []
    for style in styles.values():
        flows = [
            {
                'flow': flow,
                'qty': summary['qty'],
                'worker_count': len(summary['workers']),
            }
            for flow, summary in style['flows'].items()
        ]
        flows.sort(key=lambda item: (-item['qty'], _natural_sort_key(item['flow'])))
        items.append({
            'initial_style_no': style['initial_style_no'],
            'label': style['label'],
            'total_qty': style['total_qty'],
            'worker_count': len(style['workers']),
            'workorder_count': len(style['workorders']),
            'flows': flows,
            'stepnos': style['stepnos'],
        })

    items.sort(key=lambda item: (
        item['initial_style_no'] == '',
        _natural_sort_key(item['label']),
    ))
    return {'items': items}


def _aggregate_initial_style_detail(
    flow_employees: dict,
    initial_style_no: str,
) -> dict:
    """从普通线员工工序快照构建指定初版款号详情。

    Args:
        flow_employees: 按生产线组织的员工及工序明细。
        initial_style_no: 已去除首尾空白的初版款号，空字符串表示未设置。

    Returns:
        合并跨生产线员工并保留工序生产线归属的详情数据。
    """
    employees: dict = {}
    matched_flows = set()
    for flow, flow_employee_list in flow_employees.items():
        for source_employee in flow_employee_list:
            employee_id = source_employee.get('reg_per_sys_id')
            for source_step in source_employee.get('steps', []):
                style_no = str(source_step.get('initial_style_no') or '').strip()
                if style_no != initial_style_no:
                    continue
                matched_flows.add(flow)
                employee = employees.setdefault(employee_id, {
                    'reg_per_sys_id': employee_id,
                    'total_qty': 0,
                    'cumulative_qty': 0,
                    'cumulative_complete': True,
                    'output_value': 0.0,
                    'output_complete': True,
                    'steps': [],
                    'workorders': set(),
                })
                step = dict(source_step)
                step['flow'] = flow
                step['initial_style_no'] = initial_style_no
                qty = step.get('qty') or 0
                employee['total_qty'] += qty
                if 'cumulative_qty' in step:
                    employee['cumulative_qty'] += step.get('cumulative_qty') or 0
                else:
                    employee['cumulative_complete'] = False
                if step.get('output_value') is None:
                    employee['output_complete'] = False
                else:
                    employee['output_value'] += step['output_value']
                workorder = str(step.get('workorder') or '').strip()
                if workorder:
                    employee['workorders'].add(workorder)
                employee['steps'].append(step)

    result_employees = []
    for employee in employees.values():
        employee['steps'].sort(key=lambda step: (
            _natural_sort_key(step.get('flow', '')),
            int(step.get('stepno')) if str(step.get('stepno', '')).isdigit() else 0,
            _natural_sort_key(step.get('workorder', '')),
        ))
        result_employee = {
            'reg_per_sys_id': employee['reg_per_sys_id'],
            'total_qty': employee['total_qty'],
            'output_value': (
                employee['output_value'] if employee['output_complete'] else None
            ),
            'steps': employee['steps'],
            'workorders': sorted(employee['workorders'], key=_natural_sort_key),
        }
        if employee['cumulative_complete']:
            result_employee['cumulative_qty'] = employee['cumulative_qty']
        result_employees.append(result_employee)

    result_employees.sort(key=lambda employee: (
        -employee['total_qty'],
        _natural_sort_key(str(employee['reg_per_sys_id'])),
    ))
    return {
        'initial_style_no': initial_style_no,
        'label': initial_style_no or '未设置',
        'total_qty': sum(employee['total_qty'] for employee in result_employees),
        'cumulative_qty': sum(
            employee.get('cumulative_qty', 0) for employee in result_employees
        ),
        'worker_count': len(result_employees),
        'flows': sorted(matched_flows, key=_natural_sort_key),
        'employees': result_employees,
    }


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


def _get_group_target_with_fallback(target_date, flow_name):
    """
    获取指定生产组的整组目标产量。

    Args:
        target_date (date): 目标日期。
        flow_name (str): 生产组名称。

    Returns:
        int | None: 已保存的整组目标；未设置时返回 None。
    """
    key = f'group_target:{target_date.isoformat()}:{flow_name}'
    cached = cache.get(key)
    if cached is not None:
        return int(cached)

    try:
        target = GroupTargetProduction.objects.filter(
            target_date=target_date,
            flow_name=flow_name,
        ).values_list('target_qty', flat=True).first()
        if target is not None:
            cache.set(key, int(target), timeout=_seconds_to_midnight())
            return int(target)
    except Exception as exc:
        logger.error('从数据库读取整组目标产量失败: {}', exc)
    return None


def _get_group_work_minutes_with_fallback(target_date, flow_name):
    """获取指定生产组的计划工作分钟数。

    Args:
        target_date (date): 目标日期。
        flow_name (str): 生产组名称。

    Returns:
        int | None: 已保存的计划工作分钟；旧记录未设置时返回 None。
    """
    key = f'group_work_minutes:{target_date.isoformat()}:{flow_name}'
    cached = cache.get(key)
    if cached is not None:
        return int(cached)

    try:
        planned_work_minutes = GroupTargetProduction.objects.filter(
            target_date=target_date,
            flow_name=flow_name,
        ).values_list('planned_work_minutes', flat=True).first()
        if planned_work_minutes is not None:
            cache.set(
                key,
                int(planned_work_minutes),
                timeout=_seconds_to_midnight(),
            )
            return int(planned_work_minutes)
    except Exception as exc:
        logger.error('从数据库读取计划工作时间失败: {}', exc)
    return None


def _calculate_current_group_target(
    group_target,
    planned_work_minutes,
    elapsed_work_minutes,
):
    """按当前已工作时长折算整组当前时段目标。

    Args:
        group_target (int): 整组全天目标。
        planned_work_minutes (int | None): 计划工作分钟。
        elapsed_work_minutes (int | None): 当前已工作分钟；None 表示历史或无时段。

    Returns:
        int: 四舍五入后的当前时段整组目标，且不会超过全天目标。
    """
    if planned_work_minutes is None or elapsed_work_minutes is None:
        return group_target
    elapsed_minutes = max(elapsed_work_minutes, 0)
    rounded_minutes = ((elapsed_minutes + 59) // 60) * 60
    bounded_minutes = min(rounded_minutes, planned_work_minutes)
    current_target = (
        Decimal(group_target)
        * Decimal(bounded_minutes)
        / Decimal(planned_work_minutes)
    ).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return int(current_target)


def _allocate_step_target(step_workers, target):
    """把同一道工序的目标按员工稳定分配。

    Args:
        step_workers (dict[str, set[str]]): 工序与去重员工集合。
        target (int): 每道工序需要分配的目标。

    Returns:
        dict[str, dict[str, int]]: 工序下每名员工的目标。
    """
    allocations = {}
    for stepno in sorted(step_workers, key=lambda value: int(value)):
        employee_ids = sorted(step_workers[stepno], key=lambda value: int(value))
        base_target, remainder = divmod(target, len(employee_ids))
        allocations[stepno] = {
            employee_id: base_target + (index < remainder)
            for index, employee_id in enumerate(employee_ids)
        }
    return allocations


def _distribute_group_target(
    employees,
    group_target,
    planned_work_minutes=None,
    elapsed_work_minutes=None,
):
    """
    将整组目标分配到每道工序及工序内员工。

    每道工序都获得完整的整组目标。工序目标按员工 ID 稳定排序后进行整数分配，
    不能整除的余数依次补给排序靠前的员工，确保个人目标之和等于工序目标。

    Args:
        employees (list[dict]): 当前生产组的员工与工序明细。
        group_target (int): 整组全天目标产量。
        planned_work_minutes (int | None): 计划工作分钟。
        elapsed_work_minutes (int | None): 当前已工作分钟。

    Returns:
        tuple[dict, int]: 各工序目标汇总和整组当前时段目标。
    """
    step_workers = {}
    for employee in employees:
        employee_id = str(employee['reg_per_sys_id'])
        for step in employee.get('steps', []):
            stepno = str(step.get('stepno'))
            step_workers.setdefault(stepno, set()).add(employee_id)

    current_group_target = _calculate_current_group_target(
        group_target,
        planned_work_minutes,
        elapsed_work_minutes,
    )
    full_allocations = _allocate_step_target(step_workers, group_target)
    current_allocations = _allocate_step_target(step_workers, current_group_target)
    step_targets = {}
    for stepno in sorted(step_workers, key=lambda value: int(value)):
        step_targets[stepno] = {
            'target': group_target,
            'current_target': current_group_target,
            'worker_count': len(step_workers[stepno]),
        }

    for employee in employees:
        employee_id = str(employee['reg_per_sys_id'])
        step_actuals = {}
        for step in employee.get('steps', []):
            stepno = str(step.get('stepno'))
            step_actuals[stepno] = step_actuals.get(stepno, 0) + (step.get('qty') or 0)

        employee_step_targets = {}
        for stepno, actual_qty in step_actuals.items():
            full_target = full_allocations[stepno][employee_id]
            target = current_allocations[stepno][employee_id]
            employee_step_targets[stepno] = {
                'full_target': full_target,
                'target': target,
                'actual_qty': actual_qty,
                'target_rate': actual_qty / target * 100 if target > 0 else None,
            }
        for step in employee.get('steps', []):
            step_target = employee_step_targets[str(step.get('stepno'))]
            step['target'] = step_target['target']
            step['target_rate'] = step_target['target_rate']

        employee['step_targets'] = employee_step_targets
        employee['full_target'] = sum(
            item['full_target'] for item in employee_step_targets.values()
        )
        employee['target'] = sum(item['target'] for item in employee_step_targets.values())
        employee['target_rate'] = (
            employee['total_qty'] / employee['target'] * 100
            if employee['target'] > 0
            else None
        )

    return step_targets, current_group_target


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


def _prepare_flow_employees_for_detail(
    source_employees,
    target_date,
    flow_name,
    work_minutes,
):
    """复制分组员工并注入与分组详情一致的目标和效率。

    Args:
        source_employees (list[dict]): 完整分组员工及工序快照。
        target_date (date): 目标业务日期。
        flow_name (str): 生产分组名称。
        work_minutes (int | None): 当前有效工作分钟。

    Returns:
        tuple[list[dict], dict]: 员工副本及该分组的只读目标摘要。
    """
    employees = []
    for source_employee in source_employees:
        employee = dict(source_employee)
        employee['steps'] = [
            dict(step) for step in source_employee.get('steps', [])
        ]
        employee['employee_efficiency'] = calculate_employee_efficiency(
            employee.get('output_value'),
            work_minutes,
        )
        employees.append(employee)

    group_target = _get_group_target_with_fallback(target_date, flow_name)
    planned_work_minutes = _get_group_work_minutes_with_fallback(
        target_date,
        flow_name,
    )
    step_targets = {}
    current_group_target = None
    if group_target is not None:
        elapsed_work_minutes = work_minutes
        if target_date == get_business_date() and elapsed_work_minutes is None:
            elapsed_work_minutes = 0
        step_targets, current_group_target = _distribute_group_target(
            employees,
            group_target,
            planned_work_minutes=planned_work_minutes,
            elapsed_work_minutes=elapsed_work_minutes,
        )
        for employee in employees:
            employee['wo_targets'] = {}
    else:
        targets_dict = _get_targets_with_fallback(target_date)
        wo_targets_dict = _get_wo_targets_with_fallback(target_date)
        for employee in employees:
            employee_id = str(employee['reg_per_sys_id'])
            employee['target'] = int(targets_dict.get(employee_id, 0))
            employee['target_rate'] = (
                employee['total_qty'] / employee['target'] * 100
                if employee['target'] > 0
                else None
            )
            employee['step_targets'] = {}
            employee['wo_targets'] = {
                key.split('@')[1]: value
                for key, value in wo_targets_dict.items()
                if key.startswith(employee_id + '@')
            }

    target_summary = {
        'flow': flow_name,
        'group_target': group_target,
        'current_group_target': current_group_target,
        'work_hours': (
            planned_work_minutes / 60
            if planned_work_minutes is not None
            else None
        ),
        'step_targets': step_targets,
    }
    return employees, target_summary


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

    work_minutes = get_effective_work_minutes(target_date)
    employees, target_summary = _prepare_flow_employees_for_detail(
        employees_data.get(flow_name, []),
        target_date,
        flow_name,
        work_minutes,
    )
    total_qty = sum(e['total_qty'] for e in employees)
    cumulative_qty = sum(int(e.get('cumulative_qty') or 0) for e in employees)

    result = {
        'flow': flow_name,
        'date': target_date.isoformat(),
        'total_qty': total_qty,
        'cumulative_qty': cumulative_qty,
        'worker_count': len(employees),
        'work_minutes': work_minutes,
        'hourly_trend': hourly_data.get(flow_name, []),
        'employees': employees,
        'group_target': target_summary['group_target'],
        'current_group_target': target_summary['current_group_target'],
        'work_hours': target_summary['work_hours'],
        'step_targets': target_summary['step_targets'],
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
def initial_style_overview(request):
    """获取普通线范围内按初版款号聚合的生产概览。

    Args:
        request: 支持 ``date`` 日期参数的 DRF 请求。

    Returns:
        Response: 初版款号、产量、人数、本厂款号数和生产线汇总。
    """
    try:
        date_str = request.query_params.get('date', get_business_date().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)
        if mode == 'local' and _snapshot_state(target_date) is None:
            return _snapshot_not_found_response()

        if mode == 'local':
            result = _aggregate_initial_style_overview(
                local_get_batch_flow_employees(target_date)
            )
            state = _snapshot_state(target_date)
            result.update({
                'source': 'local_snapshot',
                'snapshot_date': target_date.isoformat(),
                'snapshot_version': state.snapshot_version if state else None,
            })
            return Response(result, status=status.HTTP_200_OK)

        snapshot_result = READ_MODEL.details(target_date)
        result = _aggregate_initial_style_overview(
            snapshot_result.data.get('flow_employees', {})
        )
        result['source'] = 'redis_snapshot'
        return _snapshot_response(SnapshotReadResult(
            data=result,
            metadata=snapshot_result.metadata,
            stale=snapshot_result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as exc:
        logger.exception('获取初版款号概览失败: {}', exc)
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def initial_style_detail(request):
    """获取普通线范围内指定初版款号的跨生产线员工明细。

    Args:
        request: 必须显式提供 ``initial_style_no``，空值表示未设置款号。

    Returns:
        Response: 指定初版款号的员工、工序和生产线详情。
    """
    if 'initial_style_no' not in request.query_params:
        return Response(
            {'error': '缺少 initial_style_no 参数'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        initial_style_no = str(
            request.query_params.get('initial_style_no') or ''
        ).strip()
        date_str = request.query_params.get('date', get_business_date().isoformat())
        target_date = date.fromisoformat(date_str)
        mode = _detail_mode(request, target_date)
        if mode == 'local' and _snapshot_state(target_date) is None:
            return _snapshot_not_found_response()

        if mode == 'local':
            flow_employees = local_get_batch_flow_employees(target_date)
            snapshot_result = None
        else:
            snapshot_result = READ_MODEL.details(target_date)
            flow_employees = snapshot_result.data.get('flow_employees', {})

        work_minutes = get_effective_work_minutes(target_date)
        targeted_flow_employees = {}
        flow_target_summaries = {}
        for flow_name, source_employees in flow_employees.items():
            contains_initial_style = any(
                str(step.get('initial_style_no') or '').strip() == initial_style_no
                for employee in source_employees
                for step in employee.get('steps', [])
            )
            if not contains_initial_style:
                continue
            employees, target_summary = _prepare_flow_employees_for_detail(
                source_employees,
                target_date,
                flow_name,
                work_minutes,
            )
            targeted_flow_employees[flow_name] = employees
            flow_target_summaries[flow_name] = target_summary

        result = _aggregate_initial_style_detail(
            targeted_flow_employees,
            initial_style_no,
        )
        for employee in result['employees']:
            employee['employee_efficiency'] = calculate_employee_efficiency(
                employee.get('output_value'),
                work_minutes,
            )

        result['work_minutes'] = work_minutes
        result['flow_targets'] = [
            {
                'flow': flow_name,
                'group_target': flow_target_summaries[flow_name]['group_target'],
                'current_group_target': flow_target_summaries[flow_name][
                    'current_group_target'
                ],
                'work_hours': flow_target_summaries[flow_name]['work_hours'],
            }
            for flow_name in result['flows']
        ]
        result['date'] = target_date.isoformat()
        result['source'] = 'local_snapshot' if mode == 'local' else 'redis_snapshot'
        if mode == 'local':
            state = _snapshot_state(target_date)
            result.update({
                'snapshot_date': target_date.isoformat(),
                'snapshot_version': state.snapshot_version if state else None,
            })
            return Response(result, status=status.HTTP_200_OK)
        return _snapshot_response(SnapshotReadResult(
            data=result,
            metadata=snapshot_result.metadata,
            stale=snapshot_result.stale,
        ))
    except ReadModelNotReadyError as exc:
        return _read_model_unavailable_response(exc)
    except Exception as exc:
        logger.exception('获取初版款号详情失败: {}', exc)
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
    SSE 实时推送流（快照发布即时广播，周期核对仅用于丢消息补偿）

    异步实现：每个连接使用容量为 1 的最新事件队列；同一 Worker 内相同
    日期/工序的客户端共享一次 Redis 读取和 JSON 序列化。不同负载的构建
    进入有界并发队列，避免突发连接放大线程池和内存压力。

    ``mode=notification`` 时只发送快照版本元数据，供生产详情在统一发布
    水位到达后刷新当前视图，避免向详情客户端发送实时看板大负载。

    Args:
        request: Django 请求；可通过 ``stepno`` 过滤工序，或通过
            ``mode=notification`` 订阅轻量快照通知。

    Returns:
        StreamingHttpResponse: ``text/event-stream`` 长连接响应。
    """
    notification_only = request.GET.get('mode') == 'notification'
    stepno_filter = None if notification_only else _parse_stepno(request)
    state = {'business_date': get_business_date()}
    broker = get_snapshot_notification_broker()
    payload_cache = get_sse_payload_cache()

    def _cache_key() -> tuple:
        """返回当前连接对应的共享负载键。

        Returns:
            tuple: 业务日期和工序过滤组成的不可变键。
        """
        if notification_only:
            return (state['business_date'].isoformat(), 'notification')
        return (state['business_date'].isoformat(), tuple(stepno_filter or ()))

    async def _get_event() -> SerializedSSEEvent:
        """读取当前完整快照并完成一次共享序列化。

        Returns:
            SerializedSSEEvent: 可被本 Worker 多个连接复用的事件。
        """
        if notification_only:
            result = await sync_to_async(
                READ_MODEL.snapshot_metadata,
                thread_sensitive=False,
            )(state['business_date'])
            data = {
                'type': 'snapshot_published',
                'business_date': state['business_date'].isoformat(),
                'snapshot_version': result.metadata['snapshot_version'],
                'generated_at': result.metadata['generated_at'],
                'stale': result.stale,
            }
        else:
            result = await sync_to_async(
                READ_MODEL.stream_payload,
                thread_sensitive=False,
            )(state['business_date'], stepno_filter)
            data = {
                'type': 'dashboard_update',
                'timestamp': datetime.now().isoformat(),
                'snapshot_version': result.metadata['snapshot_version'],
                'generated_at': result.metadata['generated_at'],
                'stale': result.stale,
                **result.data,
            }
        return SerializedSSEEvent(
            snapshot_version=result.metadata['snapshot_version'],
            generated_at=result.metadata['generated_at'],
            content=f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n",
        )

    async def event_stream():
        """按最新通知或周期核对结果生成 SSE 数据与心跳。

        Yields:
            str: SSE 数据事件、不可用事件或心跳注释。
        """
        last_version = None
        has_attempted_payload = False
        async with broker.subscribe() as notification_queue:
            while True:
                notification = None
                if has_attempted_payload:
                    try:
                        notification = await asyncio.wait_for(
                            notification_queue.get(),
                            timeout=SSE_HEARTBEAT_SECONDS,
                        )
                    except TimeoutError:
                        yield ": heartbeat\n\n"

                current_business_date = get_business_date()
                if current_business_date != state['business_date']:
                    state['business_date'] = current_business_date
                    last_version = None

                notification_version = None
                if isinstance(notification, dict):
                    if notification.get('business_date') not in {
                        None,
                        state['business_date'].isoformat(),
                    }:
                        continue
                    notification_version = notification.get('snapshot_version')

                try:
                    event = await payload_cache.get(
                        _cache_key(),
                        _get_event,
                        notification_version=notification_version,
                        max_age_seconds=SSE_NOTIFICATION_POLL_SECONDS,
                    )
                    if event.snapshot_version != last_version:
                        last_version = event.snapshot_version
                        yield event.content
                except ReadModelNotReadyError as exc:
                    logger.warning('SSE 实时快照暂不可用: {}', exc)
                    data = {
                        'type': 'snapshot_unavailable',
                        'timestamp': datetime.now().isoformat(),
                        'code': 'realtime_snapshot_unavailable',
                    }
                    yield (
                        "event: snapshot_unavailable\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )
                except Exception as e:
                    logger.error('SSE 数据获取失败: {}', e)
                finally:
                    has_attempted_payload = True

    return StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@api_view(['POST'])
def set_targets(request):
    """
    设置目标产量（HTTP POST）

    请求体（整组格式为当前页面标准，旧格式仅用于向后兼容）：
        flow (str): 生产组名称。
        group_target (int): 整组目标；每道工序获得相同目标并按人数分配。
        work_hours (number): 计划工作小时数，用于折算当前时段目标。
        targets (dict): {reg_per_sys_id: target_qty}（旧格式，仍支持）
        wo_targets (dict): {"1001@WO-001": 150, "1001@WO-002": 150}（旧格式）

    Returns:
        Response: 保存结果；参数无效时返回 400。
    """
    group_target = request.data.get('group_target')
    if group_target is not None:
        flow_name = str(request.data.get('flow', '')).strip()
        if not flow_name:
            return Response(
                {'error': '保存整组目标时必须提供生产组'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if flow_name not in settings.VISIBLE_FLOWS:
            return Response(
                {'error': '生产组不在允许范围内'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            group_target_decimal = Decimal(str(group_target).strip())
        except (InvalidOperation, ValueError):
            return Response(
                {'error': '整组目标必须是整数'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            not group_target_decimal.is_finite()
            or group_target_decimal != group_target_decimal.to_integral_value()
        ):
            return Response(
                {'error': '整组目标必须是整数'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        group_target_int = int(group_target_decimal)
        if group_target_int < 0:
            return Response(
                {'error': '整组目标不能小于 0'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_hours = request.data.get('work_hours')
        planned_work_minutes = None
        if work_hours is not None:
            try:
                work_hours_decimal = Decimal(str(work_hours).strip())
            except (InvalidOperation, ValueError):
                work_hours_decimal = Decimal(0)
            if (
                not work_hours_decimal.is_finite()
                or work_hours_decimal <= 0
                or work_hours_decimal > 24
            ):
                return Response(
                    {'error': '工作时间必须大于 0 且不超过 24 小时'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            planned_work_minutes = int(
                (work_hours_decimal * 60).quantize(
                    Decimal('1'),
                    rounding=ROUND_HALF_UP,
                )
            )
            if planned_work_minutes < 1:
                return Response(
                    {'error': '工作时间必须大于 0 且不超过 24 小时'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        today = get_business_date()
        defaults = {'target_qty': group_target_int}
        if planned_work_minutes is not None:
            defaults['planned_work_minutes'] = planned_work_minutes
        GroupTargetProduction.objects.update_or_create(
            target_date=today,
            flow_name=flow_name,
            defaults=defaults,
        )
        cache_key = f'group_target:{today.isoformat()}:{flow_name}'
        cache.set(
            cache_key,
            group_target_int,
            timeout=_seconds_to_midnight(),
        )
        if planned_work_minutes is not None:
            cache.set(
                f'group_work_minutes:{today.isoformat()}:{flow_name}',
                planned_work_minutes,
                timeout=_seconds_to_midnight(),
            )
        logger.info(
            '整组目标已保存: {} = {}, 工作时间={}小时',
            flow_name,
            group_target_int,
            planned_work_minutes / 60 if planned_work_minutes is not None else '沿用',
        )
        return Response({
            'status': 'ok',
            'flow': flow_name,
            'group_target': group_target_int,
            'work_hours': (
                planned_work_minutes / 60
                if planned_work_minutes is not None
                else None
            ),
        })

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
