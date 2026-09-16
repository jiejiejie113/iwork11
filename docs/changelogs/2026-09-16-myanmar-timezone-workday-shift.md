# 业务时区切换为缅甸（Asia/Yangon）与工厂作息调整

## 变更概览

- 业务时区基准由曼谷（`Asia/Bangkok`，UTC+7）切换为缅甸（`Asia/Yangon`，UTC+6:30）。
- 工厂作息由 07:00 开工、11:00-12:00 午休调整为缅甸作息：07:30 开工、午休 11:30-12:00、晚休 16:00-16:30、18:30 收工。
- 收工后有效工时按封顶 600 分钟返回（加班不计入员工效率）。

## 变更详情

### 1. 时区基准

- `iwork/settings.py`：`IWORK_BUSINESS_TIME_ZONE` 默认值改为 `Asia/Yangon`；`CELERY_TIMEZONE`、
  目标提交策略默认时区、业务日期、缓存 TTL、SSE 租约等均自动跟随该配置。
- `env/local.env`、`env/production.env`：显式声明 `IWORK_BUSINESS_TIME_ZONE=Asia/Yangon`（双保险）。
- `iwork/migrations/0014_alter_targetsubmissionpolicy_timezone_name.py`：同步
  `TargetSubmissionPolicy.timezone_name` 的模型默认值。
- `iwork/templates/iwork/today_targets.html`：截止时间格式化时区由 `Asia/Bangkok` 改为
  `Asia/Yangon`（dashboard/production_detail 此前已切换）。

### 2. 工厂作息与有效工时

- `iwork/settings.py` 新增 `WORKDAY_BREAK2_START_MINUTE=16:00`、`WORKDAY_BREAK2_END_MINUTE=16:30`、
  `WORKDAY_END_MINUTE=18:30`；`WORKDAY_START_MINUTE=07:30`、午休改为 11:30-12:00。
- `iwork/statistics.py` `get_effective_work_minutes` 重写：支持两段休息（午休 + 晚休），
  18:30 后封顶返回 600 分钟；07:30 前返回 `None`；历史日期返回 `None`。
- 全天有效工时 07:30-18:30 扣除 1 小时休息 = 600 分钟，与默认目标工时
  `IWORK_TARGET_DEFAULT_WORK_HOURS=10.0` 一致。

### 3. 测试与文档

- 测试统一替换为 `Asia/Yangon`；`tests/test_statistics.py` 边界用例按新作息重写
  （07:29→None、07:30→0、11:30→240、16:00→480、18:30→600、19:00→600 等）。
- `docs/开发文档/iwork规范手册.md` 第 5 节、`docs/开发文档/API接口文档.md`、
  `docs/部署文档/API接口清单.md`、`CLAUDE.md` 同步更新。

### 4. 存量数据更新（人工运维执行）

```sql
UPDATE target_submission_policy
SET timezone_name = 'Asia/Yangon'
WHERE timezone_name = 'Asia/Bangkok';
```

`daily_target_obligation.deadline_at` 为已冻结的历史时刻，不随策略变更回改；未更新策略
记录前，未来义务的截止时间仍按曼谷 09:00（UTC 02:00）计算，比缅甸 09:00（UTC 02:30）早 30 分钟。

## 验证结果

- `pytest tests/ -q`：693 passed。
- `ruff check` 涉及的后端与测试文件：All checks passed。
- `python manage.py makemigrations iwork --check --dry-run`：无未生成迁移。
- 说明：Django `TIME_ZONE` 保持 `UTC` 不变，远程 `payroll` 库字面时间比较契约不受影响；
  历史快照的 `registered_date/registered_time` 为 UTC 字面存储，同样不受业务时区切换影响。
