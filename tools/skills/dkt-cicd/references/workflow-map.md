# Workflow 映射与确认契约

## 固定路由

| 服务 | GitHub 仓库 | 固定分支 | CI | GHCR 发布 | 生产部署 | 生产环境 |
|---|---|---|---|---|---|---|
| iwork | `jiejiejie113/iwork11` | `Keycloak` | `ci.yml` | `release.yml` | `deploy-iwork.yml` | `production-iwork` |
| Portal | `jiejiejie113/DTD_nginx` | `feature/keycloak-migration` | `ci.yml` | `release.yml` | `deploy-portal.yml` | `production-portal` |

仓库、分支和 Workflow 必须使用上表固定值，不接受用户提供的替代仓库或任意 Workflow
路径。若需要调整映射，应先修改和审查 Skill，而不是在单次调用中绕过。

## 前置证据

- CI 和发布均只针对固定远程分支当前完整 Commit SHA。
- 发布前必须存在同一 Commit 的成功 CI；发布 Workflow 也会再次验证。
- 部署前必须存在同一 Commit 的成功 CI 和发布，并使用发布得到的完整镜像 Digest 与配置包 Digest。
- 预检和部署会读取同一Commit的成功Release日志并重新提取Digest；输入Digest必须逐项
  完全一致，不能只通过格式校验。
- Portal 部署 Workflow 还会验证同一 Commit 和两个 Digest 的成功 Runner smoke。
- iwork 的现有 Runner smoke 使用固定历史 Digest/Revision，不是当前分支的动态发布入口，
  Skill 不把它作为当前版本的通用 smoke 命令。

## 动作输入

### iwork 发布、预检/部署

`publish` 是完整发版编排：针对固定分支当前 Commit 生成新的 `ci_request_id`，触发并
等待本次 `ci.yml` 成功，再以该 ID 作为 `ci_request_id` 触发 `release.yml`。它只返回本次
CI 与 Release 的 Run、request_id 和发布证据；CI 失败、Run 歧义或证据读取失败时不得触发
Release。

`release` 是底层重试入口，iwork 必须显式提供 `-CiRequestId`。脚本只接受同一 Commit、
`workflow_dispatch`、`completed/success` 且唯一匹配该 request_id 的 CI Run；不再猜测最新
成功 CI。CI 成功而 Release 失败时，只能重试 Release，不得改用其他 Commit 或旧 Run。

必需：

- `-Revision`：40 位小写 Commit SHA，必须等于远程 `Keycloak` HEAD。
- `-ImageDigest`：`sha256:` 加 64 位小写十六进制。
- `-ConfigDigest`：同一 Release 生成的生产配置包逻辑 Digest。
- `-ConfigArtifactDigest`：同一 Release 上传的 GitHub 配置 Artifact 存储 Digest。
- `-ChangeDescription`：非空变更说明。

预检固定传递 `apply=false`、`rollback_drill=false`、`run_migrations=false`、
`confirmation=PREFLIGHT IWORK`。当前迁移策略为永久失败关闭的 `disabled-v1`：在形成
机器可验证的向后兼容变更集合、隔离数据库结果和前后版本证明前，任何
`run_migrations=true` 都必须在 Docker 调用前拒绝，不提供“有迁移”的确认路径。

正式部署必须传入成功预检返回的 `-PreflightRunId`，格式为
`<workflow_run_id>-<run_attempt>`。该 Run 必须是同一 Commit 的
`completed/success`、`workflow_dispatch` 运行，且 Run 名称/标题含有本次 `request_id`；
它只能来自 `apply=false` 的 iwork 预检，脚本会重新读取其完整三类 Digest 并逐项比对当前
输入，任何绑定缺失、运行状态不符或证据不一致都失败关闭。

部署确认预览仅返回无迁移路径：

`DEPLOY IWORK <Revision>`

用户逐字确认后，Skill 向 Workflow 传递原生确认词 `DEPLOY IWORK`；任何迁移确认词或
`run_migrations=true` 都失败关闭。确认前必须先生成参数绑定的本地预览状态；该状态15分钟
有效、单次消费，参数变化或直接携带确认词都将失败关闭。

### Portal 预检/部署

必需：

- `-Revision`：40 位小写 Commit SHA，必须等于远程
  `feature/keycloak-migration` HEAD。
- `-PortalDigest` 与 `-ProxyDigest`：两个完整 SHA-256 Digest。
- `-ChangeDescription`：非空变更说明。

预检和普通部署固定关闭 `capability_drill`，不传递已从 Portal Workflow 移除的旧
`rollback_drill`、retry 或 recovery 字段；确认词为 `PREFLIGHT PORTAL`。

Portal 部署会同时影响认证入口，确认预览固定返回：

`DEPLOY PORTAL AND AUTHENTICATION <Revision>`

用户逐字确认后，Skill 向 Workflow 传递其原生确认词 `DEPLOY PORTAL`。
Portal同样要求先生成15分钟有效的单次预览状态，不能复用其他Commit、Digest或变更说明
对应的确认。

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
非零退出码。iwork 的`ci`、`publish`、`release`、`preflight`和`deploy`每次 dispatch 都会生成
独立GUID `request_id`并传给Workflow；其中`publish`即使未提供`-Wait`也会强制等待本次CI
成功后才触发Release。脚本只关联`run-name`包含该ID的新Run。Portal
在其Workflow完成同一输入契约前，继续按触发前Run ID快照、Commit、事件和时间窗关联。
Run发现窗口为120秒，截止前会执行一次最终查询；触发与Run发现期间使用本机命名Mutex。
若窗口内出现多个候选Run，脚本停止关联并要求人工核对，不能猜测最新Run就是本次触发，
也不能自动重试。

iwork 的四类 Workflow 使用独立 `request_id`：Release 还必须接收并核验上游 CI 的
`ci_request_id`，Preflight/Deploy 还必须接收并核验上游 Release 的 `release_request_id`。
这些上游 ID 只能从已核验 Run 的 `displayTitle` 提取，不能用平台 Run ID 或“最新成功”替代。

Release 证据输出包含 `ImageDigest`、`ConfigDigest` 与 `ConfigArtifactDigest` 字段，同时保留兼容的
`Digests`数组。iwork 成功 Release 必须从日志解析出唯一完整的镜像、配置逻辑和配置 Artifact
Digest；预检与部署将三个值逐项传入并与同一 Release 证据匹配。Portal 仍必须分别解析
`dtd-nginx` 和 `dtd-oauth2-proxy` 两个唯一 Digest，`ConfigArtifactDigest` 保持为空。失败 Run
可返回空 Digest 字段，`production-status`不会因失败 Run 没有发布证据而整体失败。
