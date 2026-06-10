import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import date, datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from loguru import logger

from iwork import queries as remote_q
from iwork import local_queries as local_q

# =====
# 业务配置引用（统一在 settings.py 中定义）
MONTHLY_CACHE_TTL = settings.MONTHLY_CACHE_TTL
QUERY_TIMEOUT = settings.QUERY_TIMEOUT

# =====
# 临时开关：跳过月份全表扫描查询以加速启动（改为 False 恢复完整功能）
SKIP_MONTHLY_QUERIES = False

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


def _seconds_to_midnight() -> int:
    """计算距离今晚 24:00 的剩余秒数"""
    now = datetime.now()
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
    for stepno, stations in batch_station.items():
        for s in stations:
            merged[s['station']] = merged.get(s['station'], 0) + s['qty']
    return [{'station': k, 'qty': v} for k, v in
            sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:10]]


def _merge_batch_process_flow(batch_pf: dict) -> list:
    """合并全工序的 Flow 分组数据 → 用于 'all' 视图"""
    merged = []
    for stepno, items in batch_pf.items():
        merged.extend(items)
    return merged


def _merge_batch_monthly_total(batch_monthly_total: dict) -> list:
    """合并全工序的月总趋势，按 date 聚合求和"""
    merged = {}
    for stepno, items in batch_monthly_total.items():
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
    pf_stats = batch_pf.get(stepno, [])
    if stepno == settings.ALLOWED_FLOWS_STEPNO:
        pf_stats = [r for r in pf_stats if r['flow'] in settings.ALLOWED_FLOWS]
    return {
        'workorder_count': basic['workorder_count'],
        'total_qty': basic['total_qty'],
        'date': today,
        'hourly_stats': [item for item in batch_hourly.get(stepno, []) if item['hour'] is not None],
        'process_flow_stats': pf_stats,
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


def get_batch_stats(q=None) -> dict:
    """
    一次性构建所有工序的统计数据 → {stepno: stats_dict, 'all': stats_dict}

    供 Celery 定时任务使用，计算结果写入 Redis 缓存。
    """
    if q is None:
        q = remote_q

    today = date.today()
    month_start = date(today.year, today.month, 1)

    # ---- 第 1 阶段：并行 batch 查询（6 个维度） ----
    logger.info('第1阶段：5线程并行查询开始')
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_basic = pool.submit(q.get_batch_basic_stats, today)
        f_hourly = pool.submit(q.get_batch_hourly_stats, today)
        f_pf = pool.submit(q.get_batch_process_by_flow, today)
        f_station = pool.submit(q.get_batch_station_ranking, today)
        f_wo = pool.submit(q.get_batch_workorders_list, today, 20)

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
        month_key = f'batch_monthly:{today.year}{today.month}'
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
    for stepno, items in batch_hourly.items():
        for item in items:
            h = item['hour']
            if h is not None:
                hourly_merged[h] = hourly_merged.get(h, 0) + item['qty']
    all_hourly = [{'hour': h, 'qty': qty} for h, qty in sorted(hourly_merged.items())]
    all_top = _merge_batch_top_processes(batch_basic)
    all_wo = []
    wo_merged = {}
    wo_flows = {}
    for stepno, items in batch_wo.items():
        for item in items:
            k = item['wrk_order']
            wo_merged[k] = wo_merged.get(k, 0) + item['total_qty']
            if k not in wo_flows:
                wo_flows[k] = set()
            wo_flows[k].update(item.get('flows', []))
    all_wo = [{'wrk_order': k, 'total_qty': v, 'flows': sorted(wo_flows.get(k, set()))}
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


def cache_batch_to_redis(batch: dict) -> None:
    """将批量结果写入 Redis（每个工序独立 key，TTL 到午夜）"""
    ttl = _seconds_to_midnight()
    today = date.today()
    month_key = f'batch_monthly:{today.year}{today.month}'

    t1 = time.time()
    for stepno, stats in batch.items():
        key = f'stats:realtime:{stepno}' if stepno != 'all' else 'stats:realtime:all'
        cache.set(key, stats, ttl)

    # 缓存工序列表
    process_list = [s for s in batch.keys() if s != 'all']
    cache.set('stats:realtime:_process_list', process_list, ttl)
    logger.info('Redis 缓存写入完成，{} 个 key，耗时 {:.1f}s', len(batch), time.time() - t1)


def get_batch_detail_stats(q=None) -> dict:
    """批量构建生产详情数据 → {flow_overview, flow_hourly, flow_employees, stepno_employees}"""
    if q is None:
        q = remote_q
    today = date.today()

    logger.info('生产详情：4线程并行查询开始')
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_overview = pool.submit(q.get_batch_flow_overview, today)
        f_hourly = pool.submit(q.get_batch_flow_hourly, today)
        f_employees = pool.submit(q.get_batch_flow_employees, today)
        f_stepno = pool.submit(q.get_batch_stepno_employees, today)

        result = {
            'flow_overview': _result_or_cancel(f_overview, 'flow_overview'),
            'flow_hourly': _result_or_cancel(f_hourly, 'flow_hourly'),
            'flow_employees': _result_or_cancel(f_employees, 'flow_employees'),
            'stepno_employees': _result_or_cancel(f_stepno, 'stepno_employees'),
        }
    logger.info('生产详情查询完成，耗时 {:.1f}s，{} 个 Flow', time.time() - t1, len(result['flow_overview']))
    return result


def cache_detail_batch_to_redis(detail_batch: dict) -> None:
    """将批量详情结果写入 Redis"""
    ttl = _seconds_to_midnight()

    t1 = time.time()
    cache.set('stats:detail:flow_overview', detail_batch['flow_overview'], ttl)
    cache.set('stats:detail:flow_hourly', detail_batch['flow_hourly'], ttl)
    cache.set('stats:detail:stepno_overview', detail_batch['stepno_employees'], ttl)

    flow_count = len(detail_batch['flow_employees'])
    for flow_name, employees in detail_batch['flow_employees'].items():
        cache.set(f'stats:detail:flow:{flow_name}', employees, ttl)
    logger.info('详情 Redis 缓存写入完成，{} 个 key，耗时 {:.1f}s', flow_count + 3, time.time() - t1)


# ============================================================================
# 公共 API
# ============================================================================

def get_realtime_stats(stepno_filter: list[int] | None = None) -> dict:
    """从 Redis 缓存读取实时数据（纯读，不计算）"""
    t0 = time.perf_counter()
    key = f'stats:realtime:{_stepno_key(stepno_filter)}'
    cached = cache.get(key)
    redis_ms = (time.perf_counter() - t0) * 1000
    if cached is None:
        logger.warning('Redis 缓存未命中: {} (Redis读取耗时 {:.0f}ms)，回退数据库查询', key, redis_ms)
        t_fallback = time.perf_counter()
        stats = _get_date_stats(date.today(), stepno_filter, remote_q)
        fallback_ms = (time.perf_counter() - t_fallback) * 1000
        cache.set(key, stats, _seconds_to_midnight())
        logger.debug('[工序产量对比] get_realtime_stats 回退完成 key={} fallback={:.0f}ms total={:.0f}ms',
                     key, fallback_ms, (time.perf_counter() - t0) * 1000)
        return stats
    logger.debug('[工序产量对比] get_realtime_stats Redis命中 key={} redis={:.0f}ms', key, redis_ms)
    return cached


def get_date_stats(target_date: date, stepno_filter: list[int] | None = None) -> dict:
    """指定日期的全量统计（查询远程库，每次实时查询不缓存）"""
    return _get_date_stats(target_date, stepno_filter, remote_q, use_cache=False)


def get_local_date_stats(target_date: date, stepno_filter: list[int] | None = None) -> dict:
    """指定日期的全量统计（查询本地库，每次实时查询不缓存）"""
    return _get_date_stats(target_date, stepno_filter, local_q, use_cache=False)


def get_today_stats(stepno_filter: list[int] | None = None) -> dict:
    """今日数据的全量统计（保留旧接口兼容性）"""
    return get_date_stats(date.today(), stepno_filter)


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
