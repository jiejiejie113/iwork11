# iwork CI/CD 最后冲刺实施方案

> 制定日期：2026-08-28
> 适用仓库：`GuChenkano/iwork`
> 本地分支：`Keycloak`
> 变更前生产基线：`4cb8e31188a0022ea5441e1e10490adc4cc8ad8a`
> 原始实现提交：`774283a5ac293c9209a09f07e721b8880a9b3098`
> 当前远程 HEAD：`029fa6fc6203f5b4f785d800e649d4eac7c7521f`
> 方案状态：S1 修复中；上次正式部署在切换前失败，修复提交尚未形成
> 总进度基线：[2026-08-21-GitHub-Actions-CICD完整实施方案.md](./2026-08-21-GitHub-Actions-CICD完整实施方案.md)

## 1. 文档定位

本文是 iwork CI/CD 最后冲刺阶段的执行清单，用于把当前已经完成并已提交但尚未推送的本地实现，推进为经过真实 GitHub Actions 和生产环境验证的完整交付。

本文不替代总方案。每个阶段完成后，必须把实际 Commit、Actions Run、Digest、测试结果、生产收据、异常和风险豁免同步回写到总方案；若本文与总方案或仓库实际状态不一致，以仓库现场证据和总方案最新记录为准。

## 2. 最终目标

建立并真实跑通以下生产交付模型：

```text
不可变应用镜像
    + 不可变生产配置包
    + 固定生产部署机制
    + 唯一 request_id
    + 成对回滚
    = 可验证、可追溯、失败关闭的 iwork 生产发布
```

最终必须证明：

1. 同一批准 Commit 同时绑定应用镜像 Digest、配置逻辑 Digest和GitHub Artifact存储 Digest。
2. CI、Release、Preflight和Deploy均使用独立GUID `request_id`关联，不能用平台Run ID替代。
3. 生产容器实际读取配置包内的`env/production.env`，不把服务器Git工作区中的同名文件作为候选配置。
4. `DKT_iwork`和`DKT_iwork_alert_worker`作为一个发布单元同时切换和验收。
5. 失败时恢复上一镜像和上一配置包，并保留上一Commit、镜像Digest、配置Digest和容器Image ID证据。
6. 配置、镜像、Commit、request_id或Run关联出现缺失、歧义、篡改或不一致时，部署必须失败关闭。
7. 本轮不执行数据库迁移，不操作数据库、卷、Redis、Keycloak、共享网络或Nginx拓扑。

## 3. 当前事实基线

### 3.1 本地状态

```text
仓库：C:\Users\lipengfei\ZCodeProject\iwork
分支：Keycloak
基线：4cb8e31188a0022ea5441e1e10490adc4cc8ad8a
当前远程 HEAD：029fa6fc6203f5b4f785d800e649d4eac7c7521f
工作区：包含跨身份 Mutex ACL 修复及回归测试未提交修改
远程：029fa6f 已推送，但该提交对应的正式部署失败在生产切换前
```

本轮改动主要覆盖：

- 不可变生产配置包生成器及测试。
- CI、Release和Deploy Workflow的`request_id`及三类Digest契约。
- 固定生产部署脚本、活动发布指针和成对回滚。
- Compose服务运行时配置文件路径覆盖。
- 跨仓库生产协调锁的`request_id`审计。
- `dkt-cicd` Skill的Run关联、Digest解析、生产预览和失败关闭。
- 总方案和仓库约束文档。

### 3.2 已取得的本地证据

截至2026-08-28，已取得并在提交`774283a5ac293c9209a09f07e721b8880a9b3098`前复核的本地证据：

| 验证项 | 当前结果 |
|---|---|
| Python全量测试 | `596 passed`，另有1条既有`requests`依赖版本警告 |
| 部署阶段4隔离测试 | `35 passed`（包含于全量测试） |
| 配置包与CI契约测试 | `53 passed`（配置包、CI和阶段4目标测试） |
| `dkt-cicd`离线验收 | `112`个断言通过 |
| Ruff | 通过 |
| 生产订单同步脚本测试 | 通过 |
| 生产订单计划任务安装测试 | 通过 |
| Local/Production Compose解析 | 使用测试占位变量通过 |

同时完成20个PowerShell脚本/模块解析、6个YAML解析、JavaScript语法检查、Compose占位变量解析、Ruff、
`git diff --check`以及版本化Skill与用户安装副本6个文件逐项SHA-256一致性检查。上述证据只能证明当前本地工作区行为，
不等价于已提交、已推送、GitHub Actions成功或生产环境已采用新机制。

### 3.3 当前生产基线

本轮最后冲刺尚未修改生产。根据最近一次已记录证据，生产仍运行通知修复版本：

```text
Commit：4cb8e31188a0022ea5441e1e10490adc4cc8ad8a
Image Digest：sha256:6b131b70ef209073adf9e6de7e048f230e2c9ce00b8b3eea0d78187455ff3285
Web：DKT_iwork
Worker：DKT_iwork_alert_worker
```

开始任何生产动作前必须重新只读核验，不能直接把以上历史记录视为当前事实。

### 3.4 2026-08-28 正式部署阻断与修复范围

对提交 `029fa6fc6203f5b4f785d800e649d4eac7c7521f` 执行的正式部署 Run
[`33146302986`](https://github.com/GuChenkano/iwork/actions/runs/33146302986)
在生产切换前失败，错误为：

```text
Access to the path 'Global\\DKT-Docker-Recovery' is denied.
```

只读核验确认生产未切换，两个 iwork 容器保持旧版本、`healthy`且无重启；没有遗留部署锁、维护标记或候选容器。根因是 Docker 健康看门狗以 `SYSTEM` 身份先创建共享恢复 Mutex，而生产 Runner 以 `DONGMING\\shuju` 运行，默认 DACL 未授权 Runner 打开该对象。

本轮修复覆盖所有共享创建方：iwork 部署脚本、生产协调审计 Mutex、Portal 部署脚本和 Docker 看门狗统一显式授权 `SYSTEM`、本机 Administrators 与 Runner 身份，并对短暂 `UnauthorizedAccessException` 做有界重试；权限异常继续失败关闭并输出身份、Mutex 名称和原始错误。测试增加了受限 Mutex 跨身份释放/重建回归。旧 `029fa6f` 的 Release、配置包、预检和失败 Deploy 证据均不可复用，修复形成新 Commit 后必须重新执行完整 CI、Release、准入安装、预检和一次正式部署。

## 4. 已实现的目标能力

### 4.1 不可变配置包

配置包只允许包含：

```text
config-manifest.json
docker-compose.yml
env/production.env
```

配置清单固定绑定：

```text
schema
application
source_commit
image_digest
compose_sha256
production_env_sha256
config_digest
```

清单保持最小、确定性Schema，不加入生成时间等每次运行变化的字段，确保相同Commit、镜像和配置输入能够得到相同逻辑Digest。GitHub Run、仓库、分支、Artifact ID和生成时间属于发布收据，不混入配置内容身份。

配置文件先以严格UTF-8解码，再规范化为无BOM、LF字节；`compose_sha256`和`production_env_sha256`记录规范化文件的64位小写十六进制摘要，`config_digest`记录固定六行清单内容的完整`sha256:`加64位小写十六进制摘要。生成器和部署端均按此规则复验，不能用原始CRLF或带BOM字节绕过校验。

配置包生成和生产复验均拒绝：

- 未知文件或目录。
- 路径穿越和重解析点。
- 覆盖已有不可变目标。
- 生产环境文件中的密码、Secret、Token、私钥、证书或Cookie类敏感键。
- Compose环境映射中的敏感明文和私钥内容。
- 无效UTF-8、文件哈希不一致或清单字段不一致。

### 4.2 三类Digest

Release必须稳定输出：

```text
IWORK_IMAGE_DIGEST
IWORK_CONFIG_DIGEST
IWORK_CONFIG_ARTIFACT_DIGEST
IWORK_REQUEST_ID
```

含义如下：

| 字段 | 证明内容 |
|---|---|
| Image Digest | GHCR中实际发布的不可变应用镜像 |
| Config Digest | 配置清单和两个配置文件的逻辑内容身份 |
| Config Artifact Digest | GitHub保存的配置Artifact存储身份 |
| request_id | 本次用户请求在Actions链路中的唯一关联身份 |

Deploy Workflow和`dkt-cicd`必须逐项校验，不得仅校验格式或取“最新成功Run”。

### 4.3 运行时配置与成对回滚

Compose通过`IWORK_RELEASE_PROFILE_FILE`指向已验证配置包中的绝对`production.env`路径。固定部署脚本必须在每次候选和回滚Compose调用期间显式设置该值，并在调用完成后恢复进程环境。

部署失败时恢复：

```text
上一Web镜像
上一Alert Worker镜像
上一生产配置包
上一active-release指针
```

回滚状态必须保存上一镜像Digest、上一OCI Commit、上一配置Digest、上一容器Image ID和`request_id`。两个生产容器的镜像Digest或OCI Commit不一致时，不允许继续部署。

## 5. 冲刺阶段总览

| 阶段 | 内容 | 生产影响 | 完成标志 |
|---|---|---|---|
| S1 | 本地代码和文档收口 | 无 | Mutex 修复、测试和文档完成，全部本地门禁通过 |
| S2 | Git提交和远程推送 | 无 | 本地、远程`Keycloak`指向修复新Commit |
| S3 | 真实CI和Release | 无生产切换 | 成功生成镜像、配置和Artifact三类Digest |
| S4 | 生产只读基线与固定机制安装 | 安装受控执行机制，不切换应用 | 固定脚本/模块/Hook哈希与批准Commit一致 |
| S5 | `apply=false`生产预检 | 只拉取和校验候选，不替换容器 | 预检成功且生产容器身份未变 |
| S6 | 正式生产部署 | 替换iwork两个应用容器 | 新确认词授权后部署成功，状态收据完整 |
| S7 | 最终验收与观察 | 只读检查为主 | 自动验收完成，观察期无持续异常 |

## 6. S1：本地代码和文档收口

### 6.1 固定工作区边界

执行前记录：

```powershell
chcp 65001
git status --short --branch
git diff --stat 4cb8e31188a0022ea5441e1e10490adc4cc8ad8a
git diff 4cb8e31188a0022ea5441e1e10490adc4cc8ad8a --name-status
```

禁止：

- `git reset --hard`、`git clean`或覆盖用户文件。
- 将`.reasonix/`、临时包、测试输出、数据库文件或密钥加入提交。
- 为了让测试通过而修改生产数据、数据库、卷或服务器状态。

### 6.2 重算固定哈希

每次修改以下文件后，必须重算并同步Workflow和测试常量：

```text
scripts/Invoke-IworkProductionDeployment.ps1
scripts/ProductionCoordination.psm1
```

至少核对：

```text
DEPLOY_SCRIPT_SHA256
DEPLOY_COORDINATION_MODULE_SHA256
EXPECTED_COORDINATION_MODULE_SHA256
```

### 6.3 最终验证矩阵

按以下顺序执行：

1. 目标测试：

```powershell
python -m pytest -q tests/test_ci_workflow.py tests/test_production_config_bundle.py tests/test_production_deployment_stage4.py
```

2. Python全量测试：

```powershell
python -m pytest tests/ -q
```

3. Ruff：

```powershell
python -m ruff check --no-cache --ignore E402,W292 iwork tests/test_ci_workflow.py tests/test_production_config_bundle.py tests/test_production_deployment_stage4.py
```

4. PowerShell与运维脚本：

```powershell
.\tests\test_sync_production_orders.ps1
.\tests\test_install_production_orders_sync_task.ps1
.\tools\skills\dkt-cicd\tests\Test-DktCicd.ps1
```

5. 静态契约：

- Windows PowerShell 5.1解析所有本轮PowerShell脚本。
- 解析全部Actions YAML。
- 检查本轮JavaScript语法。
- 分别解析local和production Compose；只使用测试占位变量，不读取真实密钥。
- 执行`git diff --check`。
- 扫描新增可达内容中的Token、密码、内部凭据和不应公开的敏感基础设施材料。

6. Skill同步：

```powershell
.\scripts\Install-DktCicdSkill.ps1
.\tests\test_install_dkt_cicd_skill.ps1
```

安装后必须证明版本源与用户安装副本逐文件一致；不能直接编辑安装副本作为正式来源。

### 6.4 最终双轴审查

以`4cb8e31188a0022ea5441e1e10490adc4cc8ad8a`为固定点执行：

- Standards：检查AGENTS、PowerShell 5.1、Actions、Git、安全和生产约束。
- Spec：检查本文和总方案要求是否完整实现，有无缺失、逻辑错误或范围蔓延。

任何P0/P1、安全边界、回滚错误、生产配置漂移或证据可伪造问题均阻断提交；低风险文档、断言或哈希同步问题可立即修复并重跑。

### 6.5 S1完成条件

- 工作区改动全部可以解释并属于本轮范围。
- 最终测试数字和哈希已记录。
- 双轴审查没有未解决的阻断项。
- 总方案同步到实际本地状态。
- `git diff --check`无错误。

## 7. S2：Git提交和远程推送

### 7.1 提交前检查

```powershell
git status --short
git diff --cached --stat
git diff --cached --check
```

必须逐文件确认暂存范围，不能使用不经检查的全目录批量提交。

### 7.2 建议提交

上一轮代码、测试、Skill和同步文档构成的原子提交为：

```text
[2026-08-28][FEAT] 为iwork生产发布绑定不可变配置包
```

实际提交：`774283a5ac293c9209a09f07e721b8880a9b3098`。该提交随后经过多次 Digest/Run 修复到 `029fa6f`，但正式部署在切换前因跨身份 Mutex 权限失败；本轮修复需生成新的原子提交。

提交后已再次确认目标测试、`git diff --check`和工作区状态；当前仅待推送。

### 7.3 推送验收

```powershell
git push origin Keycloak
git rev-parse HEAD
git rev-parse origin/Keycloak
git ls-remote origin refs/heads/Keycloak
```

三个远程/本地SHA必须完全一致。推送失败时只分析认证、网络、代理或远程分支状态，不得强推。

## 8. S3：真实CI和Release

### 8.1 CI

使用`dkt-cicd`触发新Commit的CI，并等待明确终态：

```text
status=completed
conclusion=success
headSha=本轮新Commit
event=workflow_dispatch
displayTitle包含本次request_id
```

如果Run在120秒内不可见，只做状态查询和关联分析，禁止未经确认重复触发。

### 8.2 Release

CI成功后触发Release。Release必须产生且唯一输出：

```text
ImageDigest=sha256:<64位小写十六进制>
ConfigDigest=sha256:<64位小写十六进制>
ConfigArtifactDigest=sha256:<64位小写十六进制>
RequestId=<GUID>
```

还必须验证：

- GHCR镜像OCI revision等于新Commit。
- Artifact名称固定为`iwork-production-config-<Commit>`。
- Artifact未过期。
- 配置Artifact的GitHub API Digest等于Release机器记录。
- 下载后的清单、Compose和production.env哈希与Config Digest一致。
- 同一Commit若存在多个候选Release，只有Artifact Digest精确匹配且身份唯一的Run可用。

### 8.3 S3停止条件

出现以下任一情况立即停止，不进入生产：

- CI或Release不是`completed/success`。
- 任一Digest缺失、格式错误或出现两个不同值。
- Run的Commit、分支、事件或request_id不匹配。
- Artifact无法下载、已过期或API Digest不一致。
- 镜像OCI revision不匹配。
- Release日志或摘要暴露密钥。

## 9. S4：生产基线与固定机制安装

### 9.1 只读基线

在`192.168.0.97`只读记录：

- 当前Windows执行身份。
- iwork Runner Listener和Worker状态；安装时必须没有活动Worker。
- `DKT_iwork`和`DKT_iwork_alert_worker`的容器ID、配置镜像、镜像ID、OCI revision、健康状态和RestartCount。
- 当前部署锁、维护标记和候选残留。
- 固定部署脚本、协调模块、Runner Hook的路径和SHA-256。
- 最近成功部署收据和现有`active-release.json`状态。

不得读取：

```text
D:\DM\dkt-secrets.env
Runner凭据内容
GitHub Token
数据库密码
Keycloak密钥
```

### 9.2 安装固定机制

只有在以下条件同时满足时执行安装：

- 新Commit已完成人工审查、CI和Release。
- Runner无活动Worker。
- 生产没有部署锁、维护窗口或其他共享运维操作。
- 本地安装源脚本哈希与批准提交一致。
- 目标会话具备要求的提升权限。

安装只更新固定部署脚本、协调模块和Runner准入Hook，不重启或替换生产容器，不操作数据库、卷或网络。

安装后重新计算服务器文件哈希，并与Workflow常量、提交内容逐项比较；任一不一致立即停止。

## 10. S5：`apply=false`生产预检

预检输入必须来自同一成功Release：

```text
Commit
ImageDigest
ConfigDigest
ConfigArtifactDigest
request_id
change_description
apply=false
run_migrations=false
```

预检允许：

- 下载和复验配置Artifact。
- 登录GHCR并拉取批准Digest镜像。
- 验证镜像OCI revision。
- 生成候选Compose并执行`docker compose config --quiet`。
- 执行不会切换生产容器的静态和身份检查。

预检禁止：

- `docker compose up`替换生产容器。
- 执行数据库迁移。
- 修改`active-release.json`。
- 创建长期维护标记。
- 重载Nginx、重建网络或操作共享卷。

预检后必须证明：

- 两个生产容器ID、镜像ID和RestartCount保持不变。
- 无候选容器、部署锁和维护标记残留。
- 预检Run、request_id和三类Digest已写入摘要。

## 11. S6：正式生产部署

### 11.1 新确认词原则

正式部署必须在成功预检之后重新生成完整预览，预览至少展示：

```text
服务和仓库
分支
新Commit
ImageDigest
ConfigDigest
ConfigArtifactDigest
request_id
目标环境
run_migrations=false
变更说明
```

必须等待用户在看到本次预览后逐字输入新确认词。以下历史确认词不得复用：

```text
DEPLOY IWORK 4cb8e31188a0022ea5441e1e10490adc4cc8ad8a
```

预览超过15分钟、参数改变或被消费后必须重新生成。

### 11.2 正式切换步骤

1. 获取共享生产锁并写入request_id和三类Digest。
2. 写入短期维护标记，使看门狗进入观察模式。
3. 复验当前双容器健康、同一镜像Digest和同一OCI Commit。
4. 固化上一活动发布和上一容器身份。
5. 再次验证并持久化候选配置包。
6. 使用候选配置包内绝对production.env启动Web和Alert Worker。
7. 执行Django部署检查、HTTP检查、Worker ping、镜像ID和健康检查。
8. 原子更新`active-release.json`和部署状态收据。
9. 清理临时Compose、GHCR临时认证、维护标记和共享锁。

### 11.3 自动回滚

若候选切换后任一硬性检查失败：

1. 使用预先固化的两个旧镜像回滚引用。
2. 使用上一配置包中的Compose和绝对production.env。
3. 同时恢复Web和Alert Worker。
4. 重新验证容器Image ID、HTTP、Django和Worker。
5. 恢复上一`active-release.json`。
6. 写入`rolled_back / RollbackSucceeded=true`或`rollback_failed`收据。

回滚失败属于大型阻断，必须立即停止并汇报，不自动再次部署或再次回滚。数据库不在本轮自动回滚范围内。

## 12. S7：最终生产验收

### 12.1 容器与配置身份

- `DKT_iwork`和`DKT_iwork_alert_worker`均为`running / healthy`。
- 两个容器RestartCount为0，或能对非0值给出明确的本轮证据解释。
- 两个容器使用同一完整镜像Digest和同一OCI Commit。
- Compose解析出的服务`env_file`来自：

```text
D:\DM\cicd-state\iwork\release-config\<config-digest-hex>\env\production.env
```

- 不得解析到`D:\DM\iwork\env\production.env`。

### 12.2 收据与审计

以下位置必须成对一致：

- GitHub Actions摘要。
- Release机器记录。
- 部署Run详情。
- 共享锁事件。
- 部署状态JSON。
- `active-release.json`。
- 回滚演练或自动回滚收据（若本轮产生）。

必须能够从`request_id`反查唯一CI、Release、Preflight和Deploy Run。

### 12.3 应用回归

自动化检查至少覆盖：

- iwork入口未登录时仍进入OIDC登录流程。
- 首页、生产详情、历史数据和现有SSE无回归。
- 站内通知API、已读写入和详情弹窗相关测试继续通过。
- alerts Worker健康且没有持续任务异常。
- Nginx、Keycloak、Portal、MySQL和Redis未被本轮重建。

真实账号浏览器验收若继续按既有决定豁免，必须明确记录“未执行”，不能写成已通过。

### 12.4 清理检查

- 无活动生产部署锁。
- 无过期维护标记。
- 无候选容器。
- 无临时Compose和临时配置包目录残留。
- 临时Docker认证目录已删除。
- 服务器Git工作区未被reset、clean或用于候选配置。

## 13. 观察期

正式部署后执行分层观察：

| 时间 | 检查内容 |
|---|---|
| 立即 | 两容器健康、镜像/配置身份、HTTP、Worker、锁和维护标记 |
| 15分钟 | 重启次数、错误日志、SSE、通知与alerts任务 |
| 1小时 | 持续健康、无连接风暴、无任务积压、无异常回滚 |
| 24小时 | 服务稳定性、业务错误、容器重启、告警和资源使用最终收口 |

硬性可用性故障可按已经认证的成对回滚路径处理；业务语义问题必须人工判断，不能只因容器healthy而忽略。

## 14. 失败分级和停止规则

### 14.1 可立即修复并重跑

- 文档与实际字段不一致。
- 测试断言遗漏。
- 固定SHA-256未同步。
- YAML、PowerShell或格式检查的小型错误。
- Skill安装副本不同步。

修复后必须从受影响的最早门禁重新验证，不能直接沿用旧成功结果。

### 14.2 必须停止并汇报

- 安全或权限边界存在漏洞。
- 生产配置包仍可能读取服务器工作区配置。
- Digest、Commit、request_id或Run无法唯一对应。
- Artifact Digest无法由GitHub API证实。
- Runner不是空闲状态却需要更新准入。
- 生产容器基线不健康或双容器身份不一致。
- 发现部署锁、维护操作或其他生产变更并发。
- 正式切换失败且自动回滚失败。
- 涉及数据库、卷、Keycloak或共享网络的非预期操作。

停止后应提供：原始错误、发生阶段、生产是否切换、容器当前状态、已执行动作、未执行动作和人工处理建议。

## 15. 禁止事项

整个冲刺期间禁止：

- 读取、输出或提交生产密钥。
- 在GitHub Actions中传递`dkt-secrets.env`。
- 从服务器Git工作区直接读取候选production.env。
- 使用可变镜像标签代替完整Digest。
- 在生产服务器构建镜像。
- 让生产Runner执行PR代码或任意Shell输入。
- 跳过预检直接正式部署。
- 复用历史生产确认词。
- 自动执行数据库迁移、数据库恢复或卷清理。
- 自动重复失败的正式部署或回滚演练。
- 强推、重置或清理本地/服务器Git工作区。

## 16. 最终交付清单

完成后应在总方案中附上：

- [ ] 最终Git Commit SHA。
- [ ] 远程`origin/Keycloak`一致性证据。
- [ ] 本地目标测试、全量测试、Ruff和静态检查结果。
- [ ] 最终双轴审查结论。
- [ ] CI Run ID、链接、request_id和结论。
- [ ] Release Run ID、链接、request_id和结论。
- [ ] 完整Image Digest。
- [ ] 完整Config Digest。
- [ ] 完整Config Artifact Digest。
- [ ] 生产固定机制安装文件哈希。
- [ ] Preflight Run ID、链接和生产未变证据。
- [ ] 用户本次正式部署确认词。
- [ ] Deploy Run ID、链接和最终状态。
- [ ] `active-release.json`非敏感字段摘要。
- [ ] 两容器身份、健康和RestartCount。
- [ ] 实际配置包env_file路径。
- [ ] 锁、维护标记、候选和临时认证清理结果。
- [ ] 浏览器验收结果或明确风险豁免。
- [ ] 24小时观察结论。

## 17. 完成定义

只有以下条件全部满足，iwork CI/CD最后冲刺才可以标记为完成：

1. 本地改动已审查、提交、推送，远程Commit一致。
2. 新Commit的CI与Release真实成功。
3. 三类Digest和request_id在GitHub证据链中唯一且一致。
4. 生产固定部署机制已按批准Commit安装并通过哈希核验。
5. `apply=false`预检成功且证明生产未变。
6. 用户在本次部署预览后提供了新确认词。
7. 正式部署成功，或失败后自动成对回滚成功且按失败交付收口。
8. 生产实际运行配置来自不可变配置包。
9. 所有锁、维护标记、候选和临时凭据清理完成。
10. 自动化验收完成，浏览器验收完成或明确记录风险豁免。
11. 24小时观察完成且无持续异常。
12. 全部证据已回写到总方案，本文不再保留模糊的“已完成”描述。

## 18. 下一步执行入口

恢复执行时从修复后的 S2 推送核验开始，不直接进入生产：

1. 核对当前工作区，确认暂停期间没有新增不明修改。
2. 验证修复提交已通过本地门禁，并记录新的完整 Commit SHA。
3. 推送并核对本地、远程和`ls-remote`三方SHA一致。
4. 进入真实CI、Release和生产门禁流程。

## 19. 2026-08-28 修复执行记录（进行中）

- 已完成：iwork `Enter-DeploymentMutex` 使用显式 Mutex ACL，并对构造/`WaitOne` 权限拒绝做诊断和有界重试。
- 已完成：`ProductionCoordination.psm1` 的审计 Mutex 真正使用显式 ACL，避免 helper 仅定义不生效。
- 已完成：阶段4隔离回归测试通过（当前 37 项）；此前生产阻断已可在隔离环境重现其跨身份模式。
- 待完成：DTD_nginx 看门狗、Portal 与协调模块同步修复及对应机制哈希/测试收口；iwork 修复提交、推送、真实 CI/Release、生产准入安装、预检和正式部署。
- 生产边界：在上述新证据链完成前，不重试 `029fa6f`；不复用其旧 Digest 或预检，不操作数据库、卷、Keycloak、网络和 Nginx。
