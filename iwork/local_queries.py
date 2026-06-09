from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Sum, Count

from iwork.local_models import LocalPytckreg3
from iwork.queries import ALLOWED_FLOWS


def apply_stepno_filter(queryset, stepno_filter: list[int] | None):
    """对本地 QuerySet 应用 StepNo 过滤（内部工具函数）"""
    if stepno_filter:
        return queryset.filter(StepNo__in=stepno_filter)
    return queryset


def get_date_range(target: date) -> tuple:
    """获取指定日期的范围（开始时间、结束时间）"""
    start = timezone.make_aware(timezone.datetime.combine(target, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(target + timedelta(days=1), timezone.datetime.min.time()))
    return start, end


def get_records_queryset(target: date) -> object:
    """获取指定日期的 QuerySet（内部使用）"""
    start, end = get_date_range(target)
    return LocalPytckreg3.objects.using('iwork_local').filter(RegDate__gte=start, RegDate__lt=end)


def get_basic_stats(target: date, stepno_filter: list[int] | None = None) -> dict:
    """获取本地基础统计：工单数、总数量"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = records.aggregate(
        workorder_count=Count('WrkOrder', distinct=True),
        total_qty=Sum('Qty'),
    )
    return {
        'workorder_count': stats['workorder_count'] or 0,
        'total_qty': stats['total_qty'] or 0,
    }


def get_hourly_stats(target: date, stepno_filter: list[int] | None = None) -> list:
    """获取本地按小时统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('hour')
        .annotate(qty=Sum('Qty'))
        .order_by('hour')
    )
    return [{'hour': s['hour'], 'qty': s['qty'] or 0} for s in stats]


def get_process_stats(target: date, limit: int = 10,
                             stepno_filter: list[int] | None = None) -> list:
    """获取本地工序统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
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


def get_flow_stats(target: date, limit: int = 10,
                          stepno_filter: list[int] | None = None) -> list:
    """获取本地 Flow 统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.exclude(Flow='')
        .values('Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'flow': s['Flow'], 'qty': s['qty'] or 0} for s in stats]


def get_station_stats(target: date, limit: int = 10,
                             stepno_filter: list[int] | None = None) -> list:
    """获取本地工位统计"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.exclude(StationID='')
        .values('StationID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'station': s['StationID'], 'qty': s['qty'] or 0} for s in stats]


def get_worker_ranking(target: date, limit: int = 10,
                              stepno_filter: list[int] | None = None) -> list:
    """获取本地员工排名"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'name': str(s['RegPerSysID']), 'qty': s['qty'] or 0} for s in stats]


def get_workorders_list(target: date, limit: int = 20,
                               stepno_filter: list[int] | None = None) -> list:
    """获取本地工单列表"""
    records = get_records_queryset(target)
    records = apply_stepno_filter(records, stepno_filter)
    stats = list(
        records.values('WrkOrder')
        .annotate(total_qty=Sum('Qty'), step_count=Count('StepNo', distinct=True))
        .order_by('-total_qty')[:limit]
    )
    return [{'wrk_order': s['WrkOrder'], 'total_qty': s['total_qty'] or 0, 'step_count': s['step_count']} for s in stats]


def get_workorder_detail(wrk_order: str, target: date) -> dict:
    """获取本地工单详情"""
    start, end = get_date_range(target)
    records = LocalPytckreg3.objects.using('iwork_local').filter(
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
# 新增本地查询函数（看板改版 v2）

def get_monthly_total_trend(start_date: date, end_date: date,
                                   stepno_filter: list[int] | None = None) -> list:
    """获取本地当月每日总产量趋势"""
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = LocalPytckreg3.objects.using('iwork_local').filter(RegDate__gte=start, RegDate__lt=end)
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
    """获取本地当月每日×工序产量"""
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = LocalPytckreg3.objects.using('iwork_local').filter(
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
    """获取本地工序×Flow 产量对比"""
    records = get_records_queryset(target_date)
    records = records.filter(StepNo__in=stepno_list).exclude(Flow='')
    stats = list(
        records.values('StepNo', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('StepNo', '-qty')
    )
    return [{'step': s['StepNo'], 'flow': s['Flow'], 'qty': s['qty'] or 0} for s in stats]


def get_heatmap_data(target_date: date,
                            stepno_filter: list[int] | None = None) -> dict:
    """获取本地热力图矩阵：时段×Flow 产量"""
    records = get_records_queryset(target_date)
    records = apply_stepno_filter(records, stepno_filter)
    records = records.exclude(Flow='')
    stats = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('hour', 'Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('hour', 'Flow')
    )
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
    """获取本地工站产量排行 —— 按 (Flow)[StationID] 组合标识分组"""
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
    """获取本地分页工单列表"""
    records = get_records_queryset(target_date)
    records = apply_stepno_filter(records, stepno_filter)
    total = records.values('WrkOrder').distinct().count()
    stats = list(
        records.values('WrkOrder')
        .annotate(
            total_qty=Sum('Qty'),
            step_count=Count('StepNo', distinct=True),
            worker_count=Count('RegPerSysID', distinct=True),
        )
        .order_by('-total_qty')
        [(page - 1) * page_size: page * page_size]
    )
    items = [{'wrk_order': s['WrkOrder'], 'total_qty': s['total_qty'] or 0, 'step_count': s['step_count'], 'worker_count': s['worker_count'] or 0} for s in stats]
    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, (total + page_size - 1) // page_size),
    }


def get_available_dates(mode: str = 'local') -> list:
    """
    获取可用的日期列表

    Args:
        mode: 'local' 或 'remote'

    Returns:
        list: 可用日期列表
    """
    if mode == 'local':
        dates = LocalPytckreg3.objects.using('iwork_local').dates(
            'RegDate', 'day', order='DESC'
        )
        return list(dates)
    else:
        from iwork.models import Pytckreg3
        dates = Pytckreg3.objects.using('iwork').dates(
            'RegDate', 'day', order='DESC'
        )
        return list(dates)


# ============================================================================
# Batch 查询函数（本地库版本，与 queries.py 函数签名一致）

def get_batch_basic_stats(target_date: date) -> dict:
    """每个工序的 KPI：{stepno: {total_qty, workorder_count}}"""
    records = get_records_queryset(target_date)
    rows = list(
        records.values('StepNo')
        .annotate(total_qty=Sum('Qty'), workorder_count=Count('WrkOrder', distinct=True))
    )
    return {r['StepNo']: {'total_qty': r['total_qty'] or 0, 'workorder_count': r['workorder_count'] or 0} for r in rows}


def get_batch_hourly_stats(target_date: date) -> dict:
    records = get_records_queryset(target_date)
    rows = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('StepNo', 'hour').annotate(qty=Sum('Qty')).order_by('StepNo', 'hour')
    )
    result = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({'hour': r['hour'], 'qty': r['qty'] or 0})
    return result


def get_batch_process_by_flow(target_date: date) -> dict:
    records = get_records_queryset(target_date).exclude(Flow='')
    rows = list(records.values('StepNo', 'Flow').annotate(qty=Sum('Qty')).order_by('StepNo', '-qty'))
    result = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({'step': r['StepNo'], 'flow': r['Flow'], 'qty': r['qty'] or 0})
    return result


def get_batch_heatmap_data(target_date: date) -> dict:
    records = get_records_queryset(target_date).exclude(Flow='')
    rows = list(records.extra(select={'hour': 'HOUR(RegTime)'}).values('StepNo', 'hour', 'Flow').annotate(qty=Sum('Qty')))
    from iwork.queries import _groupby
    result = {}
    for stepno_key, group_rows in _groupby(rows, 'StepNo'):
        hours = sorted({r['hour'] for r in group_rows if r['hour'] is not None})
        flows = sorted({r['Flow'] for r in group_rows if r['Flow'] is not None})
        matrix = {}
        for r in group_rows:
            h, f = r['hour'], r['Flow']
            if h is not None and f is not None:
                matrix[(h, f)] = r['qty'] or 0
        result[stepno_key] = {'hours': hours, 'flows': flows,
                              'data': [[matrix.get((h, f), 0) for f in flows] for h in hours]}
    return result


def get_batch_station_ranking(target_date: date, limit: int = 10) -> dict:
    records = get_records_queryset(target_date).exclude(Flow='').exclude(StationID='')
    rows = list(records.values('StepNo', 'Flow', 'StationID').annotate(qty=Sum('Qty')).order_by('StepNo', '-qty'))
    from iwork.queries import _groupby
    result = {}
    for stepno_key, group_rows in _groupby(rows, 'StepNo'):
        top = sorted(group_rows, key=lambda r: r['qty'], reverse=True)[:limit]
        result[stepno_key] = [{'station': f"({r['Flow']})[{r['StationID']}]", 'qty': r['qty'] or 0} for r in top]
    return result


def get_batch_workorders_list(target_date: date, limit: int = 20) -> dict:
    records = get_records_queryset(target_date)
    rows = list(records.values('StepNo', 'WrkOrder')
                .annotate(total_qty=Sum('Qty'), step_count=Count('StepNo', distinct=True))
                .order_by('StepNo', '-total_qty'))
    from iwork.queries import _groupby
    result = {}
    for stepno_key, group_rows in _groupby(rows, 'StepNo'):
        top = sorted(group_rows, key=lambda r: r['total_qty'], reverse=True)[:limit]
        result[stepno_key] = [
            {'wrk_order': r['WrkOrder'], 'total_qty': r['total_qty'] or 0, 'step_count': r['step_count']}
            for r in top
        ]
    return result


def get_batch_monthly_total_trend(start_date: date, end_date: date) -> dict:
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = LocalPytckreg3.objects.using('iwork_local').filter(RegDate__gte=start, RegDate__lt=end)
    rows = list(records.extra(select={'reg_date': 'DATE(RegDate)'})
                .values('StepNo', 'reg_date').annotate(qty=Sum('Qty')).order_by('StepNo', 'reg_date'))
    result = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({'date': str(r['reg_date']), 'qty': r['qty'] or 0})
    return result


def get_batch_monthly_process_stats(start_date: date, end_date: date) -> dict:
    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    records = LocalPytckreg3.objects.using('iwork_local').filter(RegDate__gte=start, RegDate__lt=end)
    rows = list(records.extra(select={'reg_date': 'DATE(RegDate)'})
                .values('StepNo', 'reg_date').annotate(qty=Sum('Qty')).order_by('StepNo', 'reg_date'))
    result = {}
    for r in rows:
        result.setdefault(r['StepNo'], []).append({'date': str(r['reg_date']), 'step': r['StepNo'], 'qty': r['qty'] or 0})
    return result


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
    records = records.exclude(Flow='').filter(Flow__in=ALLOWED_FLOWS)
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
    records = get_records_queryset(target_date).exclude(Flow='')
    records = records.filter(Flow__in=ALLOWED_FLOWS)
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
    records = get_records_queryset(target_date).exclude(Flow='')
    records = records.filter(Flow__in=ALLOWED_FLOWS)
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
    from iwork.queries import _groupby

    records = get_records_queryset(target_date).exclude(Flow='')
    records = records.filter(Flow__in=ALLOWED_FLOWS)
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
            emp_map[emp_id]['steps'].append({'stepno': r['StepNo'], 'qty': r['qty'] or 0})
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
    from iwork.queries import _groupby

    records = get_records_queryset(target_date).exclude(Flow='')
    records = records.filter(Flow__in=ALLOWED_FLOWS)
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

