"""
工序产量对比模块 — 数据查询连通性与耗时诊断工具

============================================================
实际调用链（经过代码追踪确认）：
============================================================

[正常路径] 实时数据 (Redis 命中):
  前端 loadRealtimeData()
    → GET /api/dashboard/realtime/?stepno=70
    → api_views.realtime_stats()
      → get_realtime_stats(stepno_filter)  ← statistics.py
        → Redis GET stats:realtime:70 → 直接返回

  Redis 缓存由 Celery 每 60s 填充:
    Celery sync_dashboard_stats  ← tasks.py
      → get_batch_stats()        ← statistics.py
        → 6线程并行查询，含:
          → get_batch_process_by_flow(today)  ← queries.py [全工序]

[异常路径] 实时数据 (Redis 未命中，回退查库):
  前端 loadRealtimeData()
    → GET /api/dashboard/realtime/?stepno=70
    → api_views.realtime_stats()
      → get_realtime_stats(stepno_filter)  ← statistics.py
        → Redis 未命中
        → _get_date_stats(today, stepno_filter, remote_q)
          → 第1批并行(2线程): get_basic_stats + get_process_stats
          → 第2批并行(6线程): 含 get_process_by_flow(today, top8) ← 本模块核心查询

[历史路径] history_dashboard:
  前端 loadHistoryData()
    → GET /api/history/date/<date>/?mode=local
    → api_views_local.local_date_stats()
      → get_local_date_stats() → _get_date_stats(target, stepno_filter, local_q)
        → local_queries.get_process_by_flow(target, stepno_list)

============================================================
结论: 工序产量对比模块实际依赖两个核心查询函数:
  1. get_batch_process_by_flow(date)      — Celery批量路径
  2. get_process_by_flow(date, stepnos)   — HTTP回退/历史路径
============================================================

独立运行方式:
    cd D:\DM\Python代码\Seamus\iwork
    python tests\diagnose_process_compare.py
"""
import os
import sys
import time
import socket
from datetime import date, timedelta

# ======
# Django 环境初始化
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.settings')

import django
django.setup()

from django.db import connections
from django.db.models import Sum

# ======
# 配置参数
REPEAT_COUNT = 3                                  # 每个查询重复次数
TEST_STEPNO_SINGLE = [70]                         # 单工序测试（前端默认 stepno=70）
TOP_N = 8                                         # Top N 工序数

# ======
# 分隔线
SEP = "=" * 62
SEP2 = "-" * 62

# ======
# 结果收集
all_timings: list[dict] = []
warnings: list[str] = []
slow_threshold_ms: float = 0


def print_header(title: str):
    """打印章节标题"""
    print(f"\n{SEP}")
    print(f"  {title}")
    print(f"{SEP}")


def timed(func, *args, **kwargs) -> tuple:
    """计时执行函数，返回 (result, elapsed_ms)"""
    t0 = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = (time.perf_counter() - t0) * 1000
    return result, elapsed


def record_timing(name: str, scenario: str, elapsed_ms: float, row_count: int = 0):
    """记录一条耗时数据"""
    all_timings.append({
        'name': name,
        'scenario': scenario,
        'elapsed_ms': elapsed_ms,
        'row_count': row_count,
    })


def format_ms(ms: float) -> str:
    """格式化毫秒数"""
    if ms < 1000:
        return f"{ms:7.1f}ms"
    elif ms < 60000:
        return f"{ms/1000:7.2f} s"
    else:
        return f"{ms/60000:7.2f}min"


def status_marker(ms: float) -> str:
    """根据耗时返回状态标记"""
    if ms < 1000:
        return "✓ 正常"
    elif ms < 3000:
        return "⚠ 偏慢"
    else:
        return "✗ 慢!"


def _show_sql_for_queryset(qs, label: str = ""):
    """打印 QuerySet 生成的 SQL（不执行查询）"""
    try:
        sql = str(qs.query)
        prefix = f"    SQL({label}): " if label else "    SQL: "
        print(f"{prefix}{sql[:400]}{'...' if len(sql) > 400 else ''}")
    except Exception:
        pass


# ============================================================================
# 第一部分：连通性诊断
# ============================================================================


def test_tcp_connectivity(host: str, port: int = 3306) -> dict:
    """测试到远程数据库的 TCP 连接延迟"""
    results = []
    for _ in range(3):
        t0 = time.perf_counter()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.close()
            elapsed = (time.perf_counter() - t0) * 1000
            results.append(elapsed)
        except Exception as e:
            return {
                'success': False,
                'elapsed_ms': (time.perf_counter() - t0) * 1000,
                'error': str(e),
            }
    return {
        'success': True,
        'elapsed_ms': sum(results) / len(results),
        'error': None,
    }


def test_django_orm_connectivity(db_alias: str = 'iwork') -> dict:
    """测试 Django ORM 层的数据库连通性"""
    t0 = time.perf_counter()
    try:
        with connections[db_alias].cursor() as cursor:
            cursor.execute("SELECT 1 AS ping")
            cursor.fetchone()
        elapsed = (time.perf_counter() - t0) * 1000
        return {'success': True, 'elapsed_ms': elapsed, 'error': None}
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return {'success': False, 'elapsed_ms': elapsed, 'error': str(e)}


def show_mysql_status(db_alias: str = 'iwork'):
    """显示 MySQL 服务器关键状态"""
    try:
        with connections[db_alias].cursor() as cursor:
            cursor.execute("SHOW GLOBAL STATUS LIKE 'Slow_queries'")
            row = cursor.fetchone()
            slow_count = int(row[1]) if row else 0

            cursor.execute("SHOW GLOBAL STATUS LIKE 'Threads_connected'")
            row = cursor.fetchone()
            threads_connected = int(row[1]) if row else 0

            cursor.execute("SHOW GLOBAL STATUS LIKE 'Uptime'")
            row = cursor.fetchone()
            uptime_days = int(row[1]) // 86400 if row else 0

            cursor.execute("""
                SELECT
                    ROUND(SUM(data_length + index_length) / 1024 / 1024 / 1024, 2) AS size_gb,
                    MAX(table_rows) AS estimated_rows
                FROM information_schema.tables
                WHERE table_schema = 'payroll' AND table_name = 'pytckreg3'
            """)
            table_info = cursor.fetchone()
            table_size_gb = table_info[0] if table_info else 0
            estimated_rows = table_info[1] if table_info else 0

        print(f"  MySQL 服务器状态:")
        print(f"    慢查询累计数:    {slow_count}")
        print(f"    当前连接数:      {threads_connected}")
        print(f"    已运行时间:      {uptime_days} 天")
        print(f"    pytckreg3 大小:  {table_size_gb} GB (约 {estimated_rows:,} 行)")

        if slow_count > 100:
            warnings.append(f"慢查询累计数较高 ({slow_count})")
    except Exception as e:
        print(f"  ⚠ 无法获取 MySQL 状态: {e}")


# ============================================================================
# 第二部分：实际使用的核心查询耗时测试
# ============================================================================


def test_query_function(func, func_name: str, scenario: str, *args, **kwargs):
    """
    对单个查询函数进行多次计时测试

    Args:
        func: 目标查询函数
        func_name: 函数名
        scenario: 场景描述（对应哪个生产路径）
    """
    print(f"\n  [{func_name}]")
    print(f"    场景: {scenario}")
    best_ms = float('inf')
    best_result = None
    worst_ms = 0
    total_ms = 0

    for i in range(REPEAT_COUNT):
        result, elapsed = timed(func, *args, **kwargs)
        total_ms += elapsed
        if elapsed < best_ms:
            best_ms = elapsed
            best_result = result
        if elapsed > worst_ms:
            worst_ms = elapsed

        cold = " (冷查询)" if i == 0 else ""
        print(f"    第{i+1}次: {format_ms(elapsed)}{cold}")

    avg_ms = total_ms / REPEAT_COUNT

    # 计算行数
    if isinstance(best_result, dict):
        # get_batch_process_by_flow 返回 {stepno: [...]}
        row_count = sum(len(v) for v in best_result.values()) if best_result else 0
    elif isinstance(best_result, list):
        row_count = len(best_result)
    else:
        row_count = 1

    print(f"    平均: {format_ms(avg_ms)} | 最慢: {format_ms(worst_ms)} | 最快: {format_ms(best_ms)} | 结果行数: {row_count}")
    record_timing(func_name, scenario, avg_ms, row_count)

    if avg_ms > 3000:
        warnings.append(f"{func_name} ({scenario}) 平均耗时 {format_ms(avg_ms)} 超 3 秒")

    return best_result


def show_generated_sql(target: date, stepno_list: list[int] | None = None, batch_mode: bool = False):
    """构造并打印与生产代码完全一致的 QuerySet 生成的 SQL"""
    from iwork.queries import get_records_queryset
    try:
        records = get_records_queryset(target).exclude(Flow='')
        if not batch_mode and stepno_list:
            records = records.filter(StepNo__in=stepno_list)
        qs = records.values('StepNo', 'Flow').annotate(qty=Sum('Qty')).order_by('StepNo', '-qty')
        sql = str(qs.query)
        print(f"    SQL: {sql[:500]}{'...' if len(sql) > 500 else ''}")
    except Exception as e:
        print(f"    (无法生成SQL预览: {e})")


def run_query_tests():
    """运行实际调用链中的核心查询耗时测试"""
    print_header("2. 核心查询耗时测试（仅测实际使用的函数）")

    from iwork import queries as remote_q
    from iwork import local_queries as local_q

    today = date.today()
    yesterday = today - timedelta(days=1)

    # ============================
    # 2.1 先获取当天 Top 8（确定测试参数）
    # ============================
    print(f"\n{SEP2}")
    print("  前置: 获取当天 Top 8 工序（用于后续测试参数）")
    top8, elapsed = timed(remote_q.get_process_stats, today, limit=TOP_N)
    top8_stepnos = [p['step'] for p in top8]
    print(f"  Top {TOP_N} 工序: {top8_stepnos}  (耗时 {format_ms(elapsed)})")

    if not top8_stepnos:
        print("  ⚠ 当天无数据，使用默认工序 [70]")
        top8_stepnos = [70]

    # ============================
    # 2.2 get_process_by_flow —— HTTP 回退路径
    # ============================
    print(f"\n{SEP2}")
    print("  ◆ 查询1: get_process_by_flow  [生产路径: Redis未命中 → _get_date_stats 回退]")
    print(f"    对应代码: statistics.py:420")
    print(f"{SEP2}")

    # 显示 SQL
    print()
    show_generated_sql(today, top8_stepnos, batch_mode=False)

    # 场景 A: 单工序 (stepno=70，前端默认)
    test_query_function(
        remote_q.get_process_by_flow,
        'get_process_by_flow (远程)',
        f'单工序 stepno=70 / {today.isoformat()}',
        today, TEST_STEPNO_SINGLE,
    )

    # 场景 B: Top 8 工序 (Redis 未命中时的实际行为)
    test_query_function(
        remote_q.get_process_by_flow,
        'get_process_by_flow (远程)',
        f'Top {len(top8_stepnos)} 工序 / {today.isoformat()}',
        today, top8_stepnos,
    )

    # 场景 C: 昨日对比
    test_query_function(
        remote_q.get_process_by_flow,
        'get_process_by_flow (远程)',
        f'Top {len(top8_stepnos)} 工序 / {yesterday.isoformat()}',
        yesterday, top8_stepnos,
    )

    # ============================
    # 2.3 get_batch_process_by_flow —— Celery 批量路径
    # ============================
    print(f"\n{SEP2}")
    print("  ◆ 查询2: get_batch_process_by_flow  [生产路径: Celery get_batch_stats 全工序]")
    print(f"    对应代码: statistics.py:180 (6线程池中执行)")
    print(f"{SEP2}")

    print()
    show_generated_sql(today, batch_mode=True)

    test_query_function(
        remote_q.get_batch_process_by_flow,
        'get_batch_process_by_flow (远程)',
        f'全工序 / {today.isoformat()}',
        today,
    )

    test_query_function(
        remote_q.get_batch_process_by_flow,
        'get_batch_process_by_flow (远程)',
        f'全工序 / {yesterday.isoformat()}',
        yesterday,
    )

    # ============================
    # 2.4 _get_date_stats 端到端 + 月趋势 —— 跳过
    #    (上一次运行确认：get_monthly_total_trend 跨月查询导致 Error 2013 连接丢失)
    # ============================
    print(f"\n{SEP2}")
    print("  ⊘ 查询3: _get_date_stats (端到端回退) + 月趋势 — 已跳过")
    print(f"    原因: 上次诊断确认 get_monthly_total_trend(整月) 导致")
    print(f"    MySQL Error 2013 'Lost connection'，不属于工序产量对比本身的问题")
    print(f"{SEP2}")

    # ============================
    # 2.5 Redis 缓存读取性能
    # ============================
    print(f"\n{SEP2}")
    print("  ◆ 查询4: Redis 缓存读取  [生产路径: 正常实时数据获取]")
    print(f"    对应代码: statistics.py:347 → get_realtime_stats()")
    print(f"{SEP2}")

    from django.core.cache import cache
    t0 = time.perf_counter()
    cached_data = cache.get('stats:realtime:70')
    redis_read_ms = (time.perf_counter() - t0) * 1000
    if cached_data:
        pf_count = len(cached_data.get('process_flow_stats', []))
        print(f"    Redis 'stats:realtime:70' 命中")
        print(f"    读取耗时: {format_ms(redis_read_ms)}")
        print(f"    process_flow_stats 条目数: {pf_count}")
        print(f"    缓存字段: {list(cached_data.keys())}")
    else:
        print(f"    Redis 'stats:realtime:70' 未命中 (耗时 {format_ms(redis_read_ms)})")
        print(f"    → 下次 HTTP 请求将触发 _get_date_stats 回退查库")
        warnings.append("Redis 缓存 'stats:realtime:70' 未命中，HTTP 请求将回退直查数据库")

    record_timing('Redis cache GET', 'stats:realtime:70', redis_read_ms, pf_count if cached_data else 0)

    # 也测一下 local 库
    if top8_stepnos:
        print(f"\n{SEP2}")
        print("  ◆ 查询5: local_queries.get_process_by_flow  [生产路径: 历史数据查询]")
        print(f"    对应代码: api_views_local.local_date_stats → _get_date_stats → local_q")
        print(f"{SEP2}")

        try:
            test_query_function(
                local_q.get_process_by_flow,
                'get_process_by_flow (本地库)',
                f'Top {len(top8_stepnos)} 工序 / {today.isoformat()}',
                today, top8_stepnos,
            )
        except Exception as e:
            print(f"    ⚠ 本地库查询失败 (可能未配置): {e}")


# ============================================================================
# 第三部分：SQL 执行计划分析
# ============================================================================


def analyze_query_plan(db_alias: str = 'iwork'):
    """对核心查询执行 EXPLAIN，分析索引使用情况"""
    print_header("3. SQL 执行计划与索引分析")

    today = date.today()
    from iwork.queries import get_date_range
    start, end = get_date_range(today)

    # --- 索引信息 ---
    print(f"\n  ◆ pytckreg3 表索引")
    try:
        with connections[db_alias].cursor() as cursor:
            cursor.execute("SHOW INDEX FROM pytckreg3")
            indexes = cursor.fetchall()
            if indexes:
                index_map: dict[str, list[str]] = {}
                for idx in indexes:
                    idx_name = idx[2]
                    col_name = idx[4]
                    cardinality = idx[6] or 0
                    if idx_name not in index_map:
                        index_map[idx_name] = {'cols': [], 'cardinality': cardinality}
                    index_map[idx_name]['cols'].append(col_name)

                has_date_index = False
                has_stepno_index = False
                has_flow_index = False
                for idx_name, info in index_map.items():
                    cols_str = ', '.join(info['cols'])
                    card = info['cardinality']
                    print(f"    {idx_name}: ({cols_str}) 基数={card:,}")
                    if 'RegDate' in info['cols']:
                        has_date_index = True
                    if 'StepNo' in info['cols']:
                        has_stepno_index = True
                    if 'Flow' in info['cols']:
                        has_flow_index = True

                # 检查覆盖 GROUP BY (StepNo, Flow) 的索引
                if not (has_date_index and has_stepno_index):
                    warnings.append(
                        "缺少 (RegDate, StepNo) 联合索引，可能导致全表扫描"
                    )
                if has_date_index and has_stepno_index and not has_flow_index:
                    print(f"    ⚠ 注意: GROUP BY (StepNo, Flow) 如果有 (RegDate, StepNo, Flow) 联合索引会更高效")
            else:
                print("    (无索引信息 — 可能权限不足)")
                warnings.append("无法读取 pytckreg3 索引信息，可能缺少 information_schema 权限")
    except Exception as e:
        print(f"    ⚠ 无法获取索引信息: {e}")

    # --- EXPLAIN ---
    print(f"\n  ◆ 查询执行计划 (日期: {today.isoformat()})")

    queries_to_explain = [
        (
            "get_process_by_flow — 单工序 (StepNo=70)",
            """
            SELECT StepNo, Flow, SUM(Qty) AS qty
            FROM pytckreg3
            WHERE RegDate >= %s AND RegDate < %s
              AND StepNo IN (70)
              AND Flow != ''
            GROUP BY StepNo, Flow
            ORDER BY StepNo, SUM(Qty) DESC
            """,
        ),
        (
            "get_batch_process_by_flow — 全工序 (无 StepNo 过滤)",
            """
            SELECT StepNo, Flow, SUM(Qty) AS qty
            FROM pytckreg3
            WHERE RegDate >= %s AND RegDate < %s
              AND Flow != ''
            GROUP BY StepNo, Flow
            ORDER BY StepNo, SUM(Qty) DESC
            """,
        ),
        (
            "get_process_stats — Top 8 (按产量排序)",
            """
            SELECT StepNo, SUM(Qty) AS qty
            FROM pytckreg3
            WHERE RegDate >= %s AND RegDate < %s
            GROUP BY StepNo
            ORDER BY SUM(Qty) DESC
            LIMIT 8
            """,
        ),
    ]

    for label, sql in queries_to_explain:
        print(f"\n  [{label}]")
        try:
            with connections[db_alias].cursor() as cursor:
                cursor.execute("EXPLAIN " + sql, (start, end))
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                for row in rows:
                    info = dict(zip(columns, row))
                    print(f"    type: {info.get('type')}, "
                          f"key: {info.get('key')}, "
                          f"possible_keys: {info.get('possible_keys')}, "
                          f"rows: {info.get('rows', '?')}, "
                          f"Extra: {info.get('Extra', '')}")

                    access_type = str(info.get('type', '')).upper()
                    key_used = info.get('key')
                    extra = str(info.get('Extra', ''))
                    rows_est = info.get('rows', 0) or 0

                    if access_type == 'ALL' and rows_est > 100000:
                        warnings.append(
                            f"全表扫描(type=ALL) 预估 {rows_est:,} 行 — {label}"
                        )
                    if access_type in ('ALL', 'index') and not key_used:
                        warnings.append(
                            f"未命中合适索引 (type={access_type}) — {label}"
                        )
                    if 'Using filesort' in extra:
                        warnings.append(
                            f"Using filesort — ORDER BY 无法利用索引 — {label}"
                        )
                    if 'Using temporary' in extra:
                        warnings.append(
                            f"Using temporary — GROUP BY 需要临时表 — {label}"
                        )
        except Exception as e:
            print(f"    ⚠ EXPLAIN 失败: {e}")


# ============================================================================
# 第四部分：统计汇总
# ============================================================================


def print_summary():
    """打印汇总表格和诊断建议"""
    print_header("4. 统计汇总与诊断建议")

    print(f"\n  {'查询函数':<35} {'场景':<35} {'平均耗时':>10} {'行数':>8}  状态")
    print(f"  {'-'*35} {'-'*35} {'-'*10} {'-'*8}  ----")
    for t in all_timings:
        print(f"  {t['name']:<35} {t['scenario']:<35} {format_ms(t['elapsed_ms']):>10} {t['row_count']:>8}  {status_marker(t['elapsed_ms'])}")

    # 异常阈值
    if all_timings:
        times = sorted(t['elapsed_ms'] for t in all_timings)
        median_ms = times[len(times) // 2]
        slow_threshold_ms = max(median_ms * 3, 5000)
        print(f"\n  异常阈值: {format_ms(slow_threshold_ms)} (中位数×3 与 5s 取大值)")

        slow = [t for t in all_timings if t['elapsed_ms'] >= slow_threshold_ms]
        if slow:
            print(f"\n  ⚠ 以下查询超出异常阈值:")
            for t in slow:
                print(f"    - {t['name']} ({t['scenario']}): {format_ms(t['elapsed_ms'])}")
        else:
            print(f"\n  ✓ 所有查询在阈值内")

    # 关键数据总结
    print(f"\n  ◆ 关键数据分析:")
    batch_times = [t for t in all_timings if 'batch_process_by_flow' in t['name']]
    pf_times = [t for t in all_timings if 'get_process_by_flow' in t['name'] and 'batch' not in t['name']]
    end_to_end = [t for t in all_timings if '_get_date_stats' in t['name']]

    if batch_times:
        max_batch = max(t['elapsed_ms'] for t in batch_times)
        print(f"    Celery批量查询(get_batch_process_by_flow) 最慢: {format_ms(max_batch)}")
        # read_timeout=30s, QUERY_TIMEOUT=45s
        if max_batch > 25000:
            warnings.append(f"Celery 批量查询耗时 {format_ms(max_batch)} 接近 read_timeout(30s)，有超时风险")
        if max_batch > 40000:
            warnings.append(f"Celery 批量查询耗时 {format_ms(max_batch)} 超过 QUERY_TIMEOUT(45s)，会导致任务失败")

    if pf_times:
        max_pf = max(t['elapsed_ms'] for t in pf_times)
        print(f"    HTTP回退查询(get_process_by_flow) 最慢: {format_ms(max_pf)}")
        if max_pf > 5000:
            warnings.append(f"HTTP 回退查询 {format_ms(max_pf)} 超过 5s，会阻塞用户请求")

    if end_to_end:
        max_e2e = end_to_end[0]['elapsed_ms']
        print(f"    端到端回退(_get_date_stats) 总耗时: {format_ms(max_e2e)}")
        if max_e2e > 10000:
            warnings.append(f"Redis 未命中时端到端查询耗时 {format_ms(max_e2e)}，HTTP 请求超时风险极高")

    # 诊断建议
    if warnings:
        print(f"\n  ◆ 诊断建议 ({len(warnings)} 条):")
        for i, w in enumerate(warnings, 1):
            print(f"    {i}. ⚠ {w}")
    else:
        print(f"\n  ✓ 未发现明显问题")

    print(f"\n{SEP}")
    print(f"  诊断完成。以上所有查询均为只读，未修改任何生产代码或数据。")
    print(f"{SEP}\n")


# ============================================================================
# 主流程
# ============================================================================


def main():
    """主诊断流程"""
    print(f"\n{SEP}")
    print(f"  工序产量对比 — 数据查询诊断工具")
    print(f"  运行时间: {date.today().isoformat()}")
    print(f"  目标数据库: iwork (远程 192.168.3.15 / payroll.pytckreg3)")
    print(f"{SEP}")

    # ---- 第一部分：连通性 ----
    print_header("1. 连通性测试")

    from django.conf import settings
    db_config = settings.DATABASES.get('iwork', {})
    db_host = db_config.get('HOST', 'unknown')
    db_port = int(db_config.get('PORT', 3306))

    # TCP
    print(f"\n  TCP 连接 ({db_host}:{db_port}) ...")
    tcp_result = test_tcp_connectivity(db_host, db_port)
    if tcp_result['success']:
        print(f"    平均延迟: {format_ms(tcp_result['elapsed_ms'])} ✓")
    else:
        print(f"    ✗ 连接失败: {tcp_result['error']}")
        warnings.append(f"TCP 连接失败 ({db_host}:{db_port}): {tcp_result['error']}")

    # ORM
    print(f"\n  Django ORM (SELECT 1) ...")
    orm_result = test_django_orm_connectivity('iwork')
    if orm_result['success']:
        print(f"    延迟: {format_ms(orm_result['elapsed_ms'])} ✓")
    else:
        print(f"    ✗ 查询失败: {orm_result['error']}")
        warnings.append(f"ORM 连通性测试失败: {orm_result['error']}")

    # DB 配置信息
    print(f"\n  数据库连接配置:")
    print(f"    CONN_MAX_AGE: {db_config.get('CONN_MAX_AGE')}s")
    print(f"    connect_timeout: {db_config.get('OPTIONS', {}).get('connect_timeout', 'N/A')}s")
    print(f"    read_timeout: {db_config.get('OPTIONS', {}).get('read_timeout', 'N/A')}s")
    print(f"    CONN_HEALTH_CHECKS: {db_config.get('CONN_HEALTH_CHECKS')}")
    from iwork.statistics import QUERY_TIMEOUT
    print(f"    QUERY_TIMEOUT (statistics.py): {QUERY_TIMEOUT}s")

    # MySQL 状态
    print()
    show_mysql_status('iwork')

    # 连通性都失败则终止
    if not tcp_result['success'] and not orm_result['success']:
        print(f"\n  ✗ 数据库无法连接，终止诊断。")
        print_summary()
        return 1

    # ---- 第二部分：查询耗时 ----
    run_query_tests()

    # ---- 第三部分：SQL 执行计划 ----
    analyze_query_plan('iwork')

    # ---- 第四部分：汇总 ----
    print_summary()
    return 0


if __name__ == '__main__':
    sys.exit(main())
