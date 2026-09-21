# CI/CD 绑定迁移：GuChenkano → jiejiejie113

## 背景

本地业务线（`local-sync-b7b7b76`，含今日目标四/五状态与分时分析同步）与
`GuChenkano/iwork` 的 CI/CD 机制线历史分叉；合并成本高。而本地 HEAD 是
`jiejiejie113/iwork11` 的 `Keycloak` 分支的快进后继（0 behind / 43 ahead）。

经用户确认：保留受控发布机制，只更换仓库归属，分支名继续使用 `Keycloak`。

## 新绑定

| 项 | 旧值 | 新值 |
|----|------|------|
| iwork 仓库 | `GuChenkano/iwork` | `jiejiejie113/iwork11` |
| 部署分支 | `Keycloak` | `Keycloak`（不变） |
| 触发 actor | `GuChenkano` | `jiejiejie113` |
| 镜像 | `ghcr.io/guchenkano/iwork` | `ghcr.io/jiejiejie113/iwork11` |
| Portal 仓库 | `GuChenkano/DTD_nginx` | `jiejiejie113/DTD_nginx` |

## 变更范围（本仓库）

- `.github/workflows/{ci,release,deploy-iwork,runner-smoke}.yml`：仓库/actor 守卫、
  镜像名、跨仓库协调 `repository`。
- `scripts/Install-GitHubProductionRunner.ps1`、`Install-IworkProductionDeployment.ps1`、
  `Invoke-IworkProductionDeployment.ps1`、`ProductionCoordination.psm1`：安装器与协调模块绑定。
- `tests/test_ci_workflow.py`、`test_production_config_bundle.py`、
  `test_production_deployment_stage4.py`、`test_production_runner_stage3.py`：断言同步。
- `tools/skills/dkt-cicd/**`：工作流映射、Digest 正则、夹具与断言。
- 文档：总方案新增第 15 节；`AGENTS.md`、Owner/ACL 规范、规范手册与历史方案标注迁移。

## 待办（未完成前不得切换生产）

1. 创建 `jiejiejie113/DTD_nginx` 并完成 Portal 侧同等迁移。
2. `jiejiejie113` 确认 `ghcr.io/jiejiejie113/iwork11` 包写权限与 Runner 注册权限。
3. 新 Windows Server 安装 iwork/Portal Runner（身份默认 `DONGMING\shuju`，不一致时显式传入）。
4. 重装生产准入策略并固定新的仓库/分支/actor/Workflow/SHA-256。
5. 新仓库首次 CI→Release 成功后，刷新 `runner-smoke.yml` 的固定 Digest 与 `EXPECTED_REVISION`。
6. 基础设施（MySQL/Redis/Keycloak/Portal）需与 iwork 同 Docker 主机或同网络。
7. 中央密钥仍为服务器 `D:\DM\dkt-secrets.env`，不得进入仓库或镜像。

## 验证

- `pytest tests/ -q` 全量通过。
- 代码与脚本中不得再有 `GuChenkano`/`guchenkano` 绑定残留（历史文档与 Run 链接除外）。
