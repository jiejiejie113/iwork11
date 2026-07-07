import time
from datetime import date, timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count
from loguru import logger

from iwork.local_models import ProductionOrder


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


def _enrich_production_orders(items: list) -> None:
    """为工单列表注入 production_orders 中的产品名称和生产单号（原地修改）"""
    prefixes = {item['wrk_order'][:6] for item in items if item.get('wrk_order') and len(item['wrk_order']) >= 6}
    if not prefixes:
        return

    matches = (
        ProductionOrder.objects
        .using('iwork_local')
        .filter(style_no__in=prefixes)
        .values('style_no', 'product_name', 'order_no')
        .distinct()
    )

    lookup = {}
    for m in matches:
        if m['style_no'] not in lookup:
            lookup[m['style_no']] = (m['product_name'], m['order_no'])

    for item in items:
        prefix = item.get('wrk_order', '')[:6]
        info = lookup.get(prefix, ('', ''))
        item['product_name'] = info[0]
        item['order_no'] = info[1]


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
    _enrich_production_orders(items)

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


def get_batch_product_overview(target_date: date) -> dict:
    """
    按产品名称分组的三层结构（Product → Flow → StepNo）
    通过 WrkOrder[:6] 匹配 production_orders.style_no 获取产品信息

    Args:
        target_date (date): 目标日期

    Returns:
        dict: {
            products: [{
                product_name: str, order_no: str, total_qty: int,
                worker_count: int, flow_count: int,
                flows: [{
                    flow: str, qty: int, workers: int,
                    stepnos: [{stepno: int, qty: int, workers: int}, ...]
                }, ...]
            }, ...]
        }
        按产品总产量降序排列，未匹配到的 WrkOrder 归入"未分类"
    """
    records = get_records_queryset(target_date).exclude(Flow='').filter(Flow__in=settings.ALLOWED_FLOWS)

    rows = list(
        records.values('WrkOrder', 'Flow', 'StepNo')
        .annotate(
            qty=Sum('Qty'),
            workers=Count('RegPerSysID', distinct=True),
        )
        .order_by('WrkOrder', 'Flow', 'StepNo')
    )

    target_wo = set()
    for r in rows:
        wo = r['WrkOrder'] or ''
        if len(wo) >= 6:
            target_wo.add(wo[:6])

    lookup = {}
    if target_wo:
        matches = (
            ProductionOrder.objects.using('iwork_local')
            .filter(style_no__in=target_wo)
            .values('style_no', 'product_name', 'order_no')
            .distinct()
        )
        for m in matches:
            if m['style_no'] not in lookup:
                lookup[m['style_no']] = (m['product_name'] or '', m['order_no'] or '')

    product_map: dict[str, dict] = {}
    unmatched_flows: dict[str, dict] = {}

    for r in rows:
        wo = r['WrkOrder'] or ''
        prefix = wo[:6] if len(wo) >= 6 else ''
        info = lookup.get(prefix, ('', ''))
        product_name = info[0] if info[0] else '未分类'
        order_no = info[1]

        if product_name == '未分类':
            flow_data = unmatched_flows
        elif product_name not in product_map:
            product_map[product_name] = {'order_no': order_no, 'flows': {}}
            flow_data = product_map[product_name]['flows']
        else:
            flow_data = product_map[product_name]['flows']

        flow = r['Flow']
        if flow not in flow_data:
            flow_data[flow] = {'stepnos': {}}
        stepno = r['StepNo']
        flow_data[flow]['stepnos'][stepno] = {
            'stepno': stepno,
            'qty': r['qty'] or 0,
            'workers': r['workers'] or 0,
        }

    def _build_products(p_map: dict) -> list:
        products = []
        for p_name, p_data in p_map.items():
            flow_list = []
            product_qty = 0
            product_workers = set()
            for f_name, f_data in p_data['flows'].items():
                stepno_list = sorted(f_data['stepnos'].values(), key=lambda s: s['stepno'])
                f_qty = sum(s['qty'] for s in stepno_list)
                f_workers = sum(s['workers'] for s in stepno_list)
                flow_list.append({
                    'flow': f_name,
                    'qty': f_qty,
                    'workers': f_workers,
                    'stepnos': stepno_list,
                })
                product_qty += f_qty
            flow_list.sort(key=lambda f: f['qty'], reverse=True)
            products.append({
                'product_name': p_name,
                'order_no': p_data['order_no'],
                'total_qty': product_qty,
                'worker_count': 0,
                'flow_count': len(flow_list),
                'flows': flow_list,
            })
        products.sort(key=lambda p: p['total_qty'], reverse=True)
        return products

    result = _build_products(product_map)
    if unmatched_flows:
        result.extend(_build_products({'未分类': {'order_no': '', 'flows': unmatched_flows}}))

    return {'products': result}


# ============================================================================
# 产量看板模块查询函数
# ============================================================================

def _apply_kanban_filters(queryset, stepnos=None, wrk_orders=None,
                          flows=None, reg_per_sys_ids=None):
    """产量看板通用筛选器（内部工具函数）

    所有筛选维度均支持多选（列表），传入 None 或空列表表示不过滤。

    Args:
        queryset: Pytckreg3 QuerySet
        stepnos (list[str]|None): 工序号列表
        wrk_orders (list[str]|None): 款号列表
        flows (list[str]|None): 分组列表
        reg_per_sys_ids (list[str]|None): 员工ID列表

    Returns:
        QuerySet: 应用筛选后的 QuerySet
    """
    if stepnos:
        try:
            stepnos = [int(s) for s in stepnos]
        except (ValueError, TypeError):
            pass
        queryset = queryset.filter(StepNo__in=stepnos)
    if wrk_orders:
        queryset = queryset.filter(WrkOrder__in=wrk_orders)
    if flows:
        queryset = queryset.filter(Flow__in=flows)
    if reg_per_sys_ids:
        queryset = queryset.filter(RegPerSysID__in=reg_per_sys_ids)
    return queryset


def _merge_worker_rows(rows):
    """合并同一工人在不同 WrkOrder/Flow 下的记录

    输入来自 ORM 四级分组查询：
        [(RegPerSysID, StepNo, WrkOrder, Flow, qty), ...]
    输出按工人合并后的列表。

    合并逻辑：
        - production = SUM(所有 qty)
        - stepno/wrk_order/flow = 收集所有不重复值，用"、"连接
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
                'stepnos': set(),
                'wrk_orders': set(),
                'flows': set(),
            }
        entry = worker_map[eid]
        entry['production'] += qty
        entry['stepnos'].add(str(r['StepNo']))
        if r['WrkOrder']:
            entry['wrk_orders'].add(r['WrkOrder'])
        if r['Flow']:
            entry['flows'].add(r['Flow'])

    result = []
    for eid, entry in worker_map.items():
        result.append({
            'reg_per_sys_id': entry['reg_per_sys_id'],
            'worker_name': entry['worker_name'],
            'stepno': '、'.join(sorted(entry['stepnos'])),
            'wrk_orders': sorted(entry['wrk_orders']),
            'flow': '、'.join(sorted(entry['flows'])),
            'production': entry['production'],
        })
    return result


def get_kanban_stats(target_date, stepnos=None, wrk_orders=None,
                     flows=None, reg_per_sys_ids=None, show_all_flows=False):
    """产量看板统计汇总

    按工人聚合产量后，计算工人数、总产、人均、最高产。

    Args:
        target_date (date): 查询日期
        stepnos (list[str]|None): 工序筛选（多选）
        wrk_orders (list[str]|None): 款号筛选（多选）
        flows (list[str]|None): 分组筛选（多选）
        reg_per_sys_ids (list[str]|None): 员工筛选（多选）
        show_all_flows (bool): 是否显示全部 Flow（含隐藏分组），默认 False

    Returns:
        dict: {worker_count, total_production, avg_production, max_production, max_worker_name}
    """
    from django.db.models import Sum, Count, Max

    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepnos, wrk_orders, flows, reg_per_sys_ids)
    if not show_all_flows:
        records = records.exclude(Flow__in=settings.HIDDEN_FLOWS)

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


def get_kanban_ranking(target_date, stepnos=None, wrk_orders=None,
                       flows=None, reg_per_sys_ids=None,
                       page=1, page_size=50, show_all_flows=False):
    """产量看板排行榜

    按工人聚合产量，取主要工序/款号/分组，分页返回。

    Args:
        target_date (date): 查询日期
        stepnos (list[str]|None): 工序筛选（多选）
        wrk_orders (list[str]|None): 款号筛选（多选）
        flows (list[str]|None): 分组筛选（多选）
        reg_per_sys_ids (list[str]|None): 员工筛选（多选）
        page (int): 页码（从1开始）
        page_size (int): 每页条数，默认50
        show_all_flows (bool): 是否显示全部 Flow（含隐藏分组），默认 False

    Returns:
        dict: {pagination: {page, page_size, total_pages, total_count},
               workers: [{rank, reg_per_sys_id, worker_name, stepno, wrk_order, flow, production}]}
    """
    from django.db.models import Sum

    records = get_records_queryset(target_date)
    records = _apply_kanban_filters(records, stepnos, wrk_orders, flows, reg_per_sys_ids)
    if not show_all_flows:
        records = records.exclude(Flow__in=settings.HIDDEN_FLOWS)

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


def get_kanban_filter_options(target_date, stepnos=None, wrk_orders=None,
                              flows=None, reg_per_sys_ids=None,
                              show_all_flows=False):
    """产量看板筛选项（级联筛选，类似 Excel 高级筛选）"""
    from django.db.models import Sum

    base = get_records_queryset(target_date)
    if not show_all_flows:
        base = base.exclude(Flow__in=settings.HIDDEN_FLOWS)

    # 保存用户当前选择的筛选值（用于级联，避免被查询结果覆盖）
    sel_stepnos = stepnos
    sel_wrk_orders = wrk_orders
    sel_flows = flows
    sel_reg_per_sys_ids = reg_per_sys_ids

    rec_s = _apply_kanban_filters(base, stepnos=None, wrk_orders=sel_wrk_orders,
                                   flows=sel_flows, reg_per_sys_ids=sel_reg_per_sys_ids)
    stepnos = list(rec_s.values_list('StepNo', flat=True).distinct().order_by('StepNo'))

    rec_w = _apply_kanban_filters(base, stepnos=sel_stepnos, wrk_orders=None,
                                   flows=sel_flows, reg_per_sys_ids=sel_reg_per_sys_ids)
    wrk_orders_list = list(rec_w.values_list('WrkOrder', flat=True).distinct().order_by('WrkOrder'))

    rec_f = _apply_kanban_filters(base, stepnos=sel_stepnos, wrk_orders=sel_wrk_orders,
                                   flows=None, reg_per_sys_ids=sel_reg_per_sys_ids)
    all_flows = list(
        rec_f.exclude(Flow='').values_list('Flow', flat=True).distinct().order_by('Flow')
    )

    rec_e = _apply_kanban_filters(base, stepnos=sel_stepnos, wrk_orders=sel_wrk_orders,
                                   flows=sel_flows, reg_per_sys_ids=None)
    employee_qs = (
        rec_e.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('RegPerSysID')
    )
    employees = [
        {'reg_per_sys_id': r['RegPerSysID'], 'name': str(r['RegPerSysID'])}
        for r in employee_qs
    ]

    return {
        'stepnos': stepnos,
        'wrk_orders': wrk_orders_list,
        'flows': all_flows,
        'employees': employees,
    }
