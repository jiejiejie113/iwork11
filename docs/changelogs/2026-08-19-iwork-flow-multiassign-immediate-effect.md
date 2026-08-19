# iwork Flow分配立即生效与责任即时生成

## 背景

Portal 管理页分配 Flow 存在三项与后端相关的缺陷：分配默认受"过截止时间顺延到下一工作日"逻辑影响、当日不生效；责任只在被查询时才补偿生成，且组长快照在责任创建后冻结，后分配的组长看不到当日责任；已豁免的责任在 Flow 重新分配组长后仍停留在"已豁免"。配合 Portal 管理页多选分配改造（见 DTD_nginx 同名 changelog），本次让分配当日立即生效、责任即时生成。

## 变更

- `iwork/api_views_account.py` `flow_assignments` PUT：
  - 移除"当日已过截止时间则把 `effective_date` 顺延到下一工作日"的规则，分配在生效日期当日立即生效。
  - `effective_date` 变为可选：缺省取分配时业务日（`get_business_date()`）；显式传入仍按传入值，接口向后兼容。
  - 保存成功后，对已开始的生效日期（`effective_date <= 业务日`）调用 `ensure_daily_target_obligations`，当日责任即时生成，过截止时间的直接为逾期。
  - 清理不再使用的 `timezone`、`deadline_for_date`、`next_business_date` 导入。
- `iwork/target_responsibility.py`：
  - 新增 `_sync_obligation_leaders(obligation, leaders)`：`ensure_daily_target_obligations` 现在会把当日仍有效的组长追加进责任快照（只追加、不删除已冻结的历史负责人），替代原先仅创建时写入快照的行为。
  - 已豁免（WAIVED）责任在该 Flow 重新出现有效组长且当日无提交时恢复为待提交或逾期（按当前时刻与截止时间判断），写入 `obligation_revived` 审计日志（actor 记为 `system`）。
- 测试（`tests/test_identity_and_targets.py`）：
  - `test_assignment_created_after_deadline_starts_next_business_day` 反转为 `test_assignment_after_deadline_takes_effect_same_day_as_overdue`：截止后分配当日生效、响应 `effective_date` 保持分配日、当日责任直接生成且状态为逾期、新组长在快照中。
  - 新增 `test_assignment_without_effective_date_defaults_to_business_date`：缺省 `effective_date` 取当前业务日。
  - `test_generated_obligation_freezes_leader_snapshot_and_deadline` 更名为 `test_generated_obligation_freezes_deadline_and_appends_new_leaders`：截止时间仍冻结，但当日新增的有效组长会追加进快照（原断言快照完全冻结已不符合新需求）。
  - 新增 `test_waived_obligation_revives_when_leader_reassigned`：豁免后重新分配组长，责任恢复待提交、`waived_at` 清空、快照包含新旧组长。

## 明确不变

- 移除分配时 `waive_unfinished_obligations` 语义不变：截止前移除最后一名组长豁免未完成责任；截止后保留为逾期历史事实，快照不删除。
- 责任截止时间与策略（`TargetSubmissionPolicy`）计算逻辑不变。

## 验证

- iwork 全量 525 项测试通过（较上一提交净增 2 项行为用例）、Ruff 通过。
- `Rebuild-Local.ps1 -Target iwork` 退出 0，容器健康。
- 浏览器联调（Portal 管理页多选 3 个 Flow 分配给 test002）：分配当日生效、今日责任立即出现 3 条逾期、移除分配后逾期责任按设计保留为历史事实；验收数据已精确清理。
