# 管理员当日责任摘要通知与点击详情

## 背景

既有`target_submission_overdue`只在责任逾期时逐生产组发一条通知，管理员无法一眼看到当日责任全貌。本次新增管理员每日责任摘要：只要当日存在未填写（待提交或已逾期）责任，就生成一条聚合摘要通知，点击通知可弹出当日责任明细，便于管理员快速跟进。

## 每日责任摘要规则

- 新增内置规则`daily_responsibility_summary`（管理员强制接收、无Flow范围）。
- 新增`evaluate_daily_responsibility_summary(business_date)`：按业务日汇总全部责任状态计数，`pending/overdue`视为未填写；生成或更新唯一摘要事件（按`rule + business_date + "daily"`去重）。
- 事件消息如“今日 N 个生产组未填写目标，其中 M 个已逾期。”；`payload`携带结构化明细：`type=daily_summary`、`status_counts`与`flows`（分组、状态、截止时间、负责人）。
- 全部填写或豁免后事件转为`recovered`并重新投递；再次出现未填写时恢复`open`并递增修订号。
- 每分钟补偿任务`reconcile_target_obligations_task`在逾期评估后追加摘要评估，返回`summary_count`。
- 通知列表序列化增加`payload`字段，供前端详情弹窗使用；SSE仍只发通用唤醒，不携带业务数据。

## 前端：通知详情弹窗

- `_header.html`新增隐藏模态：深色遮罩 + 面板，标题栏带关闭按钮，内容区渲染详情。
- 点击`daily_summary`类型通知卡片时弹出模态，展示状态计数（待提交/已逾期/已完成/逾期补交/已豁免）与明细表格（分组、状态、截止时间（UTC+7）、负责人），截止时间按曼谷时区格式化。
- 关闭方式：关闭按钮、点击遮罩外区域、Esc键；未读卡片点击时同时标记已读。

## 部署修复：静态文件与CSRF

验收过程中发现站内通知前端此前无法在本环境正常工作，两个部署缺陷一并修复：

- **静态文件路由**：`STATIC_URL`改为`/iwork/static/`（staticfiles会把相对值规范化为根绝对路径，子路径部署下必须显式携带前缀），并在`urls.py`增加`/static/`服务路由（uvicorn不提供runserver式静态服务），通知脚本现可通过完整代理链加载。
- **CSRF Origin校验**：Django 5.2对非HTTPS POST校验Origin，nginx转发Host不带端口导致通知已读等POST被403拒绝；新增`CSRF_TRUSTED_ORIGINS`（默认含`http://192.168.30.190:8080`与`http://localhost:8080`，可用环境变量覆盖）。

## 测试与验收

- 新增每日摘要规则测试：事件生成与明细、去重、全填恢复、无未填不产生、恢复后重开。
- 新增通知列表payload序列化、STATIC_URL前缀、静态路由可访问、CSRF信任源配置测试。
- 全量pytest 534项通过、Ruff通过、JavaScript语法检查通过。
- 浏览器验收（临时管理员+过去业务日数据）：抽屉显示每日责任摘要；点击弹出详情模态（状态计数+明细表）；未读数同步减少；关闭按钮/遮罩/Esc关闭均生效；验收数据与临时账号已精确清理。

不推送远程、不部署服务器。
