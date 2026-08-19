# account-admin flows 端点与责任测试确定性修复

## 背景

Portal 管理页重构需要 Flow 候选清单（datalist 建议），iwork 的 `VISIBLE_FLOWS` 是权威来源，此前未对外暴露。同时发现三个既有测试硬编码日期或依赖真实时钟，跨日/跨过 09:00 截止时间后必然失败。

## 变更

- 新增 `GET /api/account-admin/flows/`（`iwork/urls.py`、`iwork/api_views_account.py`），返回 `{'flows': settings.VISIBLE_FLOWS}`，要求管理员身份，与其余 account-admin 接口一致。
- 测试修复（`tests/test_identity_and_targets.py`）：
  - `test_late_submission_preserves_overdue_fact`：业务日期改为动态 `get_business_date()`。
  - `test_any_active_leader_can_complete_a_daily_obligation`：注入固定的截止前时刻，避免 09:00 后运行被判为逾期补交。
  - `test_assignment_date_change_waives_future_unfinished_obligation`：同样注入固定时刻，避免责任先被创建为 overdue 导致豁免断言失败。
- 新增 flows 端点测试：管理员 200 且返回配置清单、非管理员 403。

## 验证

- iwork 全量 520 项测试通过，Ruff 通过。
- `Rebuild-Local.ps1 -Target iwork` 退出 0，容器 healthy。
