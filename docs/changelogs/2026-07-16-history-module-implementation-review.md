# 历史模块生产详情与本地持久化实施回顾

## 1. 文档目的

本文详细记录 2026-07-16 对 iwork 历史模块进行的设计、实现、数据回填、部署和验收。
主要目标是让用户能够按历史日期查看与今日生产详情一致的 Flow、工序和产品数据，
同时降低远程生产数据库的大表查询压力。

对应提交：

```text
f0db5c3 [2026-07-16][FEAT] 完善历史生产详情与本地快照
7ac5d50 [2026-07-16][FIX] 完善历史快照错误提示与规范
```

关联设计决策：`docs/adr/006-local-history-snapshots.md`。

## 2. 改造前状态

### 2.1 历史功能停留在聚合看板阶段

原历史页面能够选择日期并查看总产量、工序、小时趋势和工位排行，但没有进入所选
日期生产详情的完整操作路径。生产详情页面内部虽然已经存在 `selectedDate`，但：

- 页面没有完整的历史日期入口和状态提示；
- Flow、工序和产品之间跳转时不会保留日期；
- 生产详情请求没有自动选择本地历史数据源；
- 历史日期仍可能执行自动刷新和目标编辑；
- 快照不存在时，前端不能明确显示原因。

### 2.2 本地历史存储没有真正落地

旧设计使用 `LocalPytckreg3` 映射 `iwork_local.pytckreg3`，但运行环境检查发现：

- `iwork_local.pytckreg3` 实际不存在；
- 模型使用 `managed=False`，Django 迁移不会创建该表；
- `mode=local` 的 Flow 概览请求返回 HTTP 500；
- 旧同步逻辑使用 `TicketNo` 作为唯一键，而远程真实主键还包含
  `SysSource + SeqNo`，存在覆盖不同源记录的风险；
- 同步采用逐条 `update_or_create`，不适合每天十几万条记录的长期镜像。

### 2.3 远程查询压力

只读评估结果：

| 项目 | 结果 |
| --- | ---: |
| 远程 `pytckreg3` 估算总行数 | 约 3,900 万 |
| 2026-07-15 原始记录数 | 191,166 |
| 2026-07-15 总产量 | 916,929 |
| 历史 Flow 概览查询 | 约 3.55 秒 |
| 历史 SO5-L5C 详情查询 | 约 3.93 秒 |
| 历史产品概览查询 | 约 3.21 秒 |

远程查询虽然命中了 `RegDate` 索引，但聚合仍使用临时表和 filesort。继续直接查询会随
远程表增长而增加响应时间和数据库负载。

## 3. 核心设计决策

### 3.1 不复制原始票据，保存查询所需聚合事实

最终采用“小时级生产事实 + 日期元数据快照 + 同步状态”的结构，而不是复制全部原始
`pytckreg3` 记录。

事实粒度：

```text
生产日期 + 小时 + Flow + 工位 + 员工 + 本厂款号 + 工序
```

样本日该粒度为 23,897 行，相比 191,166 条原始记录减少约 87.5%，同时能够支持：

- 历史总产量和工单数；
- 小时趋势、工位排行和热力图；
- Flow 概览和员工工序明细；
- 工序概览和员工明细；
- 按产品名称、本厂款号、工序和 Flow 的四层详情；
- 产量看板所需员工、工单、工序和 Flow 过滤。

### 3.2 历史元数据必须冻结

工序描述和标准工时来自远程 `pywrkstp`，产品名称来自本地 `production_orders`。
这些元数据可能在生产日期结束后被修订，因此同步时按日期冻结：

```text
(snapshot_date, wrk_order, step_no)
```

历史产值使用快照中的 `step_time`，避免以后修改工时导致同一历史日期显示不同结果。

### 3.3 今日与历史自动选择数据源

数据源规则统一为：

| 日期 | 默认数据源 |
| --- | --- |
| 曼谷业务日期当天 | Redis / 远程实时查询回退 |
| 早于曼谷业务日期 | 本地成功发布的历史快照 |

历史日期不再提供 `local/remote` 切换，旧客户端携带的 `mode` 参数会被忽略。远程源只在
快照构建流程内部读取，普通历史 GET 不允许绕过本地快照。

普通历史请求不会因为本地数据缺失而静默回查远程大表。快照不存在时返回：

```json
{
  "error": "该日期尚未生成本地历史快照",
  "code": "history_snapshot_not_found"
}
```

前端收到该错误后自动调用：

```text
POST /api/history/snapshots/<date>/ensure/
```

构建成功后重试原 GET，并显示快照日期、版本和源记录数。已有成功快照时确保接口直接
返回现有状态，不会重复重建。原“同步数据”按钮及 `/api/history/sync/<date>/` 已删除。

## 4. 本地数据模型

### 4.1 `historical_production_fact`

用途：保存按小时聚合的历史生产事实。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `production_date` | 生产日期 |
| `event_hour` | 生产小时，未知为 -1 |
| `flow` | 生产线 |
| `station_id` | 工位 |
| `employee_id` | 员工系统 ID |
| `wrk_order` | 完整本厂款号 |
| `step_no` | 工序号 |
| `qty` | 聚合产量 |
| `source_record_count` | 该聚合行代表的远程原始记录数 |

唯一约束覆盖完整事实粒度。主要索引覆盖 Flow 员工查询、产品工序查询、工序员工查询
和日期小时查询。

### 4.2 `historical_step_snapshot`

用途：冻结生产日期对应的工序和产品元数据。

主要字段：

```text
snapshot_date, wrk_order, step_no, description, step_time,
style_no, product_name, order_no
```

### 4.3 `historical_sync_state`

用途：记录一个日期是否可以对用户发布，以及完整性校验摘要。

主要字段：

```text
snapshot_date, status, source_row_count, source_total_qty,
fact_row_count, metadata_row_count, missing_metadata_count,
snapshot_version, error_message, started_at, completed_at
```

只有 `status=success` 的日期会出现在本地历史日期列表中。

## 5. 快照生成与发布流程

### 5.1 远程只读聚合

`RemoteHistorySource` 使用 `RegDate` 日期范围过滤远程 `pytckreg3`，直接按历史事实粒度
执行 SQL 聚合，返回：

- 聚合事实行；
- 每个事实行对应的源记录数；
- 源记录总数；
- 源总产量；
- 本厂款号和工序组合列表。

随后批量读取 `pywrkstp` 和 `production_orders`，构建元数据快照。

### 5.2 发布前校验

发布前执行两项硬校验：

```text
SUM(fact.source_record_count) == source_row_count
SUM(fact.qty) == source_total_qty
```

任一校验失败都不会发布新快照。

### 5.3 原子替换

同一日期的旧事实和元数据在 `iwork_local` 数据库事务内删除并批量写入新数据。只有
全部写入成功后，同步状态才切换为 `success`。

已有成功快照重新生成失败时，旧成功数据继续可读，不会因失败任务被隐藏。

### 5.4 版本

每次成功重建同一日期，`snapshot_version` 增加 1。版本用于判断某个历史页面使用的是
哪一轮快照，不用于业务公式计算。

## 6. 自动同步与人工回填

### 6.1 单日回填

```powershell
docker exec DKT_iwork python manage.py snapshot_history --date 2026-07-15
```

### 6.2 日期范围回填

```powershell
docker exec DKT_iwork python manage.py snapshot_history `
  --start 2026-06-16 `
  --end 2026-07-15 `
  --continue-on-error
```

### 6.3 自动任务

Celery Beat 每天上海时间 03:00，也就是曼谷业务时间 02:00，执行：

```text
iwork.tasks.snapshot_recent_history(days=3)
```

任务重建最近三个已经结束的生产日期，用于吸收迟到记录和源库修正。

### 6.4 数据库迁移

新增迁移：

```text
iwork/migrations/0004_historical_production_snapshots.py
```

`start.sh` 不再吞掉 `iwork_local` 迁移错误。历史表迁移失败时容器会停止启动，避免应用
在表不存在的情况下继续对外服务。

## 7. 后端接口改造

### 7.1 自动数据源选择

生产详情相关端点统一按日期解析数据源：

```text
GET /api/dashboard/detail/flows/?date=<date>
GET /api/dashboard/detail/flow/<flow>/?date=<date>
GET /api/dashboard/detail/stepno-overview/?date=<date>
GET /api/dashboard/detail/stepno/<stepno>/?date=<date>
GET /api/dashboard/detail/product-overview/?date=<date>
GET /api/dashboard/workorders/?date=<date>
```

Flow 和产品历史响应增加：

```text
source = local_snapshot
snapshot_date
snapshot_version
```

### 7.2 历史总览兼容

历史总览统一为本地快照接口：

```text
GET /api/history/date/<date>/
GET /api/history/dates/
POST /api/history/snapshots/<date>/ensure/
```

`local_queries.py` 已改为读取新的历史事实表。原 MySQL 专用 `HOUR()` 和 `DATE()`
字符串查询改为 Django `ExtractHour` 和 `TruncDate`，使 MySQL 与测试数据库行为一致。

## 8. 前端改造

### 8.1 历史看板入口

历史看板日期区域保留日期选择和“查看生产详情”，跳转到：

```text
/production/detail-data/?date=<selectedDate>
```

日期改变后直接加载，不再显示“本地/远程”切换、“加载数据”和“同步数据”按钮。缺少
快照时页面显示“正在构建”，完成后显示快照版本和源记录数。

### 8.2 生产详情日期状态

生产详情从 URL 查询参数读取日期。没有日期时使用 `Asia/Bangkok` 的业务日期。

历史日期显示绿色“本地历史快照”状态和实际快照消息，日期切换后重新加载当前视图。
历史页面不显示“最后更新（柬埔寨时间）”，避免把静态快照误解为实时刷新数据。

### 8.3 导航保留日期

以下导航全部保留 `date` 参数：

- 概览进入 Flow 详情；
- 概览进入工序详情；
- 详情返回生产详情概览；
- 按生产线、按工序和按产品名称切换。

### 8.4 历史只读规则

历史日期：

- 不显示目标编辑按钮；
- 不执行 60 秒自动刷新；
- 不修改目标产量；
- 从 `target_production` 按 `target_date + employee_id + workorder` 加载当日目标；
- 不使用 `localStorage` 目标兜底，页面内目标恢复键包含日期、详情类型和详情键；
- 员工效率继续显示 `--`；
- 快照不存在时自动构建；构建失败才显示后端错误。

页面增加统一 `readResponse()`，HTTP 非 2xx 响应不会再被当作正常卡片数据解析。

## 9. 历史字段与公式

### 9.1 Flow 员工工序行

```text
产量 = SUM(qty)
分组 = Flow + employee_id + wrk_order + step_no
工序描述 = 历史元数据快照.description
标准工时 = 历史元数据快照.step_time
工序产值 = 产量 * 标准工时
```

### 9.2 员工汇总

```text
员工总产量 = SUM(员工所有工序产量)
员工总产值 = SUM(员工所有工序产值)
```

任一工序缺少标准工时时，员工总产值返回 `null`。标准工时为 0 时，工序产值为 0。

### 9.3 产品视图

产品视图继续使用：

```text
产品 -> 本厂款号 -> 工序 -> Flow
```

产品名称和生产单号来自同步时冻结的映射，不在历史请求时重新读取当前映射。

### 9.4 历史员工效率

历史员工效率暂时不推算，返回 `null`，页面显示 `--`。原因是当前系统尚未定义历史
日期的班次结束时间、加班时长和特殊休息日。以后需要先引入班次日历，再把最终有效
上班分钟作为历史快照字段。

## 10. 数据回填结果

本轮已完成最近 30 天回填：

| 项目 | 结果 |
| --- | ---: |
| 日期范围 | 2026-06-16 至 2026-07-15 |
| 成功日期 | 30 |
| 失败日期 | 0 |
| 远程源记录总数 | 4,202,753 |
| 本地聚合事实总数 | 543,204 |
| 元数据快照总数 | 44,426 |

其中 2026-06-21 和 2026-07-05 没有生产记录，仍以成功的空快照保存。这代表“该日期已
核对且没有数据”，不同于“尚未同步”。

### 2026-07-15 对账

| 项目 | 远程 | 本地快照 |
| --- | ---: | ---: |
| 源记录数 | 191,166 | 191,166 |
| 总产量 | 916,929 | 916,929 |
| 聚合事实行 | - | 23,897 |

## 11. 性能结果

同一历史日期的实测结果：

| 接口 | 改造前远程查询 | 改造后本地快照 |
| --- | ---: | ---: |
| Flow 概览/详情 | 约 3.55-3.93 秒 | SO5-L5C 约 134ms |
| 产品概览 | 约 3.21 秒 | 约 112ms |
| 历史总览 | 未单独记录 | 约 93ms |

结果符合历史常用接口低于 500ms 的验收目标。

## 12. 测试与验收

### 12.1 自动测试

```text
317 passed
```

覆盖内容：

- 历史 Flow 默认选择本地快照；
- 工序描述、标准工时和产值；
- 产品四层结构和产值；
- 快照事务发布和版本递增；
- 历史总览读取持久化事实；
- 历史日期保留、只读和错误提示模板契约；
- 原有实时、历史、生产详情和看板回归测试。

### 12.2 静态检查

- Ruff：通过；
- Django system check：通过；
- `makemigrations --check --dry-run`：无遗漏迁移；
- JavaScript 语法：通过；
- `git diff --check`：通过。

### 12.3 真实数据验收

- `SO5-L5C` 历史员工数：24；
- Flow 工序与员工总产值公式错误：0；
- 产品工序产值公式错误：0；
- API 数据源：`local_snapshot`；
- 未回填日期首次 GET：HTTP 404 + 明确错误码，前端随后自动构建并重试；
- 可用历史日期：30。

### 12.4 浏览器验收

使用真实容器页面和真实历史 API 数据验证：

- URL 日期 `2026-07-15` 正确载入；
- “本地历史快照”状态可见；
- 员工明细正常渲染；
- 历史日期编辑按钮数量为 0；
- 切换到未回填日期后显示构建状态；构建失败才显示明确错误；
- 900px 视口下页面宽度保持 900px，没有页面级横向溢出。

## 13. 部署结果

- `DKT_iwork` 已使用最新镜像重建；
- `iwork.0004_historical_production_snapshots` 已应用；
- 三张历史表已创建；
- Nginx 配置检查和重载成功；
- 局域网入口返回正常认证重定向；
- iwork 容器内部接口返回 HTTP 200；
- 部署后日志没有新增业务错误。

统一重建脚本仍存在启动竞态：容器刚启动时立即执行内部 HTTP 检查，Uvicorn 可能尚未
监听而瞬时返回连接拒绝。服务稳定后的迁移、接口和日志检查全部通过。该竞态不影响
历史模块本身，但后续应给重建脚本增加轮询等待。

## 14. 文件职责变化

| 文件 | 变化 |
| --- | --- |
| `iwork/local_models.py` | 新增三张历史快照模型 |
| `iwork/history_store.py` | 新增快照读取、校验和事务发布模块 |
| `iwork/historical_queries.py` | 新增历史生产详情查询模块 |
| `iwork/local_queries.py` | 历史总览改读聚合事实 |
| `iwork/api_views.py` | 生产详情自动选择今日/历史数据源 |
| `iwork/api_views_local.py` | 历史总览只读快照，并提供按需确保快照接口 |
| `iwork/tasks.py` | 新增最近三天历史快照任务 |
| `iwork/celery.py` | 新增每日历史快照调度 |
| `snapshot_history.py` | 新增单日和日期范围回填命令 |
| `production_detail.html` | 自动回填、快照消息、历史目标隔离和隐藏实时更新时间 |
| `dashboard.html` | 自动加载历史快照并移除数据源切换和手动同步 |
| `start.sh` | 本地迁移失败时停止启动 |

## 15. 已知限制与后续建议

### 15.1 已知限制

- 历史快照是聚合事实，不能还原单张 `TicketNo` 原始票据；
- 历史员工效率尚未计算；
- 日期输入允许手工选择未回填日期，首次访问需要等待远程聚合和本地发布；
- 当前仅回填最近 30 天，更早日期需要按需回填；
- 重建脚本存在 Uvicorn 启动检查竞态；
- 产品映射依赖同步时 `production_orders` 的当前内容。

### 15.2 后续优先级

1. 增加班次日历和历史有效上班分钟，正式支持历史员工效率。
2. 将重建脚本内部 HTTP 检查改为带超时的轮询。
3. 根据业务需要回填更早日期，并监控本地表容量和索引效率。
4. 增加历史快照管理页面，展示版本、缺失元数据和失败原因。
5. 评估三年以上历史数据的月分区或归档策略。

## 16. 日常运维核对

查看历史快照状态：

```powershell
docker exec DKT_iwork python manage.py shell -c `
  "from iwork.local_models import HistoricalSyncState; print(list(HistoricalSyncState.objects.using('iwork_local').values('snapshot_date','status','snapshot_version','fact_row_count').order_by('-snapshot_date')[:10]))"
```

验证历史接口：

```text
http://192.168.30.190:8080/iwork/production/detail-data/?date=2026-07-15
http://192.168.30.190:8080/iwork/production/detail-data/flow/SO5-L5C/?date=2026-07-15
```

重新生成单日快照不会删除其他日期数据，只会事务替换指定日期并提升快照版本。

## 17. 历史加载与目标隔离二次完善

### 17.1 前端交互收敛

历史看板不再暴露“本地/远程”数据源切换，也不再提供“同步数据”或额外“加载数据”
按钮。进入历史页时默认选择曼谷业务日期的前一天；改变日期后立即加载本地快照。

历史生产详情继续使用原页面和日期参数，但历史日期不显示“最后更新（柬埔寨时间）”。
该字段仅对今日实时数据有意义，隐藏后可以避免用户误认为静态快照仍在持续刷新。

### 17.2 缺失快照自动回填协议

所有历史读取端点在快照缺失时统一返回：

```json
{
  "error": "该日期尚未生成本地历史快照",
  "code": "history_snapshot_not_found"
}
```

前端捕获该错误后调用：

```text
POST /api/history/snapshots/<date>/ensure/
```

页面内按日期共享构建 Promise，避免同一页面重复触发回填，也避免快速切换日期时复用
错误任务。后端使用 Redis `cache.add` 按日期原子抢占 15 分钟构建锁；已有任务时返回
HTTP 202 和 `history_snapshot_building`，前端按 `retry_after` 轮询。完成远程只读聚合
和本地原子发布后，前端重试原 GET。历史看板显示日期、快照版本和源记录数；生产详情
显示快照日期和版本。构建失败时清空旧日期统计并显示错误，不把旧数据或空列表当成
有效历史数据。历史看板还使用请求序号丢弃快速切换日期产生的过期响应。

旧接口 `POST /api/history/sync/<date>/` 已从 URL 路由删除。`mode=remote` 和
`mode=local` 不再属于历史接口契约；旧客户端即使继续传入，历史日期也固定读取本地
成功快照。

### 17.3 历史目标产量

历史 Flow 详情已经实现当日目标读取，不需要把目标复制进生产事实快照。目标来源为
本地表 `target_production`，数据库唯一键为：

```text
target_date + employee_id + workorder
```

- `workorder=''`：员工当日总目标；
- `workorder='<本厂款号>'`：员工在该本厂款号上的当日目标；
- 读取缓存键：`targets:<date>` 和 `wo_targets:<date>`；
- 历史页面只读，保存接口仍只允许当前业务日期的正常操作路径。

前端已删除 `localStorage` 目标兜底，避免浏览器旧值覆盖后端历史值。页面内部用于取消
编辑的临时目标键改为：

```text
日期 + 详情类型 + 详情键
```

自动测试使用同一员工、同一本厂款号在相邻日期写入不同目标，确认 2026-07-15 响应
只返回该日员工目标 `200` 和本厂款号目标 `150`，不会读取前一日的 `999/888`。

### 17.4 接口一致性修复

历史工序列表、工单分页和工单详情也加入成功快照检查。这样生产详情并发加载 Flow
概览与工单列表时，未回填日期的所有响应都会给出相同缺失信号，不会出现一部分接口
触发构建、另一部分接口提前返回空数据的情况。

今日 Flow 员工缓存命中路径的目标缓存键从未实际写入的
`targets:<date>:<flow>` 修正为统一的 `targets:<date>`，与保存接口和数据库回退保持一致。

### 17.5 本轮验证

- 完整 pytest：`317 passed`；
- 缺快照构建后读取：通过；
- 历史 GET 禁止远程模式绕过：通过；
- 相邻日期目标隔离：通过；
- 历史并发读取端点统一 404 契约：通过；
- 多客户端同日期构建锁、202 轮询和锁释放：通过；
- 历史看板快速切日期的任务隔离与过期响应保护：通过；
- 历史前端自动构建、移除旧按钮和隐藏更新时间模板契约：通过。
