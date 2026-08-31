# iwork CI/CD 最终修改方案（阶段8后续改造设计）

> 本文是阶段8后的改造设计与实施入口，不替代唯一进度基线
> C:/Users/lipengfei/ZCodeProject/iwork/docs/2026-08-21-GitHub-Actions-CICD完整实施方案.md。
> 每个切片必须在同一提交中回写总方案的阶段状态、Commit、Actions、测试、偏差和下一入口。
> 本文是方案与实施入口；当前工作树已实现其中部分切片并完成隔离验收，但尚未推送本轮
> Commit、配置生产签名材料或执行新的真实 Release/准入/生产切换。任何“已完成”仅指下文
> 明确列出的本地代码与测试证据，不代表生产环境已经实施。

> 制定日期：2026-08-31
> 适用仓库：`GuChenkano/iwork`
> 固定分支：`Keycloak`
> 当前基线：`69baafa`（本轮实现已提交，待真实 CI 验证）

## 1. 方案目标

本方案在保留现有生产安全边界的前提下，解决以下问题：

- 普通代码推送会立即触发完整CI，浪费运行时间和资源。
- CI构建的临时镜像与Release重新构建的镜像不是同一个产物。
- Release、Deploy和Skill多次查询、拼接相同证据，流程过于复杂。
- GHCR查询异常可能被错误解释为“镜像不存在”。
- 部署成功标准没有自动覆盖外部HTTPS、OIDC、SSE和关键业务接口。
- 数据库迁移后的“自动回滚”边界表述不够准确。
- Runner smoke、回滚演练和日常部署职责混杂。

最终保留的审核与授权模型为：

```text
AI审核代码、配置、迁移和CI/CD风险
  → Skill显式触发CI
  → Release生成不可变产物和证据
  → 生产Preflight
  → AI汇总证据并展示部署预览
  → 用户输入一次性精确确认词
  → Workflow和服务器执行确定性门禁
  → 正式部署及外部业务验收
```

AI负责技术审核和风险说明，用户负责最终生产授权。用户确认不能替代Commit、Digest、身份、预检、锁和健康检查等确定性安全门禁。

## 2. 最终触发规则

完整 CI 只由 `workflow_dispatch` 触发；普通 Push 不触发完整 CI，但保留独立的轻量 PR/Push 检查。
发版的正常编排由 `dkt-cicd` Skill 提供，Workflow 和服务器准入仍是实际安全边界。

| 用户指令 | Git操作 | CI | Release | Preflight/Deploy |
|---|---|---|---|---|
| “提交代码” | Commit；是否Push按用户指令 | 不触发 | 不触发 | 不触发 |
| “提交并发版” | Commit并Push到`Keycloak` | Skill触发 | CI成功后由Skill触发 | 不自动进入生产 |
| “发版当前版本” | 使用远程`Keycloak` HEAD | Skill触发 | CI成功后由Skill触发 | 不自动进入生产 |
| “只运行CI” | 不要求Release | Skill触发 | 不触发 | 不触发 |
| “预检当前版本” | 必须已有匹配Release | 不重复触发 | 不重复触发 | 只运行`apply=false` |
| “部署当前版本” | 必须已有成功Preflight | 不重复触发 | 不重复触发 | 展示预览并等待用户确认 |
| 普通手工Push | 正常推送 | 不触发完整CI；可有轻量检查 | 不触发 | 不触发 |
| “只发布已有CI” | 使用明确的CI Run及request_id | 不重复触发 | Skill触发 | 不自动进入生产 |
| PR或普通Push轻量检查 | 不涉及生产 | 只运行轻量检查 | 不触发 | 不触发 |
“提交并发版”和“发版当前版本”统一映射到 Skill 的高层 `publish` 动作：
`publish` 先生成新的 ci_request_id、触发并等待本次 CI，再把已核验的 CI Run 传给 Release。
底层 `release` 仍可单独消费显式 CI 证据，便于 CI 成功而 Release 失败时安全重试；Release 成功后只输出 Preflight 参数。

### 2.1 不使用Commit Message作为GitHub触发器

补充约束：完整发布链路的唯一正常编排入口是 Skill，但这不是授权边界。
GitHub UI、gh CLI 或其他自动化仍可能直接触发 Workflow，因此每个 Workflow 仍必须独立
校验仓库、分支、事件、actor、Commit、request_id、Release Manifest、Digest、服务器脚本
哈希和锁。AI审核只提供风险判断与人工说明，不能替代这些确定性门禁。

禁止保留`on: push`后再通过以下条件判断是否发版：

```yaml
if: contains(github.event.head_commit.message, '[RELEASE]')
```

这种写法仍会为每次Push创建Workflow Run，只是让Job显示为Skipped，不能真正实现“普通Push不触发CI”。

用户对AI明确说“提交并发版”时，AI在完成Commit和Push后调用Skill。手工Commit Message即使包含`[RELEASE]`，如果没有调用Skill，也不会自动触发CI或Release。

## 3. 目标流水线

```text
用户明确要求发版
  → AI检查工作树、Commit差异和高风险文件
  → 确认远程Keycloak HEAD等于目标Commit
  → Skill生成ci_request_id并触发CI
  → CI完成代码、迁移和配置检查
  → Skill唯一关联本次CI Run
  → Skill生成release_request_id并触发Release
  → Release只构建一次镜像并发布同一产物
  → 生成Release Manifest和三类Digest
  → Release完成并输出绑定参数，等待用户明确要求后触发apply=false Preflight
  → AI展示完整部署预览和风险结论
  → 用户输入精确确认词
  → Skill触发正式Deploy
  → 固定服务器脚本成对切换iwork和alert-worker
  → 外部HTTPS/OIDC/SSE/业务探针
  → 写入成功收据或执行应用级自动回滚
```

## 4. CI修改方案

修改`.github/workflows/ci.yml`。

### 4.1 触发器

完整 `ci.yml` 删除 `push` 和 `pull_request` 触发，只保留手工的完整 CI：

```yaml
on:
  workflow_dispatch:
    inputs:
      request_id:
        description: 本次触发的唯一关联ID
        required: true
        type: string
```

运行名称固定包含本次请求和Commit：

```yaml
run-name: >-
  iwork ci · ${{ inputs.request_id }} · ${{ github.sha }}
```

并发规则改为按完整 Commit 串行且不自动取消：

```yaml
concurrency:
  group: iwork-ci-${{ github.sha }}
  cancel-in-progress: false
```

显式发版CI不得因另一次请求而被静默取消；重复触发由Skill本机Mutex、唯一`request_id`和Run唯一匹配共同控制。

同时新增无生产权限的 `ci-pr.yml`（或等价的轻量 Workflow），按 PR 触发，并可按仓库实际协作方式保留 Keycloak 的轻量 Push 检查。
它只执行 Ruff、迁移一致性、单元测试和 Workflow/YAML/PowerShell 契约，不构建或推送镜像，不读取生产密钥，不调用部署 Workflow。
如果仓库完全不采用 PR，至少保留该轻量 Push 检查；不能在没有分支保护的情况下让 `Keycloak` 完全失去自动反馈。

### 4.2 CI职责

保留：

- Python 3.11环境。
- Ruff检查。
- `makemigrations --check --dry-run`。
- 隔离pytest。
- PowerShell脚本行为测试。
- Compose配置解析。
- 固定完整SHA的GitHub Actions。
- `persist-credentials: false`。
- 占位测试密钥和隔离测试设置。

删除CI中的临时完整Docker镜像构建。CI只验证代码、迁移和配置；生产候选镜像在Release阶段构建一次、验证后原样发布。

CI摘要必须记录：Commit、`request_id`、触发账号、各检查结果和Run URL。

## 5. Release修改方案

修改`.github/workflows/release.yml`、`Dockerfile`和生产依赖文件。

### 5.1 固定构建输入

- 将`python:3.11-slim`固定到完整镜像Digest。
- 新增锁定版本的生产依赖文件，例如`requirements.lock`。
- 测试工具、PyInstaller和桌面GUI依赖移出生产镜像依赖。
- 保持镜像内非root运行方式。
- 构建过程中不读取生产密钥，不使用生产密钥作为Build Arg、环境变量或构建上下文。

### 5.2 单次构建和原样发布

Release固定执行：

```text
验证唯一成功CI
  → docker build一次
  → 对本地镜像执行容器级Smoke
  → push同一个本地镜像
  → 按远程Digest拉取并复验OCI revision
```

禁止“CI构建一次、Release重新构建一次”，也禁止通过重新构建覆盖已存在的SHA标签。
> 对不存在的 Commit SHA 标签，严格执行“一次构建→本地 Smoke→推送→Digest 复验”。
> 对已存在的 SHA 标签不重新构建，只在远程 Digest、OCI source/revision、对应 Release Manifest
> 和可信 Artifact 证据全部一致时复用；任一证据缺失或不一致都失败关闭。Smoke 必须在推送前
> 使用隔离配置和隔离存储完成，不能连接生产数据库、Redis 或中央密钥。

### 5.3 GHCR错误分类

远程镜像查询必须区分：

- 明确404：允许创建新SHA标签。
- 401/403：立即失败。
- 网络错误、超时、限流和5xx：立即失败。
- 标签已存在但Digest或来源不一致：立即失败。

生产部署继续只使用完整Digest，不使用`latest`。如GHCR支持，应开启SHA标签不可变策略。

### 5.4 Release Manifest

Release生成独立、不可变的`release-manifest.json`：

```json
{
  "schema": "iwork-release/v1",
  "repository": "GuChenkano/iwork",
  "branch": "Keycloak",
  "commit": "完整40位SHA",
  "ci_run_id": "CI Run ID",
  "ci_request_id": "CI request_id",
  "release_run_id": "Release Run ID",
  "release_request_id": "Release request_id",
  "image_digest": "sha256:...",
  "config_digest": "sha256:...",
  "config_artifact_name": "iwork-production-config-<commit>",
  "config_artifact_id": "GitHub Artifact ID",
  "config_artifact_digest": "sha256:...",
  "manifest_artifact_name": "iwork-release-manifest-<commit>",
  "mechanism_id": "认证后的机制指纹",
  "risk_envelope": "风险分类",
  "migration_policy_id": "迁移策略标识",
  "created_at": "带时区时间"
}
```

Manifest与生产配置 Artifact 作为两个独立对象保存。Deploy只消费这份Manifest及其明确引用的
配置 Artifact，不再分别从多个日志中猜测和拼接CI、Release和Digest证据。Manifest本体不写入
自己的Artifact ID或Artifact digest；这两个字段属于上传后外部信任锚，必须与指定Release Run
的Artifact元数据一致。生产最低要求是 Release Run、Artifact ID、Artifact digest 和受保护服务器
副本四者一致。

Manifest签名是强制门禁：Release使用受保护的
`IWORK_RELEASE_MANIFEST_SIGNING_PRIVATE_KEY_PEM`和Key ID生成RSA
`RSASSA-PKCS1-v1_5-SHA256`签名，Deploy使用受保护的验证证书和同一Key ID验证；私钥不进入日志、
Artifact或服务器状态。签名失败、Key ID不匹配、证书缺失或轮换未完成均失败关闭，不能人工把证据
改回有效。签名密钥轮换必须先发布新的验证证书/Key ID并完成独立校验，再切换Release端私钥，
旧Key的证书在保留期内只用于审计，不得让已撤销证书重新变为有效。

> Manifest采用两个不可变对象的两阶段发布，禁止自引用：
> 1. 先上传只包含 config-manifest.json、Compose 和 production.env 的配置 Artifact，取得其
>    artifact id、name 和 digest；该 digest 不写回配置 Artifact 自身。
> 2. 再生成单独的 release-manifest.json，写入配置 Artifact 的 id/name/digest、镜像 Digest、
>    Config Digest、Commit、CI/Release Run ID 与 attempt、request_id、Workflow path、ref、
>    mechanism_id、risk_envelope 和 migration_policy_id；随后单独上传 Manifest Artifact。
> 3. `upload-artifact@v4`输出的`artifact-digest`定义为最终immutable ZIP上传流原始字节的
>    SHA-256，不是解压后目录或文件集合的逻辑Digest。`download-artifact@v4`虽然会对下载响应
>    原始流计算`expectedHash`，但不匹配时仅产生Warning，不会让Step失败，因此不能作为生产
>    失败关闭门禁。
> 4. Manifest Artifact 自己的digest由GitHub API或受保护证据库在上传后取得，作为外部信任锚，
>    不写入Manifest自身。Deploy必须按指定Artifact ID调用REST
>    `/actions/artifacts/{id}/zip`：带Authorization的API Client禁止自动重定向，只读取302 Location；
>    随后使用完全不带Authorization的独立Blob Client下载原始ZIP并计算SHA-256。只有与API
>    `artifact.digest`精确一致后，才允许验证ZIP条目、解压、校验Manifest签名/字段和配置包文件哈希。
> 5. Actions Artifact 当前保留期为90天，不能单独支撑长期回滚；服务器 ACL 保护副本至少保留
>    最近三次实际 deployed Release，或将 Manifest/配置包归档到有明确保留策略的不可变存储。
>    Artifact 已过期、被删除、签名/哈希不一致或镜像不可拉取时，回滚必须失败关闭。

### 5.5 Release审计

本节审计字段必须同时包含配置 Artifact 和 Manifest Artifact 的 name、id、digest。
生产输入不得只依赖 Step Summary 或未经绑定的日志文本；Release Run、Workflow path、ref、
Commit、两类 request_id 和三类 Digest 必须可以由 Manifest 与 GitHub Artifact 元数据互相复验。

- `REQUEST_ID`设置为Job级环境变量。
- CI匹配必须唯一并处理完整分页。
- 摘要必须记录CI URL、Release URL、Commit和三类Digest。
- 已存在镜像只能在Digest、Revision和可信发布证据全部匹配时复用。

## 6. Deploy修改方案

修改`.github/workflows/deploy-iwork.yml`。

### 6.1 保留的控制

- `apply=false`预检。
- 正式部署必须绑定成功Preflight Run。
- Image、Config、Config Artifact三类Digest。
- 固定部署脚本和协调模块SHA-256。
- 最小`permissions`。
- `DKT_iwork`和`DKT_iwork_alert_worker`成对切换。
- `run_migrations=false`默认值。
- 生产部署用户精确确认词。
- 任何身份、证据、锁、配置或健康异常均失败关闭。

### 6.2 使用Release Manifest

Deploy只执行：

输入契约必须新增并绑定 `release_run_id`、`release_run_attempt`、Manifest Artifact 的
`artifact_id/name/digest` 和 `release_request_id`；不能依靠“同 Commit 最新成功 Run”猜测。
Manifest中的CI/Release Run、Workflow path、ref、Commit、request_id和三类Digest必须与
GitHub API返回的Run/Artifact元数据逐项一致。Artifact必须按ID而不是名称下载；若保留
`actions/download-artifact`，至少必须使用与`name`互斥的`artifact-ids`，但由于其Digest不匹配只告警，
仍不能满足生产失败关闭要求。正式实现应替换Action下载并执行以下固定顺序：

1. 按`release_run_id`和两个Artifact ID读取唯一API元数据，校验Run、attempt、name、ID、过期状态和Digest。
2. 使用`HttpClientHandler.AllowAutoRedirect = $false`的API Client调用每个
   `/actions/artifacts/{id}/zip`，只接受预期重定向状态和绝对HTTPS Location。
3. 使用没有Authorization、Cookie或其他GitHub凭据的独立Blob Client下载原始响应流，同时写入本次
   `RUNNER_TEMP`唯一ZIP并计算SHA-256；禁止把GitHub Token转发到Blob Storage。
4. 原始ZIP Digest与API`artifact.digest`不一致时立即失败，禁止解压、解析Manifest或调用部署脚本。
5. Digest通过后验证ZIP条目：拒绝绝对路径、`..`路径穿越、重复条目、重解析点语义和非白名单文件。
6. 解压到本次Run唯一目录；Manifest包只允许JSON和签名，配置包只允许既定生产配置文件。
7. 校验Manifest签名、Schema、仓库、分支、Commit和三类Digest，再校验配置文件哈希和镜像OCI revision。
8. 校验Preflight收据以及服务器固定脚本、协调模块和看门狗机制哈希。
9. 调用固定服务器部署脚本，输出结构化摘要并清理ZIP、解压目录和临时凭据。

Artifact API不可达、重定向异常、Location不是HTTPS、Blob下载失败、原始归档Digest不一致、ZIP结构异常、
签名失败或清理失败均立即失败关闭。任何Artifact内容在原始归档Digest通过前都不得被解压或用于决策。

Release已经证明CI链路，Deploy不再重复查询一个未绑定 `ci_request_id` 的“任意成功CI”；
只接受 Manifest 明确引用且状态为 completed/success 的唯一 Release。

### 6.3 防止Skipped假成功

不使用Job级`if`把未授权actor或错误分支直接跳过。改为显式准入步骤：

- repository不匹配：失败。
- actor不匹配：失败。
- ref不匹配：失败。
- event不是`workflow_dispatch`：失败。

错误输入必须让Workflow显示Failure，而不是绿色Skipped。

推荐将准入拆成一个无生产权限的显式 admission Job 和依赖它的生产 Job。
admission 失败时整个 Workflow 为 Failure，生产 Job 不运行；不能用一个生产 Job 的
Job级 `if` 直接把拒绝显示为绿色 Skipped。Runner smoke 同样适用。

### 6.4 减少生产Runner内联代码

生产Workflow只保留Artifact下载、固定哈希检查、服务器脚本调用和摘要输出。GitHub API解析、配置包深度复验、生产锁、容器切换、状态收据和回滚逻辑继续由版本化模块及服务器固定脚本负责。

### 6.5 临时凭据

- 每个Run使用唯一`DOCKER_CONFIG`目录。
- 目录必须位于`RUNNER_TEMP`且不是重解析点。
- 清理失败必须写Warning和收据，不能完全`SilentlyContinue`。
- `DOCKER_CONFIG`初始化、配置包/Artifact归档下载、部署调用和清理必须处于同一`try/finally`
  生命周期；清理失败不得覆盖原始部署异常。
- `cleanup_failed`收据至少记录`GITHUB_RUN_ID`、`GITHUB_RUN_ATTEMPT`、`request_id`、失败路径、
  原始错误和时间；正式部署仅允许`GITHUB_RUN_ATTEMPT=1`，重跑必须失败关闭并重新生成预览/确认。
- Token不得进入日志、摘要、Artifact或状态文件。
- Runner启动前清理可信范围内的历史临时目录。

配置包临时目录也必须使用本次 Run 独立的 `RUNNER_TEMP` 子目录，并在创建、下载和清理
前验证其真实路径位于可信根目录内。凭据清理失败不能伪装成成功：应用已健康时不自动
回滚，但收据必须标记 `cleanup_failed` 并触发安全告警。

## 7. Skill修改方案

修改版本源`tools/skills/dkt-cicd`，再通过安装脚本同步到用户级Skill目录。

### 7.1 动作语义

- `ci`：用户明确要求“运行CI”时，只触发CI。
- `release`：只消费用户明确指定且已成功的 CI Run，不能用“最新成功CI”替代。
- `publish`：对应“提交并发版/发版当前版本”，生成新的 ci_request_id，触发并等待本次 CI 成功，再触发 Release。
- `preflight`：只接受匹配Release Manifest，执行`apply=false`。
- `deploy`：必须绑定成功Preflight，先生成预览，再等待用户精确确认。
- `production-status`：只报告Actions交付证据，不冒充实时Docker健康。
- `rollback`：在独立回滚Workflow完成前继续失败关闭。

### 7.2 发版前检查

Skill必须确认：

- 本地工作树没有未提交的发版范围修改。
- 远程`Keycloak` HEAD等于目标完整Commit。
- 用户明确说了“发版”“提交并发版”或“运行CI”。
- 普通“提交”“推送”不能被推断为发版。

### 7.3 CI和Release关联

每次发版都生成新的`ci_request_id`。Release只能接受：

- 同一完整Commit。
- `workflow_dispatch`事件。
- 本次Skill生成的`ci_request_id`。
- 唯一匹配。
- `completed/success`。

CI失败、Run歧义或证据读取失败时不得触发Release。
`publish` 的 CI→Release 关联必须记录 CI Run ID/attempt、ci_request_id 和 Release Run 的
release_request_id。CI 成功但 Release 失败时只重试 Release；不得偷偷重新使用其他 Commit 或旧 Run。

### 7.4 AI审核与用户确认

AI在正式部署预览中必须展示：

- Commit和变更摘要。
- AI风险结论和遗留风险。
- CI、Release和Preflight Run。
- Image、Config和Config Artifact Digest。
- 数据库迁移开关。
- 自动回滚能力和数据库边界。
- 正式部署后的验收项目。

确认状态继续绑定全部参数，15分钟有效且只能消费一次：

- 无迁移：`DEPLOY IWORK <完整Commit>`
- 有迁移：`DEPLOY IWORK WITH MIGRATIONS <完整Commit>`

禁止直接携带确认词跳过预览。

## 8. 生产健康验收

探针采用“切换前基线 → 切换后连续采样 → 24小时观察”三段式，不把所有外部故障都直接
当作候选版本故障。切换前外部 HTTPS、证书链、Nginx、OIDC discovery 和依赖可达性失败时
不允许切换；切换后只有能够归因于候选版本的硬失败才自动回滚。若新旧版本均失败或
Keycloak、DNS、TLS、远程数据库、网络等共享依赖不可判定，状态记为 `inconclusive`，
暂停自动回滚并告警，不能通过反复重试伪造成功。

SSE 探针不能只检查 HTTP 200 和 Content-Type，必须在限定时间内收到首个事件或心跳。
认证探针使用最小权限、只读的专用账号；通知探针不得修改真实用户通知或业务数据。
自签名或内部证书必须先让探针主机信任受控 CA，禁止使用 `-k` 或跳过证书校验。

固定服务器部署脚本在现有容器健康、`manage.py check --deploy`、内部HTTP和Celery ping基础上，增加：

- 外部HTTPS健康端点。
- Nginx入口。
- OIDC discovery或登录跳转。
- 实时API。
- SSE状态码和`Content-Type: text/event-stream`。
- 历史数据只读接口。
- 通知链路。
- Redis PING。
- 两个容器的Digest、Revision和RestartCount。

需要认证的探针使用最低权限专用探针账号。凭据只保存在服务器中央密钥文件，不进入Workflow、构建环境、Artifact或日志。

只有强制探针全部通过后，部署收据才能写为`deployed`。无法自动执行的真实浏览器验收必须明确记录为“未执行”或风险豁免，不能默认视为通过。

## 9. 数据库迁移与回滚边界

迁移准入必须包含可机器校验的 `migration_policy_id`、变更集合、兼容性结论和证据引用；
仅有 AI 或人工文字说明不能作为“旧应用可读取”的证明。未通过隔离数据库克隆/恢复验证
的迁移，在生产切换前失败关闭。

`run_migrations=false`继续作为默认值。

启用迁移时：

- AI必须单独审查迁移内容。
- 用户必须输入更强确认词。
- 只允许expand/contract或明确向后兼容迁移。
- 迁移前记录数据库版本、备份路径、文件大小和SHA-256。
- 部署收据记录迁移前后版本。
- 只有已通过隔离验证、明确标记为 backward-compatible 的迁移，才允许应用级自动回滚。

状态语义固定为：

- 无迁移失败：可自动恢复旧镜像和旧配置。
- 有迁移且兼容性证据完整：可自动恢复应用；数据库不自动覆盖恢复。
- 有迁移但兼容性未证明或语义失败无法归因：禁止宣称自动回滚，进入人工 forward-fix/恢复流程。
- 数据库恢复必须使用独立、明确授权的恢复流程，禁止在普通部署失败时自动覆盖生产数据库。

## 10. 独立运维Workflow

### 10.1 Runner smoke

`runner-smoke.yml`只作为基础设施验证：

- Runner身份。
- 独立工作目录。
- Docker API。
- GHCR只读拉取。
- Runner Hook。
- 固定部署机制哈希。

它不参与当前候选Release准入，也不能证明当前候选版本已经通过Preflight。

### 10.2 手工回滚

手工回滚不是“任意历史版本部署”，而是对当前生产收据的受控恢复操作。回滚目录必须来自
最近实际 deployed 且未 revoked/superseded 的 Release Manifest；目标镜像、两个配置 Artifact、
Manifest Artifact 和数据库兼容性证据任一缺失，都失败关闭。回滚前后仍需使用同一跨仓库锁，
并把 incident_id、请求人、批准人、当前版本和目标版本写入不可覆盖的收据。

新增独立`rollback-iwork.yml`，不再用`rollback_drill`冒充手工回滚：

- 目标必须来自历史实际 deployed 的成功 Release Manifest，不接受只有 CI/Release 成功的版本。
- 展示目标Commit、镜像和配置Digest。
- 回滚前执行只读Preflight。
- 用户输入精确回滚确认词。
- 默认禁止数据库恢复。
- 继续使用共享锁、维护标记和固定服务器脚本。

回滚演练保留为独立维护动作，不作为日常 Deploy 输入；迁移完成后从日常 Deploy 输入中移除
`rollback_drill`，避免演练与真实回滚再次混淆。

## 11. 服务器准入与跨仓库协调

Runner准入必须固定：

- 仓库。
- Workflow路径。
- 分支。
- actor。
- 目标状态固定为已认证的机制指纹；迁移期可暂时保留 ApprovedHeadSha 作为补偿门禁，但
  不得替代 Manifest、三类 Digest 和 request_id 校验。
- 部署脚本SHA-256。
- 协调模块SHA-256。
- 看门狗脚本哈希或签名。
- Release Manifest Schema版本。

继续保留：

- `Global\DKT-Production-Deploy`。
- `Global\DKT-Docker-Recovery`。
- 跨仓库文件锁。
- maintenance marker。
- 看门狗observe-only。
- 部署后grace period。

GitHub `concurrency`只能控制iwork仓库内部并发，不能替代Portal、看门狗和周重启共同遵守的服务器全局锁。

## 12. 实施顺序与提交拆分

按以下顺序实施，每个提交只包含对应范围：

1. `[YYYY-MM-DD][CHORE] 保存当前生产与机制基线，登记本改造为阶段8后续切片`
2. `[YYYY-MM-DD][FEAT] 在现有触发器下实现publish的CI到Release唯一编排`
3. `[YYYY-MM-DD][TEST] 补Fake-Gh、Run唯一性、分页和旧Run误关联红绿测试`
4. `[YYYY-MM-DD][FIX] 将完整CI与轻量PR/Push检查拆开，保留无发布权限的快速反馈`
5. `[YYYY-MM-DD][REFACTOR] 锁定生产依赖、基础镜像并实现本地Smoke后单次推送`
6. `[YYYY-MM-DD][FIX] 按HTTP状态分类GHCR错误并拒绝不一致标签复用`
7. `[YYYY-MM-DD][FEAT] 两阶段发布配置Artifact和独立Release Manifest`
8. `[YYYY-MM-DD][REFACTOR] Deploy按Manifest和Artifact元数据双读校验并移除猜测`
9. `[YYYY-MM-DD][FIX] 修复显式准入、唯一Release匹配和临时凭据清理`
10. `[YYYY-MM-DD][FEAT] 先observe-only再启用分级HTTPS/OIDC/SSE/业务探针`
11. `[YYYY-MM-DD][CHORE] 切换机制指纹准入并在Runner空闲后安装复验`
12. `[YYYY-MM-DD][DOCS] 固化迁移兼容性、Artifact保留和回滚目录`
13. `[YYYY-MM-DD][FEAT] 新增独立iwork手工回滚Workflow并单独验收`
14. `[YYYY-MM-DD][DOCS] 将每个切片证据回写唯一总方案并完成端到端验收`

涉及生产部署机制的提交在真实使用前，必须在Runner空闲时重新安装并复验服务器准入策略。
> 每个切片都必须先通过离线测试和对应的隔离/只读验收，再进入下一切片；任何生产切换
> 机制变更都必须重新生成机制指纹并由固定准入 Hook 校验。切换触发器的提交必须最后执行。

## 13. 测试与验收计划

### 13.1 触发行为

- 普通Push到`Keycloak`不会创建完整 `iwork CI` Run；如保留轻量检查，只创建无生产权限的快速检查 Run。
- 普通Commit不会触发 Release；轻量检查是否触发由 `ci-pr.yml` 的路径与协作规则决定。
- “只运行CI”只产生一个带唯一`request_id`的CI Run。
- “提交并发版”产生唯一CI到Release证据链。
- CI失败时不会触发Release。
- 普通“提交”不会被Skill误判为发版。

### 13.2 Release

- 新 SHA 标签只允许一次构建；已有标签不重新构建，只能按完整证据复用。
- 配置 Artifact 与 Manifest Artifact 分离，Manifest 不得自引用；两者的 name/id/digest 均可复验。
- 404允许新标签构建；401/403/429/5xx、DNS/TLS、超时和未知错误必须失败关闭。

- Release全程只有一次Docker构建。
- 推送镜像就是完成容器Smoke的本地镜像。
- 网络、认证、限流和GHCR服务端错误全部失败关闭。
- 同一Commit不能生成两个不同的有效SHA标签Digest。
- Release Manifest能唯一追溯CI、Release和三类Digest。

### 13.3 Preflight和Deploy

- Deploy只接受指定 Release Manifest 及两个 Artifact 的唯一元数据，不接受 `Select-Object -First 1` 或“最新成功”猜测。
- `config_artifact_digest`和`manifest_artifact_digest`必须被解释为`upload-artifact@v4`最终immutable ZIP
  原始字节SHA-256；不能把解压后文件哈希替代为Artifact archive digest。
- Deploy必须按Artifact ID手工获取原始ZIP；带Token的API请求禁止自动重定向，Blob下载请求不得包含
  Authorization。原始ZIP Digest匹配后才允许解压和读取Manifest/配置。
- `download-artifact`内建Digest mismatch Warning不能视为失败关闭；若仍先由Action解压，阶段4验收必须
  标记为未完成。
- ZIP路径穿越、绝对路径、重复条目、多余文件、异常重定向或Digest不匹配均必须产生显式Failure。
- 未授权 actor/ref/event 必须产生显式 Failure；不能以绿色 Skipped 结束。
- 临时凭据或配置目录清理失败必须留下不可覆盖的 cleanup_failed 收据并告警。
- 外部探针必须覆盖基线、连续采样、SSE首个事件/心跳和共享依赖不可判定分支。

- Preflight不会切换容器、执行迁移或创建维护窗口。
- 正式部署必须绑定匹配的Preflight收据。
- 用户确认状态绑定全部参数且不可复用。
- 直接跳过预览不能通过Skill。
- iwork和alert-worker始终使用同一Digest。
- Portal、看门狗、周重启和iwork不能并发操作共享Docker。
- 外部HTTPS、OIDC、SSE和关键业务探针失败时部署失败。

### 13.4 回滚和审计

- 回滚目标只能是历史实际 deployed 且未撤销的 Release；仅构建成功的版本不能直接回滚。
- 迁移兼容性没有机器可验证证据时，不允许自动恢复旧应用。

- 无迁移失败可以恢复旧镜像和旧配置。
- 有迁移时不会自动覆盖生产数据库。
- 数据库备份路径和SHA-256进入服务器收据。
- Actions证据与实时Docker健康分开汇报。
- 所有失败路径返回非零退出码。
- 日志、摘要和Artifact不包含生产密码、Token或中央密钥内容。

## 14. 生产切换步骤

1. 保存当前生产收据、活动 Release、镜像/配置/Artifact Digest、Hook 与机制哈希，形成可回退基线。
2. 在 Push/PR 双轨仍保留时，先实现并验证 Skill 的 `publish`（本次 CI → Release）和 Run 唯一关联。
3. 完成 GHCR 错误分类、生产依赖锁定、基础镜像锁定、单次构建与本地隔离 Smoke。
4. 先以 additive 方式发布配置 Artifact 和独立 Release Manifest，保留旧证据并做双读比对。
5. 将 Deploy 改为按指定 Release/Manifest/Artifact 元数据唯一校验，补齐显式 admission 和清理收据。
6. 外部 HTTPS/OIDC/SSE/业务探针先 observe-only，建立基线并验证证书信任，再启用分级硬门禁。
7. 机制相关文件同一提交更新机制指纹、安装器、Workflow 哈希和 Hook；Runner 空闲后安装、smoke、预检。
8. 以上全部通过后，最后关闭完整 CI 的普通 Push 触发；保留轻量 PR/Push 检查。
9. 单独实现并验收 `rollback-iwork.yml`，仅允许历史实际 deployed 且未撤销版本。
10. 运行一次新的完整 CI → Release → Preflight → 用户确认 → Deploy；独立执行业务探针与24小时观察。

## 14.1 本轮工作树实施状态（2026-08-31）

已在本地工作树实现并完成隔离验收的切片：

- 完整 `ci.yml` 已切换为仅 `workflow_dispatch`，保留必填 `request_id`、Compose解析、迁移检查、
  Python/PowerShell测试；PR反馈由无生产权限的 `ci-pr.yml` 承担，完整CI不再构建临时Docker镜像。
- `dkt-cicd` 已实现 `publish`（本次CI→Release）、精确GUID Run关联、120秒发现窗口和最终查询；
  iwork Release 强制绑定显式 `ci_request_id`，失败Run不解析Digest。
- Release 已采用配置Artifact + 独立 `release-manifest.json`/签名Artifact 两阶段模型；Manifest
  不自引用Artifact ID/Digest，RSA签名和Key ID是强制门禁，GHCR查询按HTTP错误分类。
- Deploy证据链已加入指定Release Run/attempt、两个Artifact元数据、三类Digest、Manifest签名和
  OCI标签校验；归档下载已改为按Artifact ID使用禁止自动重定向的API Client，Blob Client不携带
  Authorization，原始ZIP Digest通过后才执行安全白名单解压。该切片已通过阶段4回归测试，仍需随本轮
  提交进入真实CI验证；签名材料、生产Runner准入和真实生产验收仍未完成。
- 服务器固定脚本已加入不可覆盖的`request-consumption`收据；正式部署绑定预检消费收据，重放失败关闭；
  测试夹具已同步该契约。`apply=true`的Workflow re-run（`run_attempt != 1`）失败关闭。

本地验证证据（未推送、未触发Actions、未操作生产）：CI/配置包/阶段4组合测试`68 passed`，dkt-cicd
离线验收`133`个断言通过，20个PowerShell脚本/模块解析通过，`git diff --check`通过。为控制范围，
本轮不重复全仓历史Ruff债务检查；提交前仍需同步版本源 Skill 到用户安装副本并逐文件复验SHA-256。

尚未满足的外部条件与明确阻断：

1. GitHub 尚未配置 `IWORK_RELEASE_MANIFEST_SIGNING_PRIVATE_KEY_PEM`、
   `IWORK_RELEASE_MANIFEST_SIGNING_KEY_ID` 和 `IWORK_RELEASE_MANIFEST_VERIFY_CERT_B64`；配置前禁止真实Release。
2. 生产Runner准入必须在空闲维护窗口安装本轮部署脚本/Workflow哈希并执行smoke；旧Hook不得放行新机制。
3. 外部HTTPS/OIDC/SSE/通知等业务探针仍需先observe-only建立基线，再按方案启用硬门禁；浏览器真实账号
   验收和24小时稳定观察未完成，不能以Actions成功替代。
4. 只有以上本地门禁和签名/准入条件全部满足后，才可以按用户新确认执行真实CI、Release、Preflight和Deploy；
   任一新失败立即停止并回写本总方案。

## 15. 明确不做的事项
> 本方案全部切片的证据完成前，不执行生产切换；任一切片失败必须停止并分析，不能通过重试或旧证据绕过。

- 不使用普通Push自动触发完整CI。
- 不使用Commit Message条件模拟“未触发CI”。
- 不引入GitHub Environment Required Reviewer作为重复人工审批。
- 不允许生产Runner checkout、测试或构建仓库代码。
- 不把生产密钥放入GitHub、镜像或Artifact。
- 不使用`latest`部署生产。
- 不把Workflow成功等同于实时生产健康。
- 不在普通部署失败时自动覆盖恢复生产数据库。
- 不因用户确认而跳过任何确定性安全门禁。

本方案实施后，Skill成为 CI、Release、Preflight 和 Deploy 的唯一正常编排入口，但不是授权边界；
普通代码提交与正式发版解耦，确定性安全边界仍由 Workflow admission、不可变 Manifest/Artifact、
机制指纹、服务器固定脚本、跨仓库锁、探针和失败关闭共同提供。
