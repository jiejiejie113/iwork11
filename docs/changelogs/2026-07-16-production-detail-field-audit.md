# 生产详情字段来源与聚合说明

## 1. 数据来源

适用模块：

- 生产详情 - `SO5-L5C`；
- 生产详情 - 按产品名称。

今日数据来源：

| 表                                | 用途                                       |
| --------------------------------- | ------------------------------------------ |
| `payroll.pytckreg3`             | 生产打卡、员工、Flow、本厂款号、工序和产量 |
| `payroll.pywrkstp`              | 工序描述和标准工时                         |
| `iwork_local.production_orders` | 产品名称和生产单号                         |
| `iwork_local.target_production` | 员工目标和本厂款号目标                     |

历史数据来源：

| 表                                         | 用途                           |
| ------------------------------------------ | ------------------------------ |
| `iwork_local.historical_production_fact` | 历史生产聚合事实               |
| `iwork_local.historical_step_snapshot`   | 当日冻结的工序、工时和产品信息 |
| `iwork_local.target_production`          | 对应历史日期的目标             |

历史页面只读取本地历史快照，不使用当前远程数据覆盖历史字段。

## 2. SO5-L5C 字段来源

| 前端字段   | 今日字段                         | 历史字段                                   | 聚合或匹配规则                         |
| ---------- | -------------------------------- | ------------------------------------------ | -------------------------------------- |
| 员工 ID    | `pytckreg3.RegPerSysID`        | `historical_production_fact.employee_id` | 按 Flow 和员工分组                     |
| 本厂款号   | `pytckreg3.WrkOrder`           | `historical_production_fact.wrk_order`   | 使用完整值                             |
| 工序号     | `pytckreg3.StepNo`             | `historical_production_fact.step_no`     | 与本厂款号组成组合键                   |
| 工序描述   | `pywrkstp.Description`         | `historical_step_snapshot.description`   | 按本厂款号、工序号匹配                 |
| 标准工时   | `pywrkstp.StepTime`            | `historical_step_snapshot.step_time`     | 与工序描述取自同一记录                 |
| 产量       | `SUM(pytckreg3.Qty)`           | `SUM(historical_production_fact.qty)`    | 按 Flow、员工、本厂款号、工序汇总      |
| 产值       | 计算字段                         | 计算字段                                   | `产量 * 标准工时`                    |
| 总产量     | 计算字段                         | 计算字段                                   | 员工在当前 Flow 的全部工序产量之和     |
| 总产值     | 计算字段                         | 计算字段                                   | 员工在当前 Flow 的全部工序产值之和     |
| 目标       | `target_production.target_qty` | 同左                                       | 按日期、员工、本厂款号读取             |
| 目标达成率 | 计算字段                         | 计算字段                                   | `总产量 / 员工总目标 * 100%`         |
| 员工效率   | 计算字段                         | 不计算                                     | 今日为`总产值 / 有效上班分钟 * 100%` |

工序描述和标准工时必须使用以下组合键：

```text
(完整本厂款号, 工序号)
```

不能只按工序号匹配。

## 3. SO5-L5C 聚合来源

展开表的一行代表：

```text
Flow + 员工 ID + 完整本厂款号 + 工序号
```

聚合公式：

```text
工序产量 = SUM(该组合下的 Qty)
工序产值 = 工序产量 * 标准工时
员工总产量 = SUM(员工全部工序产量)
员工总产值 = SUM(员工全部工序产值)
```

特殊规则：

- 标准工时为 `0`，工序产值为 `0`；
- 标准工时缺失，工序产值显示 `--`；
- 任一工序缺少标准工时，员工总产值整体显示 `--`；
- 筛选本厂款号或工序，只改变明细展示，不改变员工全日总产值和员工效率。

## 4. 目标和员工效率

目标唯一定位条件：

```text
target_date + employee_id + workorder
```

| `workorder` | 含义                     |
| ------------- | ------------------------ |
| 空字符串      | 员工当日总目标           |
| 完整本厂款号  | 员工在该本厂款号上的目标 |

目标必须按日期隔离，不能读取相邻日期中同一员工的目标。

员工效率：

```text
员工效率 = 员工总产值 / 有效上班分钟 * 100%
```

有效上班分钟使用 `Asia/Bangkok` 时区：

- `07:00` 前为空；
- `07:00-11:00` 为当前时间减 `07:00`；
- `11:00-12:00` 固定为 `240` 分钟；
- `12:00` 后为当前时间减 `08:00`，即扣除一小时午休；
- 历史日期不计算员工效率，页面显示 `--`。

## 5. 按产品名称字段来源

| 前端字段 | 今日字段                           | 历史字段                                   | 聚合或匹配规则                        |
| -------- | ---------------------------------- | ------------------------------------------ | ------------------------------------- |
| 产品名称 | `production_orders.product_name` | `historical_step_snapshot.product_name`  | 今日按款号前 6 位映射，历史使用冻结值 |
| 生产单号 | `production_orders.order_no`     | `historical_step_snapshot.order_no`      | 与产品映射记录一致                    |
| 本厂款号 | `pytckreg3.WrkOrder`             | `historical_production_fact.wrk_order`   | 使用完整值                            |
| 工序号   | `pytckreg3.StepNo`               | `historical_production_fact.step_no`     | 与本厂款号组成组合键                  |
| 工序描述 | `pywrkstp.Description`           | `historical_step_snapshot.description`   | 按组合键匹配                          |
| 标准工时 | `pywrkstp.StepTime`              | `historical_step_snapshot.step_time`     | 按组合键匹配                          |
| 产量     | `pytckreg3.Qty`                  | `historical_production_fact.qty`         | 先按 Flow 汇总，再汇总到工序          |
| 人数     | `pytckreg3.RegPerSysID`          | `historical_production_fact.employee_id` | 每个 Flow 内去重后在工序层相加        |
| 产值     | 计算字段                           | 计算字段                                   | `工序产量 * 标准工时`               |

今日产品映射规则：

```text
LEFT(完整本厂款号, 6) = production_orders.style_no
```

## 6. 按产品名称聚合来源

页面层级：

```text
产品名称 -> 完整本厂款号 -> 工序号 -> Flow
```

各层聚合：

```text
Flow 产量 = SUM(本厂款号 + 工序号 + Flow 下的数量)
Flow 人数 = COUNT(DISTINCT 员工 ID)

工序产量 = SUM(各 Flow 产量)
工序人数 = SUM(各 Flow 去重人数)
工序产值 = 工序产量 * 标准工时

本厂款号产量 = SUM(该本厂款号下所有工序产量)
产品总产量 = SUM(该产品下所有本厂款号产量)
```

工序人数不是跨所有 Flow 全局去重。同一员工出现在两个 Flow 时，当前口径会计算两次。

## 7. 核对重点

| 核对项       | 应核对的数据库来源或公式                 |
| ------------ | ---------------------------------------- |
| 描述、工时   | 同一个完整本厂款号和工序号对应的工序记录 |
| 工序产量     | 对应组合下的数量之和                     |
| 工序产值     | 工序产量乘标准工时                       |
| 员工总量     | 当前 Flow 下员工全部工序之和             |
| 目标         | 日期、员工和本厂款号必须完全一致         |
| 员工效率     | 今日总产值除以曼谷时区有效上班分钟       |
| 产品名称     | 今日按款号前 6 位映射；历史使用冻结映射  |
| 产品工序人数 | 每个 Flow 内去重后相加                   |
