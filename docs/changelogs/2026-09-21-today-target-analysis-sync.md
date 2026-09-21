# 同步今日目标分时分析与历史查询（保留五状态与缅甸作息）

## 变更概览

- 从 `GuChenkano/iwork` 的 `Keycloak` 分支（`9306e62`）同步「今日目标分析」能力：
  70 号工序按早上、下午、晚上三个时段汇总实际产量，并给出时段目标、达成率与统一分析表。
- 保留本地已有能力：今日目标四/五状态完成判定（实际产量 + 18:30 下班时间）、缅甸
  `Asia/Yangon` 业务时区与工厂作息、前端 60 秒静默轮询和保存草稿保护。
- 分析时段按缅甸作息落地：早上 `07:30-11:30`、下午 `12:00-16:00`、晚上 `16:30-18:30`。

## 后端

- `iwork/settings.py`
  - 新增 `TARGET_ANALYSIS_STEP_NO`（复用 `ALLOWED_FLOWS_STEPNO=70`）、
    `TARGET_ANALYSIS_NORMAL_WORK_MINUTES=600`、`TARGET_ANALYSIS_PERIODS`（缅甸三段作息）。
  - `READ_MODEL_SCHEMA_VERSION` 由 `1` 升为 `2`；`target_analysis` 成为必需快照视图，
    旧 v1 快照在下一轮发布前不可读。
- `iwork/target_analysis.py`（新增）
  - 时段聚合、快照视图构建、按时段拆分目标与达成率计算。
  - 与远程实现的唯一有意偏差：`_normal_period_minutes()` 由「只分配早上/下午」泛化为
    「按早上→下午→晚上顺序分配，不超过各段时长」，否则 10 小时正常工时下晚上时段目标恒为 0。
- `iwork/historical_queries.py`
  - 新增 `get_target_analysis()`：从 `HistoricalProductionFact` 读取历史事实构建同一分析视图。
- `iwork/read_model/{builder,schemas,queries}.py`
  - 构建器写入 `target_analysis` 视图（使用 `source.facts` 原始小时事实）；
  - 快照校验新增视图名、结构与时段校验；
  - 查询门面新增 `target_analysis()`。
- `iwork/api_views_account.py`
  - 新增 `_today_target_analysis_metadata()`、`_load_target_analysis()`（当前业务日读实时快照，
    历史日期读本地历史快照状态与事实）；
  - `_today_target_payload()` 在保留 `production_state`、`actual_qty` 等五状态字段的基础上，
    追加 `analysis`、`target_date`、`is_late`、`submitted_by_username`；
  - `today_targets` 视图支持 `?date=YYYY-MM-DD`：过去业务日进入历史只读模式，
    不调用责任补生成逻辑，不查远程生产库；未来日期返回 `future_date_not_allowed`。

## 前端

- `iwork/templates/iwork/today_targets.html`
  - 新增「今日目标分析」表：合计行 + 展开三段明细，支持筛选、排序、状态筛选；
  - 历史只读模式：标题、提示条、禁用编辑、隐藏保存入口、历史快照 `ensure` 自动构建与重试；
  - 保留五状态统计卡片、快捷工时、保存全部与 60 秒静默轮询（历史日期自动停轮询）。
- `iwork/templates/iwork/_header.html`
  - 今日目标页主导航新增「查看日期」控件（与页面共用同一 Vue 应用）。

## 测试与文档

- 新增 `tests/test_target_analysis.py`；`tests/test_today_targets.py` 增加分析合并、历史读取、
  缺快照只读、未来/非法日期、分析不可用等用例。
- `tests/test_read_model_{store,queries,concurrency,fact_source}.py` 夹具补 `target_analysis`
  视图并改用版本常量。
- `docs/changelogs/2026-09-21-today-target-analysis-sync.md`（本文件）。

## 数据边界

- 目标最终值来自 `iwork_local.group_target_production`，责任状态来自
  `iwork_local.daily_target_obligation`。
- 历史分析只读取已发布的本地历史事实，不回查远程生产库；历史 GET 不创建责任记录、
  不刷新责任状态、不写入审计日志。
- 历史页面不暴露目标保存入口；主管理员既有历史修正 API 保持不变。

## 验证

- `pytest tests/ -q` 全量通过；`ruff check` 涉及文件通过。
- `READ_MODEL_SCHEMA_VERSION=2` 后需等待或触发一次快照发布，实时分析才显示可用；
  发布前页面显示「实时分析暂不可用」，其它实时页面在旧快照失效期间同样降级。
