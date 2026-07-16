# ADR-006: 本地历史生产快照

**状态**: 已采纳（2026-07-16）

## 背景

远程 `payroll.pytckreg3` 已超过三千万行，单个生产日约十五万至十九万条记录。
历史生产详情直接查询远程库通常需要三至四秒，并持续增加远程库聚合压力。
原设计中的 `iwork_local.pytckreg3` 是 `managed=False` 模型，部署环境没有对应表，
且其单字段主键不能正确表达远程表的组合主键。

## 决策

历史日期使用本地聚合快照，不复制全部原始票据。

- `historical_production_fact` 按日期、小时、Flow、工位、员工、本厂款号和工序聚合产量。
- `historical_step_snapshot` 冻结当天工序描述、标准工时和产品映射。
- `historical_sync_state` 记录快照版本、源记录数、源总产量、事实行数和元数据完整性。
- 今日生产详情继续读取 Redis；早于曼谷业务日期的请求只读取本地成功快照。
- 历史接口不接受数据源切换，旧客户端传入的 `mode` 参数会被忽略。
- 缺少快照时，历史 GET 返回 `history_snapshot_not_found`；前端自动请求确保快照接口，
  后端从远程只读源回填，发布成功后前端重试原 GET。

历史派生字段从冻结输入计算：工序产值为 `qty * step_time`；缺少标准工时返回空值，
标准工时为零时产值为零。历史员工效率继续返回空值，直到班次日历定义历史有效上班分钟。

## 发布规则

快照按日期事务替换，校验源记录数和总产量后才标记为成功。Celery 每天曼谷时间
02:00 重建最近三个已结束日期，以覆盖迟到或修正数据。普通请求只读取成功快照，
不会在 GET 中触发远程查询。按需回填必须通过显式 POST：

```text
POST /api/history/snapshots/<date>/ensure/
```

已有成功快照时该接口直接返回现有版本，不重复构建。
同一日期通过 Redis 原子构建锁互斥；已有客户端正在构建时返回 HTTP 202，前端按响应中
的 `retry_after` 轮询，避免重复扫描远程大表。

历史目标产量不写入生产事实快照。目标继续从本地 `target_production` 读取，隔离键为
`target_date + employee_id + workorder`，因此同一员工相邻日期的目标不会串用。历史页面
只读后端返回的当日目标，不使用浏览器缓存兜底。

## 运维接口

```powershell
python manage.py snapshot_history --date 2026-07-15
python manage.py snapshot_history --start 2026-07-01 --end 2026-07-15 --continue-on-error
```

历史生产详情通过现有 URL 加日期参数访问：

```text
/production/detail-data/?date=2026-07-15
/production/detail-data/flow/SO5-L5C/?date=2026-07-15
```

## 影响

样本日从 191,165 条原始记录压缩到约 23,897 条事实记录。历史查询不再依赖远程库，
但部署后必须先执行迁移并回填日期，未发布日期不会被当成有效历史数据。
