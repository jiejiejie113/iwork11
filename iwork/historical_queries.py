from datetime import date

from django.conf import settings
from django.db.models import Count, Sum

from iwork.local_models import HistoricalProductionFact, HistoricalStepSnapshot
from iwork.queries import _build_flow_employees


def _facts(target_date: date):
    return HistoricalProductionFact.objects.using('iwork_local').filter(
        production_date=target_date,
    )


def get_batch_flow_hourly(target_date: date) -> dict:
    rows = (
        _facts(target_date)
        .exclude(flow='')
        .filter(flow__in=settings.ALLOWED_FLOWS)
        .values('flow', 'event_hour')
        .annotate(qty=Sum('qty'))
        .order_by('flow', 'event_hour')
    )
    result = {}
    for row in rows:
        if row['event_hour'] < 0:
            continue
        result.setdefault(row['flow'], []).append({
            'hour': row['event_hour'],
            'qty': row['qty'] or 0,
        })
    return result


def get_batch_flow_employees(target_date: date) -> dict:
    rows = list(
        _facts(target_date)
        .exclude(flow='')
        .filter(flow__in=settings.ALLOWED_FLOWS)
        .values('flow', 'employee_id', 'step_no', 'wrk_order')
        .annotate(qty=Sum('qty'))
        .order_by('flow')
    )
    normalized_rows = [
        {
            'Flow': row['flow'],
            'RegPerSysID': row['employee_id'],
            'StepNo': row['step_no'],
            'WrkOrder': row['wrk_order'],
            'qty': row['qty'],
        }
        for row in rows
    ]
    metadata = {
        (row['wrk_order'], row['step_no']): {
            'description': row['description'],
            'step_time': row['step_time'],
        }
        for row in HistoricalStepSnapshot.objects.using('iwork_local').filter(
            snapshot_date=target_date,
        ).values('wrk_order', 'step_no', 'description', 'step_time')
    }
    return _build_flow_employees(normalized_rows, metadata)


def get_batch_flow_overview(target_date: date) -> dict:
    facts = _facts(target_date).exclude(flow='').filter(flow__in=settings.ALLOWED_FLOWS)
    rows = (
        facts.values('flow', 'step_no')
        .annotate(qty=Sum('qty'), workers=Count('employee_id', distinct=True))
        .order_by('flow', 'step_no')
    )
    result = {}
    for row in rows:
        item = result.setdefault(row['flow'], {'stepnos': {}, 'total_workers': 0})
        item['stepnos'][str(row['step_no'])] = {
            'qty': row['qty'] or 0,
            'workers': row['workers'] or 0,
        }
    for row in facts.values('flow').annotate(total_workers=Count('employee_id', distinct=True)):
        if row['flow'] in result:
            result[row['flow']]['total_workers'] = row['total_workers'] or 0
    return result


def get_all_stepnos(target_date: date) -> list[int]:
    rows = (
        _facts(target_date)
        .values('step_no')
        .annotate(qty=Sum('qty'))
        .order_by('-step_no')
    )
    return [row['step_no'] for row in rows if row['qty']]


def get_batch_stepno_employees(target_date: date) -> dict:
    rows = (
        _facts(target_date)
        .exclude(flow='')
        .filter(flow__in=settings.ALLOWED_FLOWS)
        .values('step_no', 'employee_id', 'flow')
        .annotate(qty=Sum('qty'))
        .order_by('step_no')
    )
    result = {}
    for row in rows:
        step_employees = result.setdefault(row['step_no'], {})
        employee = step_employees.setdefault(
            row['employee_id'],
            {'qty': 0, 'flows': []},
        )
        employee['qty'] += row['qty'] or 0
        employee['flows'].append(row['flow'])
    return {
        step_no: sorted(
            [
                {
                    'reg_per_sys_id': employee_id,
                    'qty': values['qty'],
                    'flows': values['flows'],
                }
                for employee_id, values in employees.items()
            ],
            key=lambda item: item['qty'],
            reverse=True,
        )
        for step_no, employees in result.items()
    }


def get_workorders_paginated(
    target_date: date,
    page: int = 1,
    page_size: int = 20,
    stepno_filter: list[int] | None = None,
) -> dict:
    facts = _facts(target_date)
    if stepno_filter:
        facts = facts.filter(step_no__in=stepno_filter)
        if settings.ALLOWED_FLOWS_STEPNO in stepno_filter:
            facts = facts.filter(flow__in=settings.ALLOWED_FLOWS)
    total = facts.values('wrk_order').distinct().count()
    rows = list(
        facts.values('wrk_order')
        .annotate(
            total_qty=Sum('qty'),
            worker_count=Count('employee_id', distinct=True),
        )
        .order_by('-total_qty')[(page - 1) * page_size:page * page_size]
    )
    wrk_orders = [row['wrk_order'] for row in rows]
    flow_lookup = {}
    for row in facts.filter(wrk_order__in=wrk_orders).values('wrk_order', 'flow').distinct():
        flow_lookup.setdefault(row['wrk_order'], set()).add(row['flow'])
    product_lookup = {}
    for row in (
        HistoricalStepSnapshot.objects.using('iwork_local')
        .filter(snapshot_date=target_date, wrk_order__in=wrk_orders)
        .values('wrk_order', 'product_name', 'order_no')
        .distinct()
    ):
        product_lookup.setdefault(
            row['wrk_order'],
            (row['product_name'] or '', row['order_no'] or ''),
        )
    items = []
    for row in rows:
        product_name, order_no = product_lookup.get(row['wrk_order'], ('', ''))
        items.append({
            'wrk_order': row['wrk_order'],
            'total_qty': row['total_qty'] or 0,
            'worker_count': row['worker_count'] or 0,
            'flows': sorted(flow_lookup.get(row['wrk_order'], set())),
            'product_name': product_name,
            'order_no': order_no,
        })
    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, (total + page_size - 1) // page_size),
    }


def get_batch_product_overview(target_date: date) -> dict:
    rows = list(
        _facts(target_date)
        .exclude(flow='')
        .filter(flow__in=settings.ALLOWED_FLOWS)
        .values('wrk_order', 'step_no', 'flow')
        .annotate(qty=Sum('qty'), workers=Count('employee_id', distinct=True))
        .order_by('wrk_order', 'step_no', 'flow')
    )
    snapshots = list(
        HistoricalStepSnapshot.objects.using('iwork_local')
        .filter(snapshot_date=target_date)
        .values(
            'wrk_order', 'step_no', 'description', 'step_time',
            'product_name', 'order_no',
        )
    )
    metadata = {
        (row['wrk_order'], row['step_no']): row
        for row in snapshots
    }
    product_info = {}
    for row in snapshots:
        product_info.setdefault(
            row['wrk_order'],
            (row['product_name'] or '未分类', row['order_no'] or ''),
        )

    product_raw = {}
    for row in rows:
        wrk_order = row['wrk_order'] or ''
        product_name, order_no = product_info.get(wrk_order, ('未分类', ''))
        product = product_raw.setdefault(
            product_name,
            {'order_no': order_no, 'wrk_orders': {}},
        )
        workorder = product['wrk_orders'].setdefault(wrk_order, {'stepnos': {}})
        step = workorder['stepnos'].setdefault(row['step_no'], {'flows': {}})
        step['flows'][row['flow']] = {
            'flow': row['flow'],
            'qty': row['qty'] or 0,
            'workers': row['workers'] or 0,
        }

    products = []
    for product_name, product_data in product_raw.items():
        workorders = []
        for wrk_order, workorder_data in product_data['wrk_orders'].items():
            steps = []
            for step_no, step_data in workorder_data['stepnos'].items():
                flows = sorted(
                    step_data['flows'].values(),
                    key=lambda item: item['qty'],
                    reverse=True,
                )
                qty = sum(item['qty'] for item in flows)
                workers = sum(item['workers'] for item in flows)
                step_metadata = metadata.get((wrk_order, step_no), {})
                step_time = step_metadata.get('step_time')
                steps.append({
                    'stepno': step_no,
                    'description': step_metadata.get('description', ''),
                    'step_time': step_time,
                    'output_value': qty * step_time if step_time is not None else None,
                    'qty': qty,
                    'workers': workers,
                    'flows': flows,
                })
            steps.sort(key=lambda item: item['stepno'])
            workorders.append({
                'wrk_order': wrk_order,
                'qty': sum(item['qty'] for item in steps),
                'stepno_count': len(steps),
                'stepnos': steps,
            })
        workorders.sort(key=lambda item: item['qty'], reverse=True)
        products.append({
            'product_name': product_name,
            'order_no': product_data['order_no'],
            'total_qty': sum(item['qty'] for item in workorders),
            'wrk_order_count': len(workorders),
            'wrk_orders': workorders,
        })
    products.sort(key=lambda item: item['total_qty'], reverse=True)
    return {'products': products}
