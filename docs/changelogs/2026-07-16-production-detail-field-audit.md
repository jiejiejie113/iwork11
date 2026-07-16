# 生产详情字段来源与公式核对清单

## 核对范围

- Eastex 生产看板 - 生产详情 - `SO5-L5C`
- Eastex 生产看板 - 生产详情 - 按产品名称
- 入口：
  - `http://192.168.30.190:8080/iwork/production/detail-data/flow/SO5-L5C/`
  - `http://192.168.30.190:8080/iwork/production/detail-data/`

## 本次系统核对结论

本次只读核对未发现字段来源或公式问题。核对时先刷新了详情 Redis 快照，再对 API
返回值与来源表、组合键元数据和公式结果做比对。

核对日期：`2026-07-16`

### SO5-L5C

| 项目            | 结果 |
| --------------- | ---- |
| 员工数          | 24   |
| 工序组合行      | 51   |
| 有效上班分钟    | 147  |
| Flow 公式错误数 | 0    |

样例：

| 字段     | 值             |
| -------- | -------------- |
| 员工     | `1942`       |
| 本厂款号 | `BU1208A`    |
| 工序号   | `38`         |
| 工序描述 | `翻猪肠绑绳` |
| 产量     | `183`        |
| 标准工时 | `0.131`      |
| 产值     | `23.973`     |

公式：

```text
183 * 0.131 = 23.973
```

### 按产品名称

| 项目               | 结果 |
| ------------------ | ---- |
| 产品数             | 17   |
| 产品工序公式错误数 | 0    |

样例：

| 字段     | 值                   |
| -------- | -------------------- |
| 产品名称 | `Sage pile jacket` |
| 本厂款号 | `BU1191`           |
| 工序号   | `15`               |
| 工序描述 | `走定领底边线`     |
| 产量     | `685`              |
| 标准工时 | `0.266`            |
| 产值     | `182.21`           |

公式：

```text
685 * 0.266 = 182.21
```

## 注意事项

今日数据优先读取 Redis 快照。生产打卡表会持续增长，因此人工核对时如果直接查
`pytckreg3` 当前原始表，可能会看到 API 与数据库存在短暂数量差异。差异通常来自
缓存刷新窗口，不一定代表公式错误。

建议人工核对前先等待下一轮 Celery 任务，或手动刷新详情缓存后立即核对。

## 字段来源清单

### SO5-L5C Flow 员工明细

| 页面/API 字段 | 来源                             | 规则                                               |
| ------------- | -------------------------------- | -------------------------------------------------- |
| 员工ID        | `pytckreg3.RegPerSysID`        | 按 Flow + 员工分组                                 |
| 本厂款号      | `pytckreg3.WrkOrder`           | 使用完整值，不截取前 6 位                          |
| 工序号        | `pytckreg3.StepNo`             | 与`WrkOrder` 组成组合键                          |
| 工序描述      | `pywrkstp.Description`         | 按`(WrkOrder, StepNo)` 精确匹配                  |
| 标准工时      | `pywrkstp.StepTime`            | 按`(WrkOrder, StepNo)` 精确匹配                  |
| 产量          | `SUM(pytckreg3.Qty)`           | 按`Flow + RegPerSysID + WrkOrder + StepNo` 聚合  |
| 产值          | 计算字段                         | `产量 * 标准工时`                                |
| 总产量        | 计算字段                         | 员工所有可见工序产量求和                           |
| 总产值        | 计算字段                         | 员工所有工序产值求和；任一工序缺标准工时时返回空值 |
| 员工效率      | 计算字段                         | `总产值 / 有效上班分钟 * 100%`                   |
| 目标          | `target_production.target_qty` | 按日期 + 员工/本厂款号读取                         |
| 目标达成率    | 前端计算                         | `总产量 / 目标 * 100%`                           |

### 按产品名称

| 页面/API 字段 | 来源                               | 规则                                      |
| ------------- | ---------------------------------- | ----------------------------------------- |
| 产品名称      | `production_orders.product_name` | 使用`WrkOrder[:6] = style_no` 匹配      |
| 本厂款号      | `pytckreg3.WrkOrder`             | 使用完整值                                |
| 工序号        | `pytckreg3.StepNo`               | 与`WrkOrder` 组成组合键                 |
| 工序描述      | `pywrkstp.Description`           | 按`(WrkOrder, StepNo)` 精确匹配         |
| 标准工时      | `pywrkstp.StepTime`              | 按`(WrkOrder, StepNo)` 精确匹配         |
| 产量          | `SUM(pytckreg3.Qty)`             | 按`WrkOrder + StepNo + Flow` 聚合后汇总 |
| 人数          | `COUNT(DISTINCT RegPerSysID)`    | 现行口径是先按 Flow 去重，再在工序层相加  |
| 产值          | 计算字段                           | `产量 * 标准工时`                       |
| 图表产量视图  | API`qty`                         | 按产量降序构建图表                        |
| 图表产值视图  | API`output_value`                | 按产值降序构建图表                        |

## 特殊聚合字段公式

### 产值 = output_value

```text
output_value = qty * step_time
```

规则：

- `step_time` 来自 `pywrkstp.StepTime`。
- `step_time = 0` 时，产值正常显示为 `0`。
- `step_time` 缺失时，产值返回空值，页面显示 `--`。

### 员工效率 = employee_efficiency

```text
employee_efficiency = employee_output_value / work_minutes * 100
```

规则：

- `employee_output_value` 为员工所有工序产值汇总。
- 任一工序缺标准工时时，员工总产值为空，员工效率显示 `--`。
- 员工效率按当前 Flow 的全日总产值计算，不随页面上的本厂款号筛选或左侧工序筛选改变。

### 有效上班分钟

业务时区：`Asia/Bangkok`

| 时间段          | 规则                                      |
| --------------- | ----------------------------------------- |
| `07:00` 前    | 返回空值，页面显示`--`                  |
| `07:00-11:00` | 当前时间减`07:00`                       |
| `11:00-12:00` | 固定`240` 分钟                          |
| `12:00` 后    | 当前时间减`08:00`，等价于扣除一小时午休 |
| 历史日期        | 返回空值，页面显示`--`                  |

### 目标达成率 = target_rate

```text
target_rate = total_qty / target_qty * 100
```

规则：

- 目标值来自本地表 `target_production`。
- 员工级目标：`workorder = ''`。
- 本厂款号级目标：`workorder = <本厂款号>`。
- 页面编辑本厂款号目标后，会把同一员工的本厂款号目标加总为员工总目标。

## 核对步骤

### 1. 查看 API 实际返回

Flow 员工明细：

```text
http://192.168.30.190:8080/iwork/api/dashboard/detail/flow/SO5-L5C/?date=2026-07-16
```

按产品名称：

```text
http://192.168.30.190:8080/iwork/api/dashboard/detail/product-overview/?date=2026-07-16
```

### 2. 抽一条 SO5-L5C 工序行反查

示例：员工 `1942`、本厂款号 `BU1208A`、工序 `38`。

```powershell
@'
from datetime import date
from django.db.models import Sum
from iwork.queries import get_records_queryset
from iwork.models import Pywrkstp

d = date.fromisoformat("2026-07-16")
qty = get_records_queryset(d).filter(
    Flow="SO5-L5C",
    RegPerSysID=1942,
    WrkOrder="BU1208A",
    StepNo=38,
).aggregate(qty=Sum("Qty"))["qty"]

meta = Pywrkstp.objects.using("iwork").get(WrkOrder="BU1208A", StepNo=38)

print("qty =", qty)
print("description =", meta.Description)
print("step_time =", meta.StepTime)
print("output_value =", qty * meta.StepTime)
'@ | docker exec -i DKT_iwork python manage.py shell
```

核对：

```text
页面/API 产量 == qty
页面/API 工序描述 == meta.Description
页面/API 标准工时 == meta.StepTime
页面/API 产值 == qty * meta.StepTime
```

### 3. 抽一条按产品名称工序行反查

示例：本厂款号 `BU1191`、工序 `15`。

```powershell
@'
from datetime import date
from django.db.models import Sum, Count
from iwork.queries import get_records_queryset
from iwork.models import Pywrkstp
from iwork.local_models import ProductionOrder

d = date.fromisoformat("2026-07-16")
rows = list(
    get_records_queryset(d)
    .filter(WrkOrder="BU1191", StepNo=15)
    .values("Flow")
    .annotate(qty=Sum("Qty"), workers=Count("RegPerSysID", distinct=True))
    .order_by("Flow")
)

qty = sum(row["qty"] or 0 for row in rows)
workers = sum(row["workers"] or 0 for row in rows)
meta = Pywrkstp.objects.using("iwork").get(WrkOrder="BU1191", StepNo=15)
product = ProductionOrder.objects.using("iwork_local").filter(style_no="BU1191"[:6]).first()

print("product_name =", product.product_name if product else "未分类")
print("qty =", qty)
print("workers =", workers)
print("description =", meta.Description)
print("step_time =", meta.StepTime)
print("output_value =", qty * meta.StepTime)
print("flows =", rows)
'@ | docker exec -i DKT_iwork python manage.py shell
```

核对：

```text
页面/API 产品名称 == product_name
页面/API 产量 == qty
页面/API 人数 == workers
页面/API 工序描述 == meta.Description
页面/API 标准工时 == meta.StepTime
页面/API 产值 == qty * meta.StepTime
页面/API flow 明细 == rows
```

### 4. 抽查建议

建议人工至少抽查以下三类：

| 类型                     | 目的                                                                |
| ------------------------ | ------------------------------------------------------------------- |
| 普通标准工时行           | 验证描述、工时、产值基础链路                                        |
| 标准工时为`0` 的行     | 验证产值应显示`0` 而不是 `--`                                   |
| 同一工序号、不同本厂款号 | 验证描述和标准工时确实按`(WrkOrder, StepNo)`，不是只按 `StepNo` |

## 缓存刷新核对命令

如果发现 API 与原始表数量不一致，先刷新详情缓存后立即重查：

```powershell
@'
from iwork.statistics import get_batch_detail_stats, cache_detail_batch_to_redis

batch = get_batch_detail_stats()
cache_detail_batch_to_redis(batch)
print("detail cache refreshed")
'@ | docker exec -i DKT_iwork python manage.py shell
```

刷新后再次访问 API 或页面核对。
