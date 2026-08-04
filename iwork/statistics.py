import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.cache import cache
from django.db import connections
from loguru import logger

from iwork import queries as remote_q
from iwork import local_queries as local_q

# =====
# 业务配置引用（统一在 settings.py 中定义）
MONTHLY_CACHE_TTL = settings.MONTHLY_CACHE_TTL
QUERY_TIMEOUT = settings.QUERY_TIMEOUT
PRODUCT_OVERVIEW_CACHE_NAME = settings.PRODUCT_OVERVIEW_CACHE_NAME
FLOW_DETAIL_CACHE_NAME = settings.FLOW_DETAIL_CACHE_NAME
DETAIL_CACHE_PREFIX = settings.DETAIL_CACHE_PREFIX
REALTIME_PROCESS_LIST_CACHE_PREFIX = settings.REALTIME_PROCESS_LIST_CACHE_PREFIX
BUSINESS_TIME_ZONE = ZoneInfo(settings.IWORK_BUSINESS_TIME_ZONE)
WORKDAY_START_MINUTE = settings.WORKDAY_START_MINUTE
WORKDAY_LUNCH_START_MINUTE = settings.WORKDAY_LUNCH_START_MINUTE
WORKDAY_LUNCH_END_MINUTE = settings.WORKDAY_LUNCH_END_MINUTE

# =====
# 临时开关：跳过月份全表扫描查询以加速启动（改为 False 恢复完整功能）
SKIP_MONTHLY_QUERIES = False


def _run_batch_query(query, *args, **kwargs):
    """执行单个批量查询并关闭当前工作线程创建的数据库连接。

    Args:
        query: 需要在线程池中执行的查询函数。
        *args: 传给查询函数的位置参数。
        **kwargs: 传给查询函数的关键字参数。

    Returns:
        查询函数的返回值。

    Raises:
        Exception: 原样传播查询函数抛出的异常。
    """
    try:
        return query(*args, **kwargs)
    finally:
        connections.close_all()

def _result_or_cancel(future, name: str, timeout: int = QUERY_TIMEOUT):
    """
    带超时的 future.result() 封装，超时时取消剩余任务并记录日志

    Args:
        future: concurrent.futures.Future 对象
        name: 查询名称（用于日志）
        timeout: 超时秒数

    Returns:
        future.result() 的返回值

    Raises:
        TimeoutError: 查询超时
    """
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        future.cancel()
        logger.error('数据库查询超时（{}s）: {}', timeout, name)
        raise


def _seconds_to_midnight(current_time: datetime | None = None) -> int:
    """计算距离曼谷业务日午夜的剩余秒数。

    Args:
        current_time: 可选的当前时间；主要用于稳定验证跨时区边界。

    Returns:
        距离下一个曼谷午夜的秒数，并增加五秒边界余量。
    """
    now = _as_business_time(current_time)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds()) + 5  # +5s 兜底避免边界条件


def _stepno_key(stepno):
    """工序缓存键后缀：None → 'all'，[70] → '70'，[70,69] → '70_69'"""
    if stepno is None:
        return 'all'
    if isinstance(stepno, list):
        return '_'.join(str(s) for s in sorted(stepno))
    return str(stepno)


def calculate_flow_efficiency(avg_time: float | None, baseline: float | None) -> float | None:
    """计算 Flow 组效率"""
    if avg_time is None or baseline is None:
        return None
    if baseline == 0:
        return None
    if avg_time < 0:
        return 0.0
    efficiency = 1 - (avg_time / baseline)
    return max(0.0, min(1.0, efficiency))


def _as_business_time(current_time: datetime | None = None) -> datetime:
    """将指定时间转换为曼谷业务时区时间。"""
    now = current_time or datetime.now(BUSINESS_TIME_ZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BUSINESS_TIME_ZONE)
    return now.astimezone(BUSINESS_TIME_ZONE)


def get_business_date(current_time: datetime | None = None) -> date:
    """返回 UTC+7 业务日期。"""
    return _as_business_time(current_time).date()


def get_effective_work_minutes(
    target_date: date,
    current_time: datetime | None = None,
) -> int | None:
    """返回 UTC+7 当日从 07:00 起、扣除 11:00-12:00 午休的分钟数。"""
    now = _as_business_time(current_time)
    if target_date != now.date():
        return None

    current_minutes = now.hour * 60 + now.minute
    if current_minutes < WORKDAY_START_MINUTE:
        return None
    if current_minutes < WORKDAY_LUNCH_START_MINUTE:
        return current_minutes - WORKDAY_START_MINUTE
    if current_minutes < WORKDAY_LUNCH_END_MINUTE:
        return WORKDAY_LUNCH_START_MINUTE - WORKDAY_START_MINUTE
    lunch_minutes = WORKDAY_LUNCH_END_MINUTE - WORKDAY_LUNCH_START_MINUTE
    return current_minutes - WORKDAY_START_MINUTE - lunch_minutes


def detail_cache_key(name: str, target_date: date | None = None) -> str:
    """生成按曼谷业务日期隔离的详情缓存键。

    Args:
        name: 详情缓存的逻辑名称。
        target_date: 缓存所属业务日期；默认取当前曼谷业务日。

    Returns:
        包含业务日期的详情缓存键。
    """
    business_date = target_date or get_business_date()
    return f'{DETAIL_CACHE_PREFIX}:{business_date.isoformat()}:{name}'


def realtime_process_list_cache_key(target_date: date | None = None) -> str:
    """生成按曼谷业务日期隔离的实时工序列表缓存键。

    Args:
        target_date: 缓存所属业务日期；默认取当前曼谷业务日。

    Returns:
        包含业务日期的实时工序列表缓存键。
    """
    business_date = target_date or get_business_date()
    return f'{REALTIME_PROCESS_LIST_CACHE_PREFIX}:{business_date.isoformat()}'


def calculate_employee_efficiency(
    output_value: float | None,
    work_minutes: int | None,
) -> float | None:
    """按员工总产值与有效上班分钟计算百分比效率。"""
    if output_value is None or work_minutes is None or work_minutes <= 0:
        return None
    return output_value / work_minutes * 100


# ============================================================================
# Batch 批量构建引擎（Celery 使用，一次性算出所有工序 → 写入 Redis）
# ============================================================================

def _merge_batch_top_processes(batch_basic: dict) -> list:
    """从批量 KPI 数据中提取 Top 8 工序"""
    sorted_steps = sorted(batch_basic.items(), key=lambda kv: kv[1]['total_qty'], reverse=True)
    return [{'step': stepno, 'qty': info['total_qty']} for stepno, info in sorted_steps[:8]]


def _merge_batch_station_full(batch_station: dict) -> list:
    """合并全部工序的工站排行（全工序无区分）——用于 'all' 视图"""
    merged = {}
    for stations in batch_station.values():
        for s in stations:
            merged[s['station']] = merged.get(s['station'], 0) + s['qty']
    return [{'station': k, 'qty': v} for k, v in
            sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:10]]


def _merge_batch_process_flow(batch_pf: dict) -> list:
    """合并全工序的 Flow 分组数据 → 用于 'all' 视图"""
    merged = []
    for items in batch_pf.values():
        merged.extend(items)
    return merged


def _merge_batch_monthly_total(batch_monthly_total: dict) -> list:
    """合并全工序的月总趋势，按 date 聚合求和"""
    merged = {}
    for items in batch_monthly_total.values():
        for item in items:
            d = item['date']
            merged[d] = merged.get(d, 0) + item['qty']
    return [{'date': d, 'qty': qty} for d, qty in sorted(merged.items())]


def _merge_batch_monthly_proc(batch_monthly_proc: dict) -> list:
    """合并全工序的月工序堆积，限制 Top 8 工序"""
    step_qty = {}
    for stepno, items in batch_monthly_proc.items():
        step_qty[stepno] = sum(item['qty'] for item in items)
    top_steps = {s for s, _ in sorted(step_qty.items(), key=lambda kv: kv[1], reverse=True)[:8]}
    merged = []
    for stepno, items in batch_monthly_proc.items():
        if stepno in top_steps:
            merged.extend(items)
    return merged


def _merge_batch_monthly_hourly(batch_monthly_hourly: dict) -> list:
    """合并全工序的月小时趋势：按(date, hour, stepno)保留工序维度"""
    merged = {}
    for stepno, items in batch_monthly_hourly.items():
        for item in items:
            if item['hour'] is not None:
                key = (item['date'], item['hour'], stepno)
                merged[key] = merged.get(key, 0) + item['qty']
    return [{'date': d, 'hour': h, 'step': s, 'qty': q}
            for (d, h, s), q in sorted(merged.items())]


def _build_heatmap_matrix(process_flow_stats: list) -> dict:
    """将 process_flow 数据转为热力图矩阵：ALLOWED_FLOWS(行) × 工序(列)"""
    from django.conf import settings
    step_qty = {}
    flow_step_qty = {}
    for item in process_flow_stats:
        step = item['step']
        flow = item['flow']
        qty = item['qty']
        step_qty[step] = step_qty.get(step, 0) + qty
        flow_step_qty[(flow, step)] = qty

    sorted_stepnos = sorted(step_qty.keys(), key=lambda s: step_qty[s], reverse=True)
    flows = list(settings.VISIBLE_FLOWS)
    data = [[flow_step_qty.get((flow, step), 0) for step in sorted_stepnos] for flow in flows]

    return {
        'stepnos': sorted_stepnos,
        'flows': flows,
        'data': data,
    }


def _assemble_stepno_stats(stepno, batch_basic, batch_hourly, batch_pf,
                           batch_monthly_total, batch_monthly_proc,
                           batch_monthly_hourly, batch_station, batch_wo,
                           today, month_start, all_stepnos_list=None) -> dict:
    """组装单个工序的完整 stats dict"""
    basic = batch_basic.get(stepno, {'total_qty': 0, 'workorder_count': 0})
    return {
        'workorder_count': basic['workorder_count'],
        'total_qty': basic['total_qty'],
        'date': today,
        'hourly_stats': [item for item in batch_hourly.get(stepno, []) if item['hour'] is not None],
        'process_flow_stats': batch_pf.get(stepno, []),
        'monthly_process_stats': batch_monthly_proc.get(stepno, []),
        'monthly_total_trend': batch_monthly_total.get(stepno, []),
        'monthly_hourly_stats': [{**r, 'step': stepno} for r in batch_monthly_hourly.get(stepno, [])],
        'station_stats': batch_station.get(stepno, [])[:10],
        'heatmap_matrix': _build_heatmap_matrix(batch_pf.get(stepno, [])),
        'station_ranking': batch_station.get(stepno, []),
        'top_processes': [{'step': stepno, 'qty': basic['total_qty']}],
        'workorders': batch_wo.get(stepno, []),
        'all_stepnos': all_stepnos_list or [],
    }


def get_batch_stats(q=None, target_date: date | None = None) -> dict:
    """
    一次性构建所有工序的统计数据 → {stepno: stats_dict, 'all': stats_dict}

    供 Celery 定时任务使用，计算结果写入 Redis 缓存。
    """
    if q is None:
        q = remote_q

    today = target_date or get_business_date()
    month_start = date(today.year, today.month, 1)

    # ---- 第 1 阶段：并行 batch 查询（6 个维度） ----
    logger.info('第1阶段：5线程并行查询开始')
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_basic = pool.submit(_run_batch_query, q.get_batch_basic_stats, today)
        f_hourly = pool.submit(_run_batch_query, q.get_batch_hourly_stats, today)
        f_pf = pool.submit(_run_batch_query, q.get_batch_process_by_flow, today)
        f_station = pool.submit(
            _run_batch_query,
            q.get_batch_station_ranking,
            today,
        )
        f_wo = pool.submit(_run_batch_query, q.get_batch_workorders_list, today, 20)

        batch_basic = _result_or_cancel(f_basic, 'batch_basic')
        batch_hourly = _result_or_cancel(f_hourly, 'batch_hourly')
        batch_pf = _result_or_cancel(f_pf, 'batch_process_flow')
        batch_station = _result_or_cancel(f_station, 'batch_station')
        batch_wo = _result_or_cancel(f_wo, 'batch_workorders')
    logger.info('第1阶段完成，耗时 {:.1f}s，共 {} 个工序', time.time() - t1, len(batch_basic))

    # ---- 第 2 阶段：月趋势 (独立缓存，跨天保留) ----
    if SKIP_MONTHLY_QUERIES:
        logger.info('第2阶段：月趋势查询[跳过] (SKIP_MONTHLY_QUERIES=True)')
        batch_monthly_total = {}
        batch_monthly_proc = {}
        batch_monthly_hourly = {}
    else:
        logger.info('第2阶段：月趋势查询开始')
        t2 = time.time()
        month_key = f'batch_monthly:{today.year}{today.month}:{today.isoformat()}'
        cached_monthly = cache.get(month_key) or {}
        today_str = str(today)

        # 月总趋势
        if 'total' in cached_monthly:
            # 有历史缓存 → 只查今日（<1s），替换缓存中的今日旧数据
            today_total = q.get_batch_monthly_total_trend(today, today)
            batch_monthly_total = dict(cached_monthly['total'])
            for stepno, items in today_total.items():
                old = batch_monthly_total.setdefault(stepno, [])
                old[:] = [r for r in old if r['date'] != today_str] + items
        else:
            batch_monthly_total = q.get_batch_monthly_total_trend(month_start, today)

        # 月工序堆积
        if 'proc' in cached_monthly:
            today_proc = q.get_batch_monthly_process_stats(today, today)
            batch_monthly_proc = dict(cached_monthly['proc'])
            for stepno, items in today_proc.items():
                old = batch_monthly_proc.setdefault(stepno, [])
                old[:] = [r for r in old if r['date'] != today_str] + items
        else:
            batch_monthly_proc = q.get_batch_monthly_process_stats(month_start, today)

        # 月小时趋势（单次SQL，性能优先）
        if 'hourly' in cached_monthly:
            today_hourly = q.get_batch_monthly_hourly_stats(today, today)
            batch_monthly_hourly = dict(cached_monthly['hourly'])
            for stepno, items in today_hourly.items():
                old = batch_monthly_hourly.setdefault(stepno, [])
                old[:] = [r for r in old if r['date'] != today_str] + items
        else:
            batch_monthly_hourly = q.get_batch_monthly_hourly_stats(month_start, today)

        # 同步缓存
        cache.set(month_key + ':total', batch_monthly_total, MONTHLY_CACHE_TTL)
        cache.set(month_key + ':proc', batch_monthly_proc, MONTHLY_CACHE_TTL)
        cache.set(month_key + ':hourly', batch_monthly_hourly, MONTHLY_CACHE_TTL)
        cache.set(month_key, {'total': batch_monthly_total, 'proc': batch_monthly_proc, 'hourly': batch_monthly_hourly}, MONTHLY_CACHE_TTL)
        logger.info('第2阶段完成，耗时 {:.1f}s', time.time() - t2)

    # ---- 第 3 阶段：按 stepno 组装 ----
    logger.info('第3阶段：工序数据组装开始')
    t3 = time.time()
    all_stepnos = set(batch_basic.keys())
    all_total_qty = sum(v['total_qty'] for v in batch_basic.values())
    all_station_full = _merge_batch_station_full(batch_station)
    all_hourly = []
    hourly_merged = {}
    for items in batch_hourly.values():
        for item in items:
            h = item['hour']
            if h is not None:
                hourly_merged[h] = hourly_merged.get(h, 0) + item['qty']
    all_hourly = [{'hour': h, 'qty': qty} for h, qty in sorted(hourly_merged.items())]
    all_top = _merge_batch_top_processes(batch_basic)
    all_wo = []
    wo_merged = {}
    wo_flows = {}
    wo_products = {}
    for items in batch_wo.values():
        for item in items:
            k = item['wrk_order']
            wo_merged[k] = wo_merged.get(k, 0) + item['total_qty']
            if k not in wo_flows:
                wo_flows[k] = set()
            wo_flows[k].update(item.get('flows', []))
            wo_products.setdefault(k, {
                'product_name': item.get('product_name', ''),
                'order_no': item.get('order_no', ''),
            })
    all_wo = [{'wrk_order': k, 'total_qty': v,
               'flows': sorted(wo_flows.get(k, set())),
               **wo_products.get(k, {})}
              for k, v in sorted(wo_merged.items(), key=lambda kv: kv[1], reverse=True)[:20]]

    all_stepnos_sorted = sorted(all_stepnos, reverse=True)

    batch = {}
    for stepno in sorted(all_stepnos):
        batch[stepno] = _assemble_stepno_stats(
            stepno, batch_basic, batch_hourly, batch_pf,
            batch_monthly_total, batch_monthly_proc,
            batch_monthly_hourly, batch_station, batch_wo,
            today, month_start, all_stepnos_sorted
        )

    # 'all' 合并视图
    batch['all'] = {
        'workorder_count': len(wo_merged),
        'total_qty': all_total_qty,
        'date': today,
        'hourly_stats': all_hourly,
        'process_flow_stats': _merge_batch_process_flow(batch_pf),
        'monthly_process_stats': _merge_batch_monthly_proc(batch_monthly_proc),
        'monthly_total_trend': _merge_batch_monthly_total(batch_monthly_total),
        'monthly_hourly_stats': _merge_batch_monthly_hourly(batch_monthly_hourly),
        'station_stats': all_station_full[:10],
        'heatmap_matrix': _build_heatmap_matrix(_merge_batch_process_flow(batch_pf)),
        'station_ranking': all_station_full,
        'top_processes': all_top,
        'workorders': all_wo,
        'all_stepnos': all_stepnos_sorted,
    }

    logger.info('第3阶段完成，耗时 {:.1f}s，组装 {} 个工序视图', time.time() - t3, len(batch))
    return batch


def cache_batch_to_redis(batch: dict, target_date: date | None = None) -> None:
    """将批量结果写入 Redis，并在曼谷业务日午夜失效。

    Args:
        batch: 按工序组织的实时统计批次。
        target_date: 批次所属的曼谷业务日期。
    """
    ttl = _seconds_to_midnight()
    business_date = target_date or get_business_date()

    t1 = time.time()
    for stepno, stats in batch.items():
        key = f'stats:realtime:{stepno}' if stepno != 'all' else 'stats:realtime:all'
        cache.set(key, stats, ttl)

    # 缓存工序列表
    process_list = [s for s in batch if s != 'all']
    cache.set(realtime_process_list_cache_key(business_date), process_list, ttl)
    logger.info('Redis 缓存写入完成，{} 个 key，耗时 {:.1f}s', len(batch), time.time() - t1)


def get_batch_detail_stats(q=None, target_date: date | None = None) -> dict:
    """批量构建生产详情数据 → {flow_overview, flow_hourly, flow_employees, stepno_employees, product_overview}"""
    if q is None:
        q = remote_q
    today = target_date or get_business_date()

    logger.info('生产详情：5线程并行查询开始')
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_overview = pool.submit(_run_batch_query, q.get_batch_flow_overview, today)
        f_hourly = pool.submit(_run_batch_query, q.get_batch_flow_hourly, today)
        f_employees = pool.submit(_run_batch_query, q.get_batch_flow_employees, today)
        f_stepno = pool.submit(_run_batch_query, q.get_batch_stepno_employees, today)
        f_product = pool.submit(_run_batch_query, q.get_batch_product_overview, today)

        result = {
            'flow_overview': _result_or_cancel(f_overview, 'flow_overview'),
            'flow_hourly': _result_or_cancel(f_hourly, 'flow_hourly'),
            'flow_employees': _result_or_cancel(f_employees, 'flow_employees'),
            'stepno_employees': _result_or_cancel(f_stepno, 'stepno_employees'),
            'product_overview': _result_or_cancel(f_product, 'product_overview'),
        }
    logger.info('生产详情查询完成，耗时 {:.1f}s，{} 个 Flow，{} 个产品',
                time.time() - t1, len(result['flow_overview']),
                len(result.get('product_overview', {}).get('products', [])))
    return result


def cache_detail_batch_to_redis(
    detail_batch: dict,
    target_date: date | None = None,
) -> None:
    """将批量详情结果写入按业务日期隔离的 Redis 缓存。

    Args:
        detail_batch: Flow、工序和产品详情批次。
        target_date: 批次所属的曼谷业务日期。
    """
    ttl = _seconds_to_midnight()
    business_date = target_date or get_business_date()

    t1 = time.time()
    cache.set(detail_cache_key('flow_overview', business_date), detail_batch['flow_overview'], ttl)
    cache.set(detail_cache_key('flow_hourly', business_date), detail_batch['flow_hourly'], ttl)
    cache.set(detail_cache_key('stepno_overview', business_date), detail_batch['stepno_employees'], ttl)
    cache.set(
        detail_cache_key(PRODUCT_OVERVIEW_CACHE_NAME, business_date),
        detail_batch.get('product_overview', {}),
        ttl,
    )

    flow_count = len(detail_batch['flow_employees'])
    for flow_name, employees in detail_batch['flow_employees'].items():
        cache.set(
            detail_cache_key(f'{FLOW_DETAIL_CACHE_NAME}:{flow_name}', business_date),
            employees,
            ttl,
        )
    logger.info('详情 Redis 缓存写入完成，{} 个 key，耗时 {:.1f}s', flow_count + 4, time.time() - t1)


# ============================================================================
# 公共 API
# ============================================================================

def get_realtime_stats(stepno_filter: list[int] | None = None) -> dict:
    """从版本化实时读模型读取数据，缓存缺失时禁止远程回源。"""
    from iwork.read_model.queries import ReadModelQueries

    return ReadModelQueries().realtime(
        get_business_date(),
        stepno_filter,
    ).data


def get_date_stats(target_date: date, stepno_filter: list[int] | None = None) -> dict:
    """指定日期的全量统计（查询远程库，每次实时查询不缓存）"""
    return _get_date_stats(target_date, stepno_filter, remote_q, use_cache=False)


def get_local_date_stats(target_date: date, stepno_filter: list[int] | None = None) -> dict:
    """指定日期的全量统计（查询本地库，每次实时查询不缓存）"""
    return _get_date_stats(target_date, stepno_filter, local_q, use_cache=False)


def get_today_stats(stepno_filter: list[int] | None = None) -> dict:
    """今日数据的全量统计（保留旧接口兼容性）"""
    return get_realtime_stats(stepno_filter)


def invalidate_local_cache(target_date: date) -> None:
    """同步完成后清空本地历史缓存"""
    pattern = f'stats:local:date:{target_date.isoformat()}:*'
    keys = cache.keys(pattern)
    for key in keys:
        cache.delete(key)


# ============================================================================
# 内部引擎（历史查询、回退使用）
# ============================================================================

def _get_cached_monthly(cache_key: str, fetch_fn, *args, use_cache: bool = True):
    """带缓存的月查询（use_cache=False 时每次实时查询）"""
    if use_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    result = fetch_fn(*args)
    if use_cache:
        cache.set(cache_key, result, MONTHLY_CACHE_TTL)
    return result


def _get_date_stats(target_date: date, stepno_filter: list[int] | None,
                    q, use_cache: bool = True) -> dict:
    """通用并行查询引擎（历史查询 + 回退使用）"""
    t0 = time.perf_counter()
    month_start = date(target_date.year, target_date.month, 1)

    t_batch1 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_basic = pool.submit(q.get_basic_stats, target_date, stepno_filter=stepno_filter)
        f_process = pool.submit(q.get_process_stats, target_date, limit=9999, stepno_filter=stepno_filter)
        basic_stats = _result_or_cancel(f_basic, 'basic_stats')
        all_processes = _result_or_cancel(f_process, 'process_stats')
    batch1_ms = (time.perf_counter() - t_batch1) * 1000

    # 从同一查询结果推导 top_processes 和 all_stepnos，省去 get_all_stepnos 查询
    top_processes = all_processes[:8]
    all_stepnos = sorted([p['step'] for p in all_processes if p['qty']], reverse=True)
    stepno_list = [p['step'] for p in top_processes]
    filter_suffix = f"_{'_'.join(str(s) for s in stepno_filter)}" if stepno_filter else '_all'
    monthly_trend_key = f'monthly_trend:{target_date.isoformat()}{filter_suffix}'
    monthly_process_key = f'monthly_process:{target_date.isoformat()}{filter_suffix}'

    t_batch2 = time.perf_counter()
    if SKIP_MONTHLY_QUERIES:
        # 临时跳过月份全表扫描查询，直接赋空列表
        monthly_total_trend = []
        monthly_process_stats = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_hourly = pool.submit(q.get_hourly_stats, target_date, stepno_filter=stepno_filter)
        f_process_flow = pool.submit(q.get_process_by_flow, target_date, all_stepnos) if all_stepnos else None

        if not SKIP_MONTHLY_QUERIES:
            f_monthly_total = pool.submit(
                _get_cached_monthly, monthly_trend_key,
                q.get_monthly_total_trend, month_start, target_date, stepno_filter,
                use_cache=use_cache
            )
            f_monthly_process = pool.submit(
                _get_cached_monthly, monthly_process_key,
                q.get_monthly_process_stats, month_start, target_date, stepno_list,
                use_cache=use_cache
            ) if stepno_list else None

        f_workorders = pool.submit(q.get_workorders_list, target_date, stepno_filter=stepno_filter)
        f_station = pool.submit(q.get_station_ranking, target_date, stepno_filter=stepno_filter)

        hourly_stats = _result_or_cancel(f_hourly, 'hourly_stats')
        process_flow_stats = _result_or_cancel(f_process_flow, 'process_flow') if f_process_flow else []
        heatmap_matrix = _build_heatmap_matrix(process_flow_stats)
        if not SKIP_MONTHLY_QUERIES:
            monthly_total_trend = _result_or_cancel(f_monthly_total, 'monthly_total')
            monthly_process_stats = _result_or_cancel(f_monthly_process, 'monthly_process') if f_monthly_process else []
        workorders = _result_or_cancel(f_workorders, 'workorders')
        station_full = _result_or_cancel(f_station, 'station')
    batch2_ms = (time.perf_counter() - t_batch2) * 1000

    total_ms = (time.perf_counter() - t0) * 1000
    pf_count = len(process_flow_stats)
    logger.debug(
        '[工序产量对比] _get_date_stats date={} stepno_filter={} → '
        'batch1={:.0f}ms batch2={:.0f}ms total={:.0f}ms '
        'process_flow={}行 monthly_trend={}行 monthly_proc={}行 '
        'top_processes={} all_stepnos={}',
        target_date.isoformat(), stepno_filter,
        batch1_ms, batch2_ms, total_ms,
        pf_count, len(monthly_total_trend), len(monthly_process_stats),
        len(top_processes), len(all_stepnos),
    )

    return {
        'workorder_count': basic_stats['workorder_count'],
        'total_qty': basic_stats['total_qty'],
        'date': target_date,
        'hourly_stats': hourly_stats,
        'process_flow_stats': process_flow_stats,
        'monthly_process_stats': monthly_process_stats,
        'monthly_total_trend': monthly_total_trend,
        'station_stats': station_full[:10],
        'heatmap_matrix': heatmap_matrix,
        'station_ranking': station_full,
        'top_processes': top_processes,
        'workorders': workorders,
        'all_stepnos': all_stepnos,
    }
