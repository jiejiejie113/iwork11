# Workflow 映射与确认契约

## 固定路由

| 服务 | GitHub 仓库 | 固定分支 | CI | GHCR 发布 | 生产部署 | 生产环境 |
|---|---|---|---|---|---|---|
| iwork | `GuChenkano/iwork` | `Keycloak` | `ci.yml` | `release.yml` | `deploy-iwork.yml` | `production-iwork` |
| Portal | `GuChenkano/DTD_nginx` | `feature/keycloak-migration` | `ci.yml` | `release.yml` | `deploy-portal.yml` | `production-portal` |

仓库、分支和 Workflow 必须使用上表固定值，不接受用户提供的替代仓库或任意 Workflow
路径。若需要调整映射，应先修改和审查 Skill，而不是在单次调用中绕过。

## 前置证据

- CI 和发布均只针对固定远程分支当前完整 Commit SHA。
- 发布前必须存在同一 Commit 的成功 CI；发布 Workflow 也会再次验证。
- 部署前必须存在同一 Commit 的成功 CI 和发布，并使用发布得到的完整 GHCR Digest。
- Portal 部署 Workflow 还会验证同一 Commit 和两个 Digest 的成功 Runner smoke。
- iwork 的现有 Runner smoke 使用固定历史 Digest/Revision，不是当前分支的动态发布入口，
  Skill 不把它作为当前版本的通用 smoke 命令。

## 动作输入

### iwork 预检/部署

必需：

- `-Revision`：40 位小写 Commit SHA，必须等于远程 `Keycloak` HEAD。
- `-ImageDigest`：`sha256:` 加 64 位小写十六进制。
- `-ChangeDescription`：非空变更说明。

预检固定传递 `apply=false`、`rollback_drill=false`、`run_migrations=false`、
`confirmation=PREFLIGHT IWORK`。

部署确认预览返回：

- 无迁移：`DEPLOY IWORK <Revision>`
- 有迁移：`DEPLOY IWORK WITH MIGRATIONS <Revision>`

用户逐字确认后，Skill 向 Workflow 传递其原生确认词 `DEPLOY IWORK` 或
`DEPLOY IWORK WITH MIGRATIONS`。

### Portal 预检/部署

必需：

- `-Revision`：40 位小写 Commit SHA，必须等于远程
  `feature/keycloak-migration` HEAD。
- `-PortalDigest` 与 `-ProxyDigest`：两个完整 SHA-256 Digest。
- `-ChangeDescription`：非空变更说明。

预检固定关闭三种回滚演练开关，关联 Run ID 固定为 `none`，确认词为
`PREFLIGHT PORTAL`。

Portal 部署会同时影响认证入口，确认预览固定返回：

`DEPLOY PORTAL AND AUTHENTICATION <Revision>`

用户逐字确认后，Skill 向 Workflow 传递其原生确认词 `DEPLOY PORTAL`。

## 回滚边界

两个部署 Workflow 都会在部署失败时自动回滚；现有 `rollback_drill` 是受控演练，不是
“把当前生产版本手动回退到上一次部署”的通用入口。当前没有独立的手工回滚 Workflow，
而强 SHA 准入也禁止简单地用旧 Digest 冒充当前分支版本。因此 `rollback` 动作必须
失败关闭，不得映射成回滚演练或直接 SSH 执行服务器脚本。

## 状态边界

`production-status` 返回 GitHub Actions 侧最近的生产部署/预检证据，不声称等价于实时
Docker 健康状态。若用户需要实际容器状态，应另行执行获准的服务器只读检查，并把
Actions 证据与 Docker 结果分开汇报。

使用`-Wait`时，Run未以`completed / success`结束或`gh run watch`失败，脚本必须返回
非零退出码。触发与Run发现期间使用本机命名Mutex；若时间窗口内出现多个同分支、同Commit
的候选Run，脚本停止关联并要求人工核对，不能猜测最新Run就是本次触发，也不能自动重试。
