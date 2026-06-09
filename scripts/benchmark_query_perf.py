"""
查询性能对比测试 v3：并行 + 月降频
"""
import time, os, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.settings')
import django; django.setup()

from iwork.statistics import get_today_stats

TODAY = date.today()
print(f"Date: {TODAY}")
print(f"Month: {TODAY.year}-{TODAY.month:02d}")

# Warmup
print("\n[Warmup]")
_ = get_today_stats(stepno_filter=[70])

# Round 1: stepno_filter=[70] (smaller result set)
print("\n[Round 1] stepno_filter=[70] (normal use case)")
times_70 = []
for i in range(3):
    t0 = time.perf_counter()
    stats = get_today_stats(stepno_filter=[70])
    elapsed = time.perf_counter() - t0
    times_70.append(elapsed)
    print(f"  Run {i+1}: {elapsed:.4f}s")

# Round 2: stepno_filter=None (all processes)
print("\n[Round 2] stepno_filter=None (all processes)")
times_all = []
for i in range(3):
    t0 = time.perf_counter()
    stats = get_today_stats()
    elapsed = time.perf_counter() - t0
    times_all.append(elapsed)
    print(f"  Run {i+1}: {elapsed:.4f}s")

# Round 3: Cached monthly (repeat to show cache effect)
print("\n[Round 3] stepno_filter=[70] (monthly cache warm)")
times_cached = []
for i in range(3):
    t0 = time.perf_counter()
    stats = get_today_stats(stepno_filter=[70])
    elapsed = time.perf_counter() - t0
    times_cached.append(elapsed)
    print(f"  Run {i+1}: {elapsed:.4f}s")

print("\n" + "=" * 60)
print("[Results]")
print(f"  stepno_filter=[70] avg: {sum(times_70)/len(times_70):.4f}s")
print(f"  stepno_filter=None avg: {sum(times_all)/len(times_all):.4f}s")
print(f"  cached monthly avg:    {sum(times_cached)/len(times_cached):.4f}s")
print(f"  Optimized queries: 10 -> 8 (merged station)")
print(f"  Phases: 2 (not 10 sequential)")
print(f"  Monthly cache: 5min TTL")
print("=" * 60)
