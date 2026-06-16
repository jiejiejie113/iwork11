import time
from datetime import date, timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count
from loguru import logger


def apply_stepno_filter(queryset, stepno_filter: list[int] | None):
    """对 QuerySet 应用 StepNo 过滤（内部工具函数）"""
    if stepno_filter:
        return queryset.filter(StepNo__in=stepno_filter)
    return queryset


def apply_flow_filter(queryset, stepno_filter: list[int] | None = None):
    """仅 settings.ALLOWED_FLOWS_STEPNO 工序应用白名单过滤（全部视图不过滤）"""
    target = settings.ALLOWED_FLOWS_STEPNO
    if stepno_filter is not None and target in stepno_filter:
        queryset = queryset.filter(Flow__in=settings.ALLOWED_FLOWS)
    return queryset


def apply_batch_flow_filter(queryset):
    """批量查询：仅 ALLOWED_FLOWS_STEPNO 工序走白名单，其他工序全量（单次SQL）"""
    from django.db.models import Q
    target = settings.ALLOWED_FLOWS_STEPNO
    return queryset.filter(
        ~Q(StepNo=target) | Q(Flow__in=settings.ALLOWED_FLOWS)
    )


def get_date_range(target: date) -> tuple:
    """获取指定日期的范围（开始时间、结束时间）"""
    start = timezone.make_aware(timezone.datetime.combine(target, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(target + timedelta(days=1), timezone.datetime.min.time()))
    return start, end


def get_records_queryset(target: date) -> object:
    """获取指定日期的 QuerySet（内部使用）"""
    from iwork.models import Pytckreg3
    start, end = get_date_range(target)
    return Pytckreg3.objects.using('iwork').filter(RegDate__gte=start, RegDate__lt=end)


def get_basic_stats(target: date, stepno_filter: list[int] | None = None) -> dict:
    """获取基础统计：工单数、总数量"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    records = apply_flow_filter(records, stepno_filter)
    stats = records.aggregate(
        workorder_count=Count('WrkOrder', distinct=True),
        total_qty=Sum('Qty'),
    )
    return {
        'workorder_count': stats['workorder_count'] or 0,
        'total_qty': stats['total_qty'] or 0,
    }


def get_hourly_stats(target: date, stepno_filter: list[int] | None = None) -> list:
    """获取按小时统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    records = apply_flow_filter(records, stepno_filter)
    stats = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('hour')
        .annotate(qty=Sum('Qty'))
        .order_by('hour')
    )
    return [{'hour': s['hour'], 'qty': s['qty'] or 0} for s in stats]


def get_process_stats(target: date, limit: int = 10, stepno_filter: list[int] | None = None) -> list:
    """获取工序统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    records = apply_flow_filter(records, stepno_filter)
    stats = list(
        records.values('StepNo')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'step': s['StepNo'], 'qty': s['qty'] or 0} for s in stats]


def get_all_stepnos(target: date, stepno_filter: list[int] | None = None) -> list[int]:
    """获取指定日期所有不重复的工序号（降序排列）"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.values('StepNo')
        .annotate(qty=Sum('Qty'))
        .order_by('-StepNo')
    )
    return [s['StepNo'] for s in stats if s['qty']]


def get_flow_stats(target: date, limit: int = 10, stepno_filter: list[int] | None = None) -> list:
    """获取 Flow 统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.exclude(Flow='')
        .values('Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'flow': s['Flow'], 'qty': s['qty'] or 0} for s in stats]


def get_flow_detail(target: date, flow_name: str) -> dict:
    """获取指定 Flow 详情"""
    start, end = get_date_range(target)
    from iwork.models import Pytckreg3
    records = Pytckreg3.objects.using('iwork').filter(
        RegDate__gte=start,
        RegDate__lt=end,
        Flow=flow_name
    )
    return {
        'flow': flow_name,
        'total_qty': records.aggregate(total=Sum('Qty'))['total'] or 0,
        'worker_count': records.values('RegPerSysID').distinct().count(),
    }


def get_station_stats(target: date, limit: int = 10, stepno_filter: list[int] | None = None) -> list:
    """获取工位统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    records = apply_flow_filter(records, stepno_filter)
    stats = list(
        records.exclude(StationID='')
        .values('StationID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'station': s['StationID'], 'qty': s['qty'] or 0} for s in stats]


def get_worker_ranking(target: date, limit: int = 10, stepno_filter: list[int] | None = None) -> list:
    """获取员工排名"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'name': str(s['RegPerSysID']), 'qty': s['qty'] or 0} for s in stats]


def _inject_flows(records, wo_list: list) -> None:
    """为工单列表注入关联的 Flow 分组列表（原地修改）"""
    wo_orders = [wo['wrk_order'] for wo in wo_list]
    if not wo_orders:
        return
    flow_map = {}
    rows = records.filter(WrkOrder__in=wo_orders).values('WrkOrder', 'Flow').distinct()
    for r in rows:
        flow_map.setdefault(r['WrkOrder'], set()).add(r['Flow'])
    for wo in wo_list:
        wo['flows'] = sorted(flow_map.get(wo['wrk_order'], set()))


def get_workorders_list(target: date, limit: int = 20, stepno_filter: list[int] | None = None) -> list:
    """获取工单列表"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    records = apply_flow_filter(records, stepno_filter)
    stats = list(
        records.values('WrkOrder')
        .annotate(total_qty=Sum('Qty'))
        .order_by('-total_qty')[:limit]
    )
    wo_list = [{'wrk_order': s['WrkOrder'], 'total_qty': s['total_qty'] or 0} for s in stats]
    _inject_flows(records, wo_list)
    return wo_list


def get_workorder_detail(wrk_order: str, target: date) -> dict:
    """获取工单详情"""
    start, end = get_date_range(target)
    from iwork.models import Pytckreg3
    records = Pytckreg3.objects.using('iwork').filter(
        WrkOrder=wrk_order,
        RegDate__gte=start,
        RegDate__lt=end
    )
    return {
        'wrk_order': wrk_order,
        'total_qty': records.aggregate(total=Sum('Qty'))['total'] or 0,
        'steps': list(
            records.values('StepNo')
            .annotate(qty=Sum('Qty'), count=Count('TicketNo'))
            .order_by('StepNo')
        ),
    }


# ============================================================================
# 新增查询函数（看板改版 v2）

def get_monthly_total_trend(start_date: date, end_date: date,
                             stepno_filter: list[int] | None = None) -> list:
    """获取当月每日总产量趋势（主题 3c）"""
    from iwork.models import Pytckreg3
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = Pytckreg3.objects.using('iwork').filter(RegDate__gte=start, RegDate__lt=end)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.extra(select={'reg_date': 'DATE(RegDate)'})
        .values('reg_date')
        .annotate(qty=Sum('Qty'))
        .order_by('reg_date')
    )
    return [{'date': str(s['reg_date']), 'qty': s['qty'] or 0} for s in stats]


def get_monthly_process_stats(start_date: date, end_date: date,
                               stepno_list: list[int],
                               limit: int = 8) -> list:
    """获取当月每日×工序产量（主题 3b）"""
    from iwork.models import Pytckreg3
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = Pytckreg3.objects.using('iwork').filter(
        RegDate__gte=start,
        RegDate__lt=end,
        StepNo__in=stepno_list
    )
    stats = list(
        records.extra(select={'reg_date': 'DATE(RegDate)'})
        .values('reg_date', 'StepNo')
        .annotate(qty=Sum('Qty'))
        .order_by('reg_date', 'StepNo')
    )
    return [{'date': str(s['reg_date']), 'step': s['StepNo'], 'qty': s['qty'] or 0} for s in stats]


def get_process_by_flow(target_date: date, stepno_list: list[int]) -> list:
    """获取工序×Flow 产量对比（主题 3a）"""
    t0 = time.perf_counter()
    records = get_records_queryset(target_date)
    records = records.filter(StepNo__in=stepno_list).exclude(Flow='')
    stats = list(
        records.values('StepNo', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', '-qty')
    )
    result = [{'step': s['StepNo'], 'flow': s['Flow'], 'qty': s['qty'] or 0} for s in stats]
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug('[工序产量对比] get_process_by_flow date={} stepnos={} → {}行 {:.0f}ms',
                 target_date.isoformat(), stepno_list, len(result), elapsed_ms)
    return result


def get_heatmap_data(target_date: date,
                     stepno_filter: list[int] | None = None) -> dict:
    """获取热力图矩阵：时段×Flow 产量（主题 5）"""
    records = get_records_queryset(target_date)
    records = apply_stepno_filter(records, stepno_filter)
    records = records.exclude(Flow='')
    stats = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('hour', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('hour', 'Flow')
    )

    # 构建矩阵
    hours = sorted({s['hour'] for s in stats if s['hour'] is not None})
    flows = sorted({s['Flow'] for s in stats if s['Flow'] is not None})
    matrix = {}
    for s in stats:
        matrix[(s['hour'], s['Flow'])] = s['qty'] or 0

    return {
        'hours': hours,
        'flows': flows,
        'data': [[matrix.get((h, f), 0) for f in flows] for h in hours],
    }


def get_station_ranking(target_date: date, limit: int = 10,
                         stepno_filter: list[int] | None = None) -> list:
    """获取工站产量排行（主题 6）—— 按 (Flow)[StationID] 组合标识分组"""
    records = get_records_queryset(target_date)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.exclude(Flow='').exclude(StationID='')
        .values('Flow', 'StationID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'station': f"({s['Flow']})[{s['StationID']}]", 'qty': s['qty'] or 0} for s in stats]


def get_workorders_paginated(target_date: date, page: int = 1, page_size: int = 20,
                              stepno_filter: list[int] | None = None) -> dict:
    """获取分页工单列表（主题 7）"""
    records = get_records_queryset(target_date)
    records = apply_stepno_filter(records, stepno_filter)
    records = apply_flow_filter(records, stepno_filter)

    total = records.values('WrkOrder').distinct().count()

    stats = list(
        records.values('WrkOrder')
        .annotate(
            total_qty=Sum('Qty'),
            worker_count=Count('RegPerSysID', distinct=True),
        )
        .order_by('-total_qty')
        [(page - 1) * page_size: page * page_size]
    )

    items = [{'wrk_order': s['WrkOrder'], 'total_qty': s['total_qty'] or 0, 'worker_count': s['worker_count'] or 0} for s in stats]
    _inject_flows(records, items)

    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, (total + page_size - 1) // page_size),
    }


def get_remote_stats(target: date) -> dict:
    """获取远程数据库指定日期的统计数据"""
    return get_basic_stats(target)


# ============================================================================
# Batch 查询函数（按 StepNo 分组，一次查询覆盖全部工序）

def get_batch_basic_stats(target_date: date) -> dict:
    """每个工序的 KPI：{stepno: {total_qty, workorder_count}}"""
    records = get_records_queryset(target_date)
    records = apply_batch_flow_filter(records)
    rows = list(
        records.values('StepNo')
        .annotate(total_qty=Sum('Qty'), workorder_count=Count('WrkOrder', distinct=True))
    )
    return {r['StepNo']: {'total_qty': r['total_qty'] or 0, 'workorder_count': r['workorder_count'] or 0} for r in rows}


def get_batch_hourly_stats(target_date: date) -> dict:
    """每个工序的每小时趋势：{stepno: [{hour, qty}]}"""
    records = get_records_queryset(target_date)
    records = apply_batch_flow_filter(records)
    rows = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('StepNo', 'hour')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', 'hour')
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({'hour': r['hour'], 'qty': r['qty'] or 0})
    return result


def get_batch_process_by_flow(target_date: date) -> dict:
    """每个工序的 Flow 对比：{stepno: [{step, flow, qty}]}"""
    t0 = time.perf_counter()
    records = get_records_queryset(target_date).exclude(Flow='')
    records = apply_batch_flow_filter(records)
    rows = list(
        records.values('StepNo', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', '-qty')
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({
            'step': r['StepNo'], 'flow': r['Flow'], 'qty': r['qty'] or 0
        })
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug('[工序产量对比] get_batch_process_by_flow date={} → {}个工序 {}行 {:.0f}ms',
                 target_date.isoformat(), len(result), len(rows), elapsed_ms)
    return result


def get_batch_heatmap_data(target_date: date) -> dict:
    """每个工序的热力图：{stepno: {hours, flows, data}}"""
    records = get_records_queryset(target_date).exclude(Flow='')
    records = apply_batch_flow_filter(records)
    rows = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('StepNo', 'hour', 'Flow')
        .annotate(qty=Sum('Qty'))
    )
    result: dict = {}
    for stepno_key, group_rows in _groupby(rows, 'StepNo'):
        hours = sorted({r['hour'] for r in group_rows if r['hour'] is not None})
        flows = sorted({r['Flow'] for r in group_rows if r['Flow'] is not None})
        matrix = {}
        for r in group_rows:
            h, f = r['hour'], r['Flow']
            if h is not None and f is not None:
                matrix[(h, f)] = r['qty'] or 0
        result[stepno_key] = {
            'hours': hours,
            'flows': flows,
            'data': [[matrix.get((h, f), 0) for f in flows] for h in hours],
        }
    return result


def get_batch_station_ranking(target_date: date, limit: int = 10) -> dict:
    """每个工序的工站排行：{stepno: [{station, qty}]} —— 按 (Flow)[StationID] 组合标识分组"""
    records = get_records_queryset(target_date).exclude(Flow='').exclude(StationID='')
    records = apply_batch_flow_filter(records)
    rows = list(
        records.values('StepNo', 'Flow', 'StationID')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', '-qty')
    )
    result: dict = {}
    for stepno_key, group_rows in _groupby(rows, 'StepNo'):
        top = sorted(group_rows, key=lambda r: r['qty'], reverse=True)[:limit]
        result[stepno_key] = [{'station': f"({r['Flow']})[{r['StationID']}]", 'qty': r['qty'] or 0} for r in top]
    return result


def get_batch_workorders_list(target_date: date, limit: int = 20) -> dict:
    """每个工序的工单列表：{stepno: [{wrk_order, total_qty, flows}]}"""
    records = get_records_queryset(target_date)
    records = apply_batch_flow_filter(records)
    rows = list(
        records.values('StepNo', 'WrkOrder')
        .annotate(total_qty=Sum('Qty'))
        .order_by('StepNo', '-total_qty')
    )
    # 收集每个工单关联的 Flow 分组
    wo_flows: dict = {}
    flow_rows = records.values('WrkOrder', 'Flow').distinct()
    for r in flow_rows:
        wo_flows.setdefault(r['WrkOrder'], set()).add(r['Flow'])

    result: dict = {}
    for stepno_key, group_rows in _groupby(rows, 'StepNo'):
        top = sorted(group_rows, key=lambda r: r['total_qty'], reverse=True)[:limit]
        result[stepno_key] = [
            {'wrk_order': r['WrkOrder'], 'total_qty': r['total_qty'] or 0,
             'flows': sorted(wo_flows.get(r['WrkOrder'], set()))}
            for r in top
        ]
    return result


def get_batch_monthly_total_trend(start_date: date, end_date: date) -> dict:
    """每个工序的月趋势：{stepno: [{date, qty}]}"""
    from iwork.models import Pytckreg3
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = Pytckreg3.objects.using('iwork').filter(RegDate__gte=start, RegDate__lt=end)
    records = apply_batch_flow_filter(records)
    rows = list(
        records.extra(select={'reg_date': 'DATE(RegDate)'})
        .values('StepNo', 'reg_date')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', 'reg_date')
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({'date': str(r['reg_date']), 'qty': r['qty'] or 0})
    return result


def get_batch_monthly_process_stats(start_date: date, end_date: date) -> dict:
    """每个工序的月工序堆积：{stepno: [{date, step, qty}]}（按日期×工序）"""
    from iwork.models import Pytckreg3
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = Pytckreg3.objects.using('iwork').filter(RegDate__gte=start, RegDate__lt=end)
    records = apply_batch_flow_filter(records)
    rows = list(
        records.extra(select={'reg_date': 'DATE(RegDate)'})
        .values('StepNo', 'reg_date')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', 'reg_date')
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({
            'date': str(r['reg_date']), 'step': r['StepNo'], 'qty': r['qty'] or 0
        })
    return result


def get_batch_monthly_hourly_stats(start_date: date, end_date: date) -> dict:
    """月内每天×每小时×工序的产量：{stepno: [{date, hour, qty}]}，单次SQL"""
    from iwork.models import Pytckreg3
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = Pytckreg3.objects.using('iwork').filter(RegDate__gte=start, RegDate__lt=end)
    records = apply_batch_flow_filter(records)
    rows = list(
        records.extra(select={'reg_date': 'DATE(RegDate)', 'hour': 'HOUR(RegTime)'})
        .values('StepNo', 'reg_date', 'hour')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', 'reg_date', 'hour')
    )
    result: dict = {}
    for r in rows:
        if r['hour'] is not None:
            result.setdefault(r['StepNo'], []).append({
                'date': str(r['reg_date']), 'hour': r['hour'], 'qty': r['qty'] or 0
            })
    return result


def _groupby(rows: list, key: str):
    """按 key 分组迭代器（假定 rows 已排序）"""
    current_key = None
    group = []
    for row in rows:
        k = row[key]
        if k != current_key:
            if group:
                yield current_key, group
            current_key = k
            group = [row]
        else:
            group.append(row)
    if group:
        yield current_key, group


# ============================================================================
# 生产详情模块 Batch 查询函数（Flow 分组 + 员工明细）


def get_all_flows(target_date: date) -> list[str]:
    """
    获取指定日期白名单内不重复的 Flow 名称（按字母排序）

    Args:
        target_date (date): 目标日期

    Returns:
        list[str]: 按字母升序排列的 Flow 名称列表
    """
    records = get_records_queryset(target_date)
    records = records.exclude(Flow='').filter(Flow__in=settings.ALLOWED_FLOWS)
    stats = list(
        records.values('Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow')
    )
    return [s['Flow'] for s in stats if s['qty']]


def get_batch_flow_overview(target_date: date) -> dict:
    """
    获取每个 Flow 下按 StepNo 分类的产量和员工数

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {flow_name: {stepnos: {stepno: {qty, workers}}}, ...}
    """
    records = get_records_queryset(target_date).exclude(Flow='').filter(Flow__in=settings.ALLOWED_FLOWS)
    rows = list(
        records.values('Flow', 'StepNo')
        .annotate(
            qty=Sum('Qty'),
            workers=Count('RegPerSysID', distinct=True),
        )
        .order_by('Flow', 'StepNo')
    )
    result: dict = {}
    for r in rows:
        flow = r['Flow']
        if flow not in result:
            result[flow] = {'stepnos': {}, 'total_workers': 0}
        result[flow]['stepnos'][str(r['StepNo'])] = {'qty': r['qty'] or 0, 'workers': r['workers'] or 0}
    # 补充各 Flow 的跨工序去重总人数
    total_workers_rows = list(
        records.values('Flow')
        .annotate(total_workers=Count('RegPerSysID', distinct=True))
    )
    for r in total_workers_rows:
        if r['Flow'] in result:
            result[r['Flow']]['total_workers'] = r['total_workers'] or 0
    return result


def get_batch_flow_hourly(target_date: date) -> dict:
    """
    获取每个 Flow 的每小时产量趋势

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {flow_name: [{hour, qty}, ...], ...}
    """
    records = get_records_queryset(target_date).exclude(Flow='').filter(Flow__in=settings.ALLOWED_FLOWS)
    rows = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('Flow', 'hour')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow', 'hour')
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r['Flow'], []).append({'hour': r['hour'], 'qty': r['qty'] or 0})
    return result


def get_batch_flow_employees(target_date: date) -> dict:
    """
    获取每个 Flow 下的员工明细，按员工总产量降序排列

    先在 ORM 层按 (Flow, RegPerSysID, StepNo, WrkOrder) 分组求和，
    再在 Python 层按员工聚合 total_qty、steps 列表和 workorders 列表。

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {flow_name: [{reg_per_sys_id, total_qty, steps: [{stepno, qty}], workorders: [str]}, ...], ...}
        组内员工按 total_qty 降序排列
    """
    records = get_records_queryset(target_date).exclude(Flow='').filter(Flow__in=settings.ALLOWED_FLOWS)
    rows = list(
        records.values('Flow', 'RegPerSysID', 'StepNo', 'WrkOrder')
        .annotate(qty=Sum('Qty'))
        .order_by('Flow')
    )
    result: dict = {}
    for flow_name, flow_rows in _groupby(rows, 'Flow'):
        emp_map: dict[int, dict] = {}
        for r in flow_rows:
            emp_id = r['RegPerSysID']
            if emp_id not in emp_map:
                emp_map[emp_id] = {'total_qty': 0, 'steps': [], 'workorders': set()}
            emp_map[emp_id]['total_qty'] += (r['qty'] or 0)
            emp_map[emp_id]['steps'].append({'stepno': r['StepNo'], 'qty': r['qty'] or 0, 'workorder': r['WrkOrder'] or ''})
            if r['WrkOrder']:
                emp_map[emp_id]['workorders'].add(r['WrkOrder'])

        employees = sorted(
            [
                {
                    'reg_per_sys_id': eid,
                    'total_qty': v['total_qty'],
                    'steps': v['steps'],
                    'workorders': sorted(v['workorders']),
                }
                for eid, v in emp_map.items()
            ],
            key=lambda x: x['total_qty'],
            reverse=True,
        )
        result[flow_name] = employees
    return result


def get_batch_stepno_employees(target_date: date) -> dict:
    """
    获取每个工序下的员工明细，按员工产量降序排列

    先在 ORM 层按 (StepNo, RegPerSysID, Flow) 分组求和，
    再在 Python 层按员工聚合产量和 Flow 列表。

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {stepno: [{reg_per_sys_id, qty, flows: [...]}, ...], ...}
        组内员工按 qty 降序排列
    """
    records = get_records_queryset(target_date).exclude(Flow='').filter(Flow__in=settings.ALLOWED_FLOWS)
    rows = list(
        records.values('StepNo', 'RegPerSysID', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo')
    )
    result: dict = {}
    for stepno, step_rows in _groupby(rows, 'StepNo'):
        emp_map: dict[int, dict] = {}
        for r in step_rows:
            emp_id = r['RegPerSysID']
            if emp_id not in emp_map:
                emp_map[emp_id] = {'qty': 0, 'flows': []}
            emp_map[emp_id]['qty'] += (r['qty'] or 0)
            emp_map[emp_id]['flows'].append(r['Flow'])

        employees = sorted(
            [
                {'reg_per_sys_id': eid, 'qty': v['qty'], 'flows': v['flows']}
                for eid, v in emp_map.items()
            ],
            key=lambda x: x['qty'],
            reverse=True,
        )
        result[stepno] = employees
    return result


# ============================================================================
# 产量看板模块查询函数
# ============================================================================

def _apply_kanban_filters(queryset, stepno=None, wrk_order=None,
                          flows=None, reg_per_sys_id=None):
    """产量看板通用筛选器（内部工具函数）

    对 QuerySet 依次应用工序、款号、分组、员工筛选。
    筛选逻辑：传入 None 或空值表示不过滤该维度。

    Args:
        queryset: Pytckreg3 QuerySet
        stepno (str|None): 工序号，None 或 '' 表示不过滤
        wrk_order (str|None): 款号，None 或 '' 表示不过滤
        flows (list[str]|None): 分组列表，None 或 [] 表示不过滤
        reg_per_sys_id (str|None): 员工ID，None 或 '' 表示不过滤

    Returns:
        QuerySet: 应用筛选后的 QuerySet
    """
    if stepno:
        queryset = queryset.filter(StepNo=stepno)
    if wrk_order:
        queryset = queryset.filter(WrkOrder=wrk_order)
    if flows:
        queryset = queryset.filter(Flow__in=flows)
    if reg_per_sys_id:
        queryset = queryset.filter(RegPerSysID=reg_per_sys_id)
    return queryset


def _merge_worker_rows(rows):
    """合并同一工人在不同 WrkOrder/Flow 下的记录

    输入来自 ORM 四级分组查询：
        [(RegPerSysID, StepNo, WrkOrder, Flow, qty), ...]
    输出按工人合并后的列表。

    合并逻辑：
        - production = SUM(所有 qty)
        - stepno/wrk_order/flow = 取 qty 最大的那条记录的值
        - worker_name = str(reg_per_sys_id)

    Args:
        rows (list[dict]): ORM values() 返回的行列表

    Returns:
        list[dict]: 合并后的工人列表
    """
    from collections import OrderedDict

    worker_map = OrderedDict()
    for r in rows:
        eid = r['RegPerSysID']
        qty = r['qty'] or 0
        if eid not in worker_map:
            worker_map[eid] = {
                'reg_per_sys_id': eid,
                'worker_name': str(eid),
                'production': 0,
                'best_qty': 0,
                'stepno': r['StepNo'],
                'wrk_order': r['WrkOrder'] or '',
                'flow': r['Flow'] or '',
            }
        entry = worker_map[eid]
        entry['production'] += qty
        # 取产量最大的那条记录的主字段
        if qty > entry['best_qty']:
            entry['best_qty'] = qty
            entry['stepno'] = r['StepNo']
            entry['wrk_order'] = r['WrkOrder'] or ''
            entry['flow'] = r['Flow'] or ''

    result = []
    for eid, entry in worker_map.items():
        result.append({
            'reg_per_sys_id': entry['reg_per_sys_id'],
            'worker_name': entry['worker_name'],
            'stepno': entry['stepno'],
            'wrk_order': entry['wrk_order'],
            'flow': entry['flow'],
            'production': entry['production'],
        })
    return result


def get_kanban_stats(target_date, stepno=None, wrk_order=None,
                     flows=None, reg_per_sys_id=None):
    """产量看板统计汇总

    按工人聚合产量后，计算工人数、总产、人均、最高产。

    Args:
        target_date (date): 查询日期
        stepno (str|None): 工序筛选
        wrk_order (str|None): 款号筛选
        flows (list[str]|None): 分组筛选（多选）
        reg_per_sys_id (str|None): 员工筛选

    Returns:
        dict: {worker_count, total_production, avg_production, max_production, max_worker_name}
    """
    from django.db.models import Sum, Count, Max

    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepno, wrk_order, flows, reg_per_sys_id)

    # 按工人聚合产量
    worker_qs = records.values('RegPerSysID').annotate(production=Sum('Qty'))

    # 二次聚合
    agg = worker_qs.aggregate(
        worker_count=Count('RegPerSysID'),
        total_production=Sum('production'),
        max_production=Max('production'),
    )

    count = agg['worker_count'] or 0
    total = agg['total_production'] or 0
    max_qty = agg['max_production'] or 0

    # 找最高产工人
    max_worker = worker_qs.order_by('-production').first()
    max_name = str(max_worker['RegPerSysID']) if max_worker else ''

    return {
        'worker_count': count,
        'total_production': total,
        'avg_production': round(total / count) if count else 0,
        'max_production': max_qty,
        'max_worker_name': max_name,
    }


def get_kanban_ranking(target_date, stepno=None, wrk_order=None,
                       flows=None, reg_per_sys_id=None,
                       page=1, page_size=50):
    """产量看板排行榜

    按工人聚合产量，取主要工序/款号/分组，分页返回。

    Args:
        target_date (date): 查询日期
        stepno (str|None): 工序筛选
        wrk_order (str|None): 款号筛选
        flows (list[str]|None): 分组筛选（多选）
        reg_per_sys_id (str|None): 员工筛选
        page (int): 页码（从1开始）
        page_size (int): 每页条数，默认50

    Returns:
        dict: {pagination: {page, page_size, total_pages, total_count},
               workers: [{rank, reg_per_sys_id, worker_name, stepno, wrk_order, flow, production}]}
    """
    from django.db.models import Sum

    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepno, wrk_order, flows, reg_per_sys_id)

    # 四级分组：按工人+工序+款号+Flow
    rows = list(
        records.values('RegPerSysID', 'StepNo', 'WrkOrder', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )

    # Python 层合并同一工人多条记录
    workers = _merge_worker_rows(rows)
    # 按产量降序
    workers.sort(key=lambda x: x['production'], reverse=True)

    total = len(workers)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_data = workers[start:start + page_size]

    # 注入全局排名
    for i, w in enumerate(page_data):
        w['rank'] = start + i + 1

    return {
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_count': total,
        },
        'workers': page_data,
    }


def get_kanban_filter_options(target_date, flows=None):
    """产量看板筛选项

    获取当天可用的工序、款号、分组、员工列表。

    Args:
        target_date (date): 查询日期
        flows (list[str]|None): 分组筛选，用于级联员工列表

    Returns:
        dict: {stepnos, wrk_orders, flows, employees}
    """
    from django.db.models import Sum

    records = get_records_queryset(target_date)

    # 工序列表（按值升序）
    stepnos = list(
        records.values_list('StepNo', flat=True)
        .distinct()
        .order_by('StepNo')
    )

    # 款号列表（按值升序）
    wrk_orders = list(
        records.values_list('WrkOrder', flat=True)
        .distinct()
        .order_by('WrkOrder')
    )

    # 分组列表（非空，按值升序）
    all_flows = list(
        records.exclude(Flow='')
        .values_list('Flow', flat=True)
        .distinct()
        .order_by('Flow')
    )

    # 员工列表（按 RegPerSysID 聚合，若传入 flows 则先筛选）
    if flows:
        records = records.filter(Flow__in=flows)
    employee_qs = (
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )
    employees = [
        {'reg_per_sys_id': r['RegPerSysID'], 'name': str(r['RegPerSysID'])}
        for r in employee_qs
    ]

    return {
        'stepnos': stepnos,
        'wrk_orders': wrk_orders,
        'flows': all_flows,
        'employees': employees,
    }
