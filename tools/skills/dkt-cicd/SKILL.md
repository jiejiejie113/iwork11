---
name: dkt-cicd
description: 使用本机 GitHub CLI 安全查询、触发、监控并汇报 iwork 与 DITU Portal 的 GitHub Actions CI、GHCR 发布和受控生产部署。适用于用户询问这两个仓库的 CI/CD 状态或明确要求触发相应 Workflow；不负责实现部署逻辑、管理 GitHub 凭据或直接操作生产容器。
---

# DKT CI/CD

使用本 Skill 时，先根据用户意图选择服务和动作，再调用
`scripts/Invoke-DktCicd.ps1`。详细仓库、分支、Workflow 和确认契约见
[references/workflow-map.md](references/workflow-map.md)。

## 边界

- 复用当前 Windows 用户已登录的 `gh`；只检查登录是否可用，不读取或保存 Token、
  `.git-credentials`、Cookie、私钥或 `dkt-secrets.env`。
- Skill 只做参数校验、Workflow 触发、监控和结果汇报。构建、部署、数据库迁移、
  健康检查和自动回滚继续由版本化 Workflow 与服务器固定脚本执行。
- 查询状态和失败日志可直接执行。CI 与 GHCR 发布可在用户明确要求后直接触发，
  不需要生产确认。
- `deploy` 是生产变更。必须先不带 `-ApprovalText` 调用一次以生成确认预览，向用户
  展示服务、仓库、分支、Commit、Digest、环境、迁移开关和变更说明；只接受用户在
  看到本次预览后给出的精确确认词。预览状态与全部参数绑定、15分钟有效且只能消费一次；
  不得直接携带确认词跳过预览，也不得把更早的笼统授权视为本次确认。
- iwork `deploy` 还必须传入成功 `preflight` 返回的 `-PreflightRunId`（格式为
  `<workflow_run_id>-<run_attempt>`）。绑定的 Run 必须是同一 Commit、`completed/success`、
  `workflow_dispatch` 且其 `run-name`/标题包含 `request_id` 的 `apply=false` 预检；脚本会
  重新读取该 Run 的完整证据并逐项校验三个 Digest，缺少绑定或证据不符时拒绝部署。
- `preflight`与`deploy`会从同一Commit的成功Release日志重新提取Digest，并与输入逐项
  精确比较；仅格式正确但不属于该Release产物的Digest必须失败关闭。
- Portal 同时影响 Portal、oauth2-proxy 与认证入口，使用比 iwork 更强的确认词。
  Portal 普通预检和部署只传递 `capability_drill=false`；已移除的旧回滚演练、retry、recovery
  输入不得发送到 `deploy-portal.yml`。
- 不把 `queued`、`in_progress` 当作成功。仅 `status=completed` 且
  `conclusion=success` 才可报告成功。
- iwork 的 `ci`、`release`、`preflight` 和 `deploy` 触发时，脚本会为本次 dispatch
  生成独立 GUID `request_id`，并按 Workflow 的 `run-name` 包含该 ID 关联新 Run；
  `release` 会把已核验 CI Run 的 `ci_request_id` 传给 Release，`preflight`/`deploy`
  会把已核验 Release Run 的 `release_request_id` 传给生产 Workflow；上游关联 ID
  缺失、格式错误或不匹配时必须失败关闭。
  Portal 在对应Workflow完成同一输入契约前继续使用旧Run ID快照、Commit、事件和时间窗
  严格关联。两者的Run发现窗口均为120秒，截止前还会执行一次最终查询。
- Release 证据结果同时返回 `ImageDigest`、`ConfigDigest` 与 `ConfigArtifactDigest` 字段；iwork 发布
  必须严格得到唯一且完整的三个 Digest，预检和部署也必须逐项传入并匹配。Portal 的 `Digests` 仍按
  `dtd-nginx`、`dtd-oauth2-proxy` 顺序返回两个镜像 Digest，`ConfigArtifactDigest` 为空。失败 Run 的 Digest 字段
  可以为空，不应因此把 `production-status` 查询整体判错。

## 动作路由

| 用户意图 | 脚本动作 |
|---|---|
| 查看最近 Actions/CI 状态 | `status -WorkflowKind ci`；全部 Workflow 使用默认值 `all` |
| 查看某次失败日志 | `failed-log -RunId <id>` |
| 运行测试或纯 CI | `ci` |
| 构建并发布不可变 GHCR 镜像 | `release` |
| 仅拉取、复验生产候选镜像 | `preflight` |
| 部署到生产 | `deploy`，严格执行两段确认 |
| 查看生产交付证据 | `production-status` |
| 回滚上一次部署 | `rollback`，当前必须失败关闭并说明缺少独立手工回滚 Workflow |

默认添加 `-OutputJson`，以便稳定解析结果。需要等待运行结束时添加 `-Wait`。例如：

```powershell
& "$env:USERPROFILE\.agents\skills\dkt-cicd\scripts\Invoke-DktCicd.ps1" `
    -Action status -Service iwork -OutputJson
```

## 汇报

每次触发或查询后至少汇报：服务、Workflow、状态、结论、Commit、Run 链接和耗时。
GHCR 发布或部署还要汇报完整镜像、配置逻辑和配置 Artifact Digest；失败时列出失败 Job/Step，并仅按需展示已经脱敏的
失败日志。若脚本返回 `confirmation_required`，先向用户展示返回的预览和精确确认词，
不要自行补全或代替用户确认；超过15分钟或参数变化后必须重新生成预览。
