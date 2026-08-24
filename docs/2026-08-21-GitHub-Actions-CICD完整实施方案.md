# GitHub Actions、生产Runner与受控部署完整实施方案

## 1. 文档目的

本文档是iwork与DITU Portal持续集成、镜像发布、生产部署、回滚和Codex自动编排的唯一长期实施基线。

适用仓库：

- `GuChenkano/iwork`，开发与部署分支为`Keycloak`。
- `GuChenkano/DTD_nginx`，开发与部署分支为`feature/keycloak-migration`。

适用生产服务器：

- `192.168.0.97`。
- iwork工作区：`D:\DM\iwork`。
- Portal工作区：`D:\DM\DTD_nginx`。
- 生产密钥：`D:\DM\dkt-secrets.env`，不得上传GitHub或写入本方案。

最终目标：

```text
开发提交
  → GitHub托管Runner执行纯CI
  → GitHub托管Runner构建并发布不可变GHCR镜像
  → 受保护的生产Self-hosted Runner拉取指定镜像Digest
  → 获取跨仓库部署锁
  → 受控部署、健康验收和失败回滚
  → dkt-cicd Skill触发、监控并汇报全过程
```

## 2. 强制维护规则

每完成一个阶段，执行Agent必须在同一阶段的代码提交中更新本文档，直到全部阶段完成。

每次更新至少包含：

1. 阶段状态和完成日期。
2. 本地与远程提交SHA。
3. GitHub Actions运行链接和结论。
4. 实际执行的测试、静态检查和生产验收证据。
5. 新发现的问题、风险和处理方式。
6. 与原方案不同的实现及调整理由。
7. 下一阶段允许开始的条件。

状态定义：

| 状态 | 含义 |
|---|---|
| 未开始 | 尚无代码或环境变更 |
| 进行中 | 已开始开发，但验收未完成 |
| 部分完成 | 部分交付已完成，并明确列出剩余项 |
| 已阻断 | 存在不能由Agent安全解决的外部条件 |
| 已完成 | 所有验收项均有实际证据 |

禁止事项：

- 不能因为代码已提交就把阶段标为已完成。
- 不能另建一份重复总方案替代本文档。
- 不能删除或改写历史阶段证据；后续修正应追加记录。
- 不能在未更新本文档的情况下结束一个阶段。

## 3. 当前总体进度

截至2026-08-24，阶段0—3已经完成：两仓库纯CI已跑绿，三个GHCR不可变镜像已发布并按Digest复验，两个生产Self-hosted Runner已永久安装并完成自动恢复、准入钩子、私有GHCR只读拉取和OCI revision真实验收。阶段4已进入代码与隔离验证，尚未执行生产容器切换或真实生产回滚；阶段5—8尚未开始。当前已完成阶段仍为4/9，不使用缺少统一权重依据的主观百分比。

| 阶段 | 名称 | 当前状态 | 关键结果 |
|---:|---|---|---|
| 0 | 基线与纯CI | 已完成 | 两仓库GitHub托管Runner流水线已跑绿 |
| 1 | 生产Runner与Docker身份验证 | 已完成 | `DONGMING\shuju`临时Runner已完成真实只读Job，临时注册与目录已清理 |
| 2 | GHCR不可变镜像发布 | 已完成 | iwork、Portal和oauth2-proxy镜像已按完整SHA发布并按Digest复验 |
| 3 | 生产Self-hosted Runner安装 | 已完成 | 两个永久Runner在线且可自动恢复；iwork、Portal和oauth2-proxy固定Digest均完成生产只读验收 |
| 4 | iwork受控部署与回滚 | 进行中 | 工作流、固定脚本、准入安装器及隔离回滚测试已实现；生产预检和切换尚未执行 |
| 5 | Portal受控部署与回滚 | 未开始 | 高风险，晚于iwork实施 |
| 6 | 跨仓库部署锁与运维任务协调 | 未开始 | 需兼容看门狗和周重启 |
| 7 | `dkt-cicd` Skill | 未开始 | 本机已可人工使用`gh` |
| 8 | 端到端验收与观察 | 未开始 | 最终生产验收阶段 |

## 4. 已完成：阶段0——基线与纯CI

### 4.1 交付内容

iwork：

- `.github/workflows/ci.yml`
- `requirements-ci.txt`
- `tests/test_ci_workflow.py`
- `docs/CI-CD.md`

Portal：

- `.github/workflows/ci.yml`
- `requirements-ci.txt`
- `tests/test_ci_workflow.py`
- `docs/CI-CD.md`

### 4.2 安全边界

- 只使用GitHub托管Runner。
- 只授予`contents: read`。
- `actions/checkout`和`actions/setup-python`固定到40位官方Commit SHA。
- `persist-credentials: false`。
- 不使用Self-hosted Runner、SSH、生产IP或生产密钥。
- 不运行`docker compose up`或任何部署脚本。
- 不登录或发布GHCR。
- Docker构建上下文不包含`.env`文件。
- iwork测试使用内存SQLite、LocMem和内存Celery。
- Portal禁用dotenv，并只使用CI占位配置和内存SQLite。

### 4.3 提交记录

| 仓库 | 初始CI提交 | 首轮修复提交 | 阶段0验收时远程HEAD |
|---|---|---|---|
| iwork | `60c01d3` | `75699fb` | `75699fbc96d0fa90bbf2da5ab9a9a9e357ab6ce2` |
| DTD_nginx | `976bfb5` | `b24e63c` | `b24e63c6dd66f6d078108af389285e472fcbbaf5` |

### 4.4 首轮失败与修复

iwork首轮失败：

- 测试Job递归删除`env/local.env`和`env/production.env`。
- 已有安全契约测试需要读取这两个无密码配置模板。
- 结果为2项`FileNotFoundError`，其余535项通过。
- 修复为测试Job只删除可能自动加载的仓库根`.env`；构建Job在Compose解析后再删除全部`.env`。

Portal首轮失败：

- PowerShell中使用`${GITHUB_SHA}`，变量被展开为空。
- Docker标签变成`ci-portal:`并因格式无效失败。
- iwork存在相同潜在问题。
- 两仓库统一改为`$env:GITHUB_SHA`，并增加CI契约测试防回归。

### 4.5 最终验收证据

| 仓库 | Actions运行 | 结论 |
|---|---|---|
| iwork | `https://github.com/GuChenkano/iwork/actions/runs/32458415182` | success |
| DTD_nginx | `https://github.com/GuChenkano/DTD_nginx/actions/runs/32458424263` | success |

iwork通过：

- Ruff生产包检查。
- Django迁移同步检查。
- 538项pytest测试。
- 两个PowerShell脚本测试。
- Compose配置解析。
- 无密钥Docker临时镜像构建。

Portal通过：

- Ruff目标范围检查。
- Django迁移同步检查。
- Django应用测试与离线配置测试。
- Portal临时镜像构建。
- oauth2-proxy临时镜像构建。

本机工具：

- GitHub CLI `2.98.0`已安装。
- 登录账号为`GuChenkano`。
- `gh`未接管现有Git多账号推送凭据。

生产零影响证据：

- 纯CI没有SSH或部署入口。
- 生产16个容器在完成后继续运行。
- `DKT_iwork`和`DKT_iwork_alert_worker`均healthy。

### 4.6 阶段0结论

状态：已完成。

下一阶段入口：只允许开始阶段1“生产Runner与Docker用户身份可行性验证”，不得直接安装永久Runner或建设自动部署。

## 5. 阶段1——生产Runner与Docker用户身份可行性验证

### 5.1 目的

确认Runner使用哪个Windows身份、以何种常驻方式运行，才能稳定访问Docker Desktop，并避免安装完成后才发现服务会话无法操作Docker。

### 5.2 当前事实

- 服务器没有`C:\actions-runner-*`目录。
- 没有已确认的GitHub Actions Runner服务。
- `com.docker.service`当前为`STOPPED`。
- Docker容器仍在运行，说明Docker Desktop依赖`DONGMING\shuju`交互式会话或其用户上下文。
- 生产仓库当前分支正确。
- Portal服务器工作区存在未跟踪的`docker/certs/`和证书方案文档，禁止清理或覆盖。

### 5.3 实施步骤

1. 在`DONGMING\shuju`身份下创建隔离的临时Runner目录。
2. 不注册永久服务，先以前台方式运行临时Runner。
3. 验证该身份执行：

   ```powershell
   docker info
   docker ps
   docker compose version
   git ls-remote
   ```

4. 验证服务器到GitHub的直连与代理`http://192.168.1.45:8899`。
5. 验证锁屏、退出远程桌面和重新登录后的Runner与Docker行为。
6. 评估三种常驻方式：

   - `DONGMING\shuju`专用Windows服务。
   - 该账号最高权限计划任务，在登录时启动Runner。
   - 保持交互式会话的受控前台Runner，仅作为过渡。

7. 明确排除SYSTEM直接部署，除非实际测试证明SYSTEM能稳定访问同一Docker引擎。

### 5.4 验收标准

- Runner可以接收只读测试Job。
- Runner身份可以稳定执行Docker只读命令。
- 不访问或修改生产密钥、容器和工作区。
- 退出桌面会话后的行为有明确实测结论。
- 形成最终运行身份和启动方式决策。
- 清理临时注册，不遗留重复Runner。

### 5.5 完成记录

状态：已完成。

完成日期：2026-08-21。

实际提交：

| 提交 | 内容 |
|---|---|
| `eaacb1f` | 建立完整实施方案和阶段更新规则 |
| `2868137` | 增加仅允许手工触发的生产Runner只读验证工作流 |
| `6efd847` | 首轮失败后尝试切换PowerShell 7 |
| `8cbd12f` | 确认Runner无`pwsh`后改为兼容Windows PowerShell 5.1的ASCII脚本 |
| `a3abae2` | 隔离非交互Runner与服务器个人Git Credential Manager |
| `9763566` | 使用Job短期只读`GITHUB_TOKEN`验证私有仓库访问 |
| `378da50` | 写入阶段1完整证据并删除临时验证Workflow，关闭潜在Self-hosted入口 |

最终远程验证提交：

```text
9763566170b2ceb1aa3a943675f796c74caecf43
```

Actions运行：

| Run | 结论 | 发现或证据 |
|---|---|---|
| `https://github.com/GuChenkano/iwork/actions/runs/32461218793` | failure | Windows PowerShell 5.1把无BOM UTF-8中文脚本解析为乱码 |
| `https://github.com/GuChenkano/iwork/actions/runs/32461382917` | failure | Runner进程PATH中没有`pwsh`，不能依赖PowerShell 7 |
| `https://github.com/GuChenkano/iwork/actions/runs/32461527751` | failure | Docker与身份检查通过；私有仓库匿名访问触发GCM |
| `https://github.com/GuChenkano/iwork/actions/runs/32461683055` | failure | 禁用GCM后确认私有仓库必须使用短期认证 |
| `https://github.com/GuChenkano/iwork/actions/runs/32461857232` | success | 身份、Docker、Compose和私有GitHub只读访问全部通过 |
| `https://github.com/GuChenkano/iwork/actions/runs/32461792210` | success | 最终提交的Python测试、Ruff、迁移检查、PowerShell测试、Compose解析和无密钥Docker构建全部通过 |

最终成功Job实测值：

```text
Runner identity: DONGMING\shuju
Docker info: Server=29.4.3;OSType=linux;Containers=16;Running=16
Running container count: 16
Docker Compose: Docker Compose version v5.1.3
Remote Keycloak HEAD: 9763566170b2ceb1aa3a943675f796c74caecf43
```

网络验证：

- 服务器直接访问GitHub成功，`git ls-remote`约4.8秒。
- 使用`http://192.168.1.45:8899`代理同样成功，约3.0秒。
- 当前以直连作为默认路径，代理作为网络异常时的显式回退，不把代理写成镜像或业务应用的强制全局配置。

桌面会话验证：

- 实测时`DONGMING\shuju`的RDP会话为`Disc`状态并已断开约1小时。
- Docker Desktop与backend仍运行在该用户会话，16个容器保持运行，临时Runner仍能从SSH前台会话读取同一Docker引擎并完成Job。
- 因此“锁屏或断开远程桌面但不注销”可用；`Disc`状态比单纯锁屏更严格，已经覆盖锁屏对Runner和Docker的影响。
- 本阶段在RDP断开后重新建立了`DONGMING\shuju`的SSH登录会话，并在该新登录上下文中完成Runner注册、Job接收和Docker读取，证明重新登录后仍可访问同一Docker引擎。
- 2026-07-21已有生产实测证明注销该用户会使Docker Desktop随会话退出；本阶段不重复制造相同生产故障，正式规范为禁止注销承载Docker的`DONGMING\shuju`会话。

最终身份与常驻方式决策：

- 运行身份固定为`DONGMING\shuju`。
- 阶段3采用该账号的最高权限计划任务启动Runner包装器；包装器必须等待Docker API可用后再启动Runner。
- 不采用SYSTEM Runner；`com.docker.service`为Stopped，当前没有证据证明SYSTEM可稳定访问同一Docker Desktop引擎。
- 不采用需要长期保持SSH或RDP窗口的前台Runner；前台方式只用于本阶段验证。
- 不优先采用Windows服务保存该用户密码；现有S4U运维任务已经证明计划任务更符合服务器当前Docker运行模型。

实现偏差与理由：

- 原方案要求重新执行注销和登录测试。由于历史生产故障已经证明注销会停止Docker，本阶段使用“当前断开会话实测 + 既有注销故障证据”，避免重复中断16个生产容器。
- 原计划只写`git ls-remote`，实际仓库为私有仓库。最终Job使用工作流自带的短期只读Token构造内存Authorization Header，不写入GCM、文件或日志。
- 服务器Runner环境只有Windows PowerShell 5.1，验证脚本正文保持ASCII；中文仅用于Workflow和Step显示名称。
- GitHub托管Runner提示当前固定的`actions/checkout`和`actions/setup-python`提交仍基于Node.js 20，并被平台强制使用Node.js 24运行。本轮CI成功，该提示不阻断阶段1；阶段2开始前应核对官方新版本Commit并继续固定到40位SHA。

清理与生产零影响证据：

- Runner使用官方`v2.336.0` Windows x64包，SHA-256为`d59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162`。
- 每个Runner均使用`--ephemeral`，单个Job完成后自动删除`.credentials`和`.runner`并从GitHub注销。
- 最终GitHub中`dkt-prod-validation-*` Runner数量为0。
- 已核验并删除`D:\DM\cicd-validation`，没有遗留Runner服务或计划任务。
- 阶段1临时Workflow在验收后从当前分支删除，避免未来永久Runner使用相同标签时形成可由任意Ref改写的潜在入口；Actions运行和Git历史仍保留审计证据。
- 清理后仍有16个容器运行，`unhealthy`数量为0。
- 未读取`D:\DM\dkt-secrets.env`，未修改生产仓库、容器、镜像、数据库或数据卷。

下一阶段入口：允许开始阶段2“GHCR不可变镜像发布”。阶段3永久Runner安装仍必须按本阶段确定的身份和计划任务方式单独实施，不能提前建设生产部署Workflow。

## 6. 阶段2——GHCR不可变镜像发布

### 6.1 目标架构

GitHub托管Runner负责测试、构建和发布；生产Runner只拉取指定Digest并部署，不在生产服务器从源码构建。

### 6.2 镜像命名

```text
ghcr.io/guchenkano/iwork:<完整Commit SHA>
ghcr.io/guchenkano/dtd-nginx:<完整Commit SHA>
ghcr.io/guchenkano/dtd-oauth2-proxy:<完整Commit SHA>
```

部署时必须使用镜像Digest，例如：

```text
ghcr.io/guchenkano/iwork@sha256:<digest>
```

不得使用可漂移的`latest`作为生产部署依据。

### 6.3 工作流设计

两仓库新增独立`release.yml`：

- 只允许`workflow_dispatch`和受控版本Tag触发。
- 发布Job依赖现有纯CI成功。
- 仅发布Job授予`packages: write`和`contents: read`。
- 使用GitHub短期`GITHUB_TOKEN`登录GHCR。
- 输出镜像名称、Commit SHA、Digest、构建耗时和Actions链接。
- 不运行生产Compose，不连接内网服务。
- 不上传`.env`、证书、SQLite、数据库备份或中央密钥。

### 6.4 验收标准

- 三个镜像可以从GHCR按Digest拉取。
- 镜像内不存在环境文件和密钥。
- 同一Commit重复构建具有可追溯记录。
- 发布失败不影响现有生产容器。
- 保留最近若干个稳定Digest用于回滚。

阶段状态：已完成（2026-08-21）。

### 6.5 阶段2实施记录

本阶段已在两个仓库完成GHCR不可变镜像发布能力，且全程仅使用GitHub托管Runner；未连接生产服务器、未运行生产Compose、未读取生产密钥，也未修改任何数据库、Redis或Docker数据卷。

代码提交：

| 仓库 | 分支 | 提交 | 内容 |
|---|---|---|---|
| iwork | `Keycloak` | `749f1677f69d2f8c62f2563606e91935a77881cb` | 建设GHCR发布工作流、发布契约测试、Docker上下文排除规则并升级Node.js 24版Action |
| iwork | `Keycloak` | `51c1911e867c7183eef45b66b7fa6bc35ee8d676` | 按Docker Buildx官方格式修复Manifest Digest解析 |
| DTD_nginx | `feature/keycloak-migration` | `d28dd28e7948ce288cae44f7c2f7a5b03209f250` | 建设Portal与oauth2-proxy双镜像发布、独立构建上下文和发布契约测试 |
| DTD_nginx | `feature/keycloak-migration` | `90f470ad3979d3431d92eb02c5071bf9bcfc2060` | 按Docker Buildx官方格式修复Manifest Digest解析 |
| DTD_nginx | `feature/keycloak-migration` | `8a5d64900ad33b333b14f8e40fabf55cad7b9fc2` | 防止PowerShell函数捕获Docker标准输出并显式记录最终Digest |

最终Actions证据：

| 仓库 | 类型 | 结果 | Actions |
|---|---|---|---|
| iwork | 纯CI | 成功 | [32468721436](https://github.com/GuChenkano/iwork/actions/runs/32468721436) |
| iwork | GHCR Release | 成功 | [32469234186](https://github.com/GuChenkano/iwork/actions/runs/32469234186) |
| DTD_nginx | 纯CI | 成功 | [32469648291](https://github.com/GuChenkano/DTD_nginx/actions/runs/32469648291) |
| DTD_nginx | GHCR Release | 成功 | [32469839714](https://github.com/GuChenkano/DTD_nginx/actions/runs/32469839714) |

2026-08-24使用恢复登录后的GitHub CLI重新读取上述四次Actions运行，四次运行均为`completed/success`；iwork两次运行对应提交`51c1911e867c7183eef45b66b7fa6bc35ee8d676`，DTD_nginx两次运行对应提交`8a5d64900ad33b333b14f8e40fabf55cad7b9fc2`。

最终不可变镜像：

```text
ghcr.io/guchenkano/iwork@sha256:2d636c8e09f11667039e3322c6422bea870ebd577dfa1e6686c36b157009390c
ghcr.io/guchenkano/dtd-nginx@sha256:fb46bc0778bd77801ac0dec11a273dbeec2074e5ae51a21eb7897c79bdf0e9f4
ghcr.io/guchenkano/dtd-oauth2-proxy@sha256:bfccd05a210729cf2d31732360ffa1032affcb014648ef19039dfa94b0da4390
```

每个Release均完成以下闭环：

- 通过GitHub API确认同一Commit SHA的`ci.yml`已成功。
- 发布Job单独获得`packages: write`，使用短期`GITHUB_TOKEN`登录GHCR。
- 以完整40位Commit SHA作为唯一标签，不生成或使用`latest`。
- 已存在的SHA标签只允许读取并核对OCI revision，不执行覆盖推送。
- 新镜像推送后解析Manifest Digest，再按Digest拉取并校验`org.opencontainers.image.revision`。
- Actions摘要记录Commit、镜像、Digest、是否复用、耗时、CI链接和Release链接。

本地与CI验证：

- iwork：`539 passed`；两个PowerShell同步任务测试均为0项失败；Ruff、迁移检查、Compose解析和`git diff --check`通过。
- DTD_nginx：Django应用测试`72 passed`；离线配置测试`90 passed, 2 skipped, 37 subtests passed`；Ruff、迁移检查、YAML解析和`git diff --check`通过。
- 两仓库普通CI均完成Windows测试与Ubuntu无密钥Docker构建。
- Docker构建上下文新增环境文件、数据库、私钥、备份、开发脚本和本地Agent目录排除；oauth2-proxy子上下文只允许Dockerfile进入。

问题与处理：

- 首轮Release使用错误的顶层`.Digest`模板，镜像构建和推送已完成，但推送后无法解析Digest，工作流因此失败。根据Docker Buildx官方文档确认格式对象只公开`.Name`、`.Manifest`和`.Image`，最终修正为`.Manifest.Digest`并重新完成CI与Release。
- Portal发布函数最初把Docker标准输出捕获进函数返回值，发布与校验虽成功，但日志不能直接检索两个Digest。最终将Docker输出发送到Host流，并显式打印已验证镜像的Digest。
- 失败运行只发生在GitHub托管Runner，未连接或改变生产环境。失败Commit对应的SHA镜像仅作为历史审计记录，不作为阶段3及后续部署输入。

下一阶段入口：允许开始阶段3“生产Self-hosted Runner安装”。阶段3只能建设Runner运行基础和最小GHCR拉取能力，不能提前执行阶段4或阶段5的生产应用部署。

## 7. 阶段3——生产Self-hosted Runner安装

### 7.1 目录和标签

建议目录：

```text
D:\DM\actions-runner\iwork
D:\DM\actions-runner\portal
D:\DM\cicd-locks
D:\DM\cicd-state
```

标签：

```text
iwork: self-hosted, windows, dkt-prod, iwork
portal: self-hosted, windows, dkt-prod, portal
```

### 7.2 安全要求

- 只接受受保护的`workflow_dispatch`部署Job。
- 禁止任何`pull_request`或`pull_request_target`运行生产Runner。
- Runner工作目录与`D:\DM\iwork`和`D:\DM\DTD_nginx`分离。
- Runner不持有个人PAT；注册Token仅用于注册。
- 服务器不需要安装`gh`。
- 生产密钥只保留在`D:\DM\dkt-secrets.env`。
- Runner服务账户采用阶段1验证通过的身份。
- 两个Runner必须共用服务器级部署锁。

### 7.3 验收标准

- 两个Runner在GitHub页面显示Idle。
- 服务或计划任务重启后自动恢复。
- 能拉取私有GHCR镜像，但不能修改仓库和GitHub设置。
- 无权运行来自PR的代码。
- 不修改现有生产仓库工作区。

### 7.4 2026-08-24实际实施记录

已完成：

- iwork Runner安装在`D:\DM\actions-runner\iwork`，名称为`DTDSERVER-iwork-01`，标签为`dkt-prod,iwork`。
- Portal Runner安装在`D:\DM\actions-runner\portal`，名称为`DTDSERVER-portal-01`，标签为`dkt-prod,portal`。
- 两个Runner均使用官方Windows x64 `2.336.0`，安装包SHA-256为`d59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162`。
- 计划任务为`\DITU\GitHub-Runner-iwork`和`\DITU\GitHub-Runner-portal`，使用`DONGMING\shuju`、S4U、最高权限运行，并包含系统启动、用户登录和每分钟重复恢复触发器。
- 包装器在Docker可用前最长等待30分钟；Runner Listener意外正常退出时返回非零退出码，由计划任务最迟约一分钟恢复。
- 自动恢复实测通过：iwork Listener从PID `8588`恢复为`25588`；Portal Listener从PID `3700`恢复为`25048`，最终各只有一个Listener。
- 2026-08-24再次只读复核：两个Listener仍分别为PID `25588`和`25048`，两个计划任务均为`Running`，Docker共有16个容器且`unhealthy=0`。
- Runner使用独立工作目录，没有覆盖生产代码目录。`D:\DM\iwork`保持干净；`D:\DM\DTD_nginx`原有工作区变更保持原样，没有被Runner清理或覆盖。
- 两仓库最终只读验收Workflow已经提交并推送：iwork为`0d92ebb71dace965eb135a0df59007f869d98a0f`，Portal为`3bc78f99e48c8b28d5f974d9bf1fc76d7ebd22ab`。
- 两仓库GitHub托管Runner CI均成功：iwork运行`32687841745`成功，Portal运行`32686181241`成功。
- 生产Runner准入钩子在Job步骤执行前固定校验`workflow_dispatch`、仓库、分支、Workflow路径和actor `GuChenkano`。
- 仓库Actions策略只允许GitHub官方Action并要求固定完整Commit SHA；Runner不保存个人PAT，注册Token仅在注册时短暂使用。

问题定位与最终解决：

- iwork只读验收运行`32687141318`和Portal只读验收运行`32687133658`均已通过身份、准入钩子、独立工作区和Docker检查。
- 两次运行均在登录GHCR时失败，原始错误为`Get "https://ghcr.io/v2/": denied: denied`。
- 初始原因包含GHCR Package尚未向对应仓库授予GitHub Actions访问权限，不是Runner、Docker或生产应用故障。
- 2026-08-24 11:56本机`gh auth status`确认`GuChenkano`令牌失效，GitHub API返回`401 Unauthorized`；12:03完成设备授权并增加`write:packages` Scope后，三个私有包均可读取且已关联预期仓库。
- 授权恢复后重新运行iwork `32688946753`和Portal `32688944735`，身份、准入钩子、独立工作区和Docker检查再次通过，但`docker login ghcr.io`仍返回`denied: denied`，证明本机CLI授权不是生产Workflow失败原因。
- 用户完成Package网页设置后再次运行iwork `32694845677`和Portal `32694846959`，两次Job日志均明确显示`GITHUB_TOKEN Permissions: Packages: read`，但GHCR登录仍被拒绝；等待约45秒后单独重跑iwork `32694985097`仍失败，已排除仓库默认Workflow Token权限和短暂传播延迟。
- GitHub官方REST OpenAPI只提供包和版本的读取、删除、恢复接口；公开GraphQL Mutation只发现`deletePackageVersion`，没有修改个人GHCR Package Actions访问关系的接口，因此最终通过Package网页的`Manage Actions access`完成授权。
- 三个私有Package均向对应仓库授予`Write`角色：发布Job仍用`packages: write`，生产验收与未来部署Job继续收窄为`packages: read`。没有使用具备删除和权限管理能力的`Admin`，Package也未改为公开。
- 授权完成后确认Workflow短期`GITHUB_TOKEN`可访问GitHub API并可申请具体仓库的GHCR pull Scope；但Docker对通用`/v2/`的`docker login`探测仍返回`denied`。最终不再依赖通用登录探测，而是在`RUNNER_TEMP`内生成仅本次Job使用的隔离Docker配置，直接按完整Digest拉取具体仓库镜像，并在`finally`中删除临时配置。
- Windows PowerShell 5.1会破坏Docker Go模板中的嵌套引号，导致OCI revision读取失败；Workflow改为读取`{{json .Config.Labels}}`并使用`ConvertFrom-Json`取得`org.opencontainers.image.revision`，未降低校验强度。
- 用于定位授权边界的`[DEBUG-ghcr-auth]`步骤在问题解决后已从iwork Workflow删除，并增加契约测试防止重新引入；正式短期令牌、隔离Docker配置、固定Digest和revision校验均保留。

最终验收证据：

- iwork首次完整只读验收运行[`32696526599`](https://github.com/GuChenkano/iwork/actions/runs/32696526599)成功，固定Digest拉取和OCI revision均通过。
- Portal最终只读验收运行[`32697834827`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32697834827)成功，用时1分15秒，Portal与oauth2-proxy两个固定Digest均成功拉取并通过OCI revision校验。
- 清理临时诊断后的iwork运行[`32698068926`](https://github.com/GuChenkano/iwork/actions/runs/32698068926)成功，用时16秒，证明正式验收链路不依赖诊断步骤。
- 运行后只读复核服务器：iwork Listener PID为`25588`，Portal Listener PID为`25048`，各只有一个实例；两个计划任务均为`Running`。
- Docker共有16个运行容器，14个配置健康检查的容器全部为`healthy`，其余2个未配置healthcheck但保持运行；没有启动、替换或重建生产容器。
- `D:\DM\iwork`工作区干净；`D:\DM\DTD_nginx`只保留既有未跟踪的`docker/certs/`和`docs/待办方案/2026-08-21-DITU-Portal证书重签实施计划.md`，Runner没有清理或覆盖生产工作区。

阶段状态：已完成。阶段4已进入代码与隔离验证阶段，但尚未切换生产容器。

## 8. 阶段4——iwork受控部署与自动回滚

### 8.1 已实现的工作流输入

`.github/workflows/deploy-iwork.yml`只允许`workflow_dispatch`，目标环境在Workflow中固定为`production-iwork`，不接受环境名或任意Shell命令输入。实际输入为：

- `image_digest`：完整`sha256:` Digest，必填。
- `expected_revision`：镜像OCI revision对应的40位Commit SHA，必填。
- `apply`：默认`false`；关闭时会拉取并验证候选Digest，但不重建、重启或替换运行容器。镜像缓存会增加候选镜像，因此不称为严格零写入。
- `run_migrations`：默认`false`。
- `change_description`：1—500字符变更说明。
- `confirmation`：预检为`PREFLIGHT IWORK`；无迁移部署为`DEPLOY IWORK`；迁移部署为`DEPLOY IWORK WITH MIGRATIONS`。

每次Actions重试使用`GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT`作为独立部署ID，避免覆盖上一次状态、备份和回滚标签。

### 8.2 实际安全边界与平台限制

- 当前私有个人仓库套餐不能启用`production-iwork` Environment Required Reviewer，也不能启用`Keycloak`分支保护。因此`environment: production-iwork`目前只是环境标识，不能视为GitHub侧人工审批。
- 补偿控制由服务器准入钩子提供：只接受`workflow_dispatch`、`GuChenkano/iwork`、`Keycloak`、固定Workflow名称和路径、actor `GuChenkano`，并要求`GITHUB_SHA`严格等于人工批准的完整40位SHA。
- 每批准一个新的Workflow提交，必须在Runner空闲时使用`Install-IworkProductionDeployment.ps1 -ApprovedHeadSha <SHA>`重新安装准入策略。重新运行Runner恢复安装器时保留已有阶段4钩子，禁止退回smoke-only策略。
- Workflow固定校验服务器`D:\DM\cicd-tools\Invoke-IworkProductionDeployment.ps1`的SHA-256；服务器脚本和Workflow任一方变化都会拒绝执行。
- `.gitattributes`固定两个阶段4生产PowerShell脚本为LF，脚本本身保留UTF-8 BOM，避免Windows检出换行转换导致固定SHA-256漂移，同时保证Windows PowerShell 5.1正确读取中文。
- Workflow只授予`actions: read`和`packages: read`，使用短期`GITHUB_TOKEN`和`RUNNER_TEMP`隔离Docker配置，按完整Digest拉取后删除认证文件；不checkout、不build、不访问生产Git工作区。
- 候选`expected_revision`必须严格等于当前被服务器准入钩子批准的`GITHUB_SHA`，随后再核对镜像OCI revision；因此不能利用合法旧Digest把生产降级到未批准的历史提交。
- 部署前通过GitHub Actions API分别确认同一Commit存在成功的`ci.yml`和`release.yml`运行；查询失败、没有成功运行或令牌权限不足均拒绝继续。

### 8.3 已实现的部署与回滚步骤

1. 固定脚本执行生产身份、生产Compose、生产环境文件、中央密钥、状态目录和锁目录预检。
2. 检查看门狗脚本确实声明`Global\DKT-Docker-Recovery`；周重启或既有iwork维护标记存在时拒绝开始。
3. 获取`Global\DKT-Production-Deploy`、`Global\DKT-Docker-Recovery`和`D:\DM\cicd-locks\production-deploy.lock`三层互斥。
4. 保存两个现有容器的容器ID、配置镜像、镜像ID、状态、健康状态和重启次数，并建立本地只读回滚标签；回滚不依赖旧GHCR Digest仍可下载。
5. `run_migrations=true`时先备份`iwork_system`和`iwork_local`，记录SHA-256，并把备份ACL收窄到Runner账号、SYSTEM和管理员。
6. 创建20分钟有效的`iwork-deployment.json`维护标记。
7. 生成只包含镜像引用和迁移开关的临时Compose覆盖，运行`docker compose config --quiet`。
8. 使用`up -d --no-build --no-deps iwork alert-worker`，只切换`DKT_iwork`和`DKT_iwork_alert_worker`，不执行`down`，不触碰共享基础设施或物理卷。
9. 自动验证两个容器healthy、实际镜像引用、`manage.py check --deploy`、容器内HTTP 200和Alert Worker `pong`。
10. 任一候选验收失败时，用本地回滚标签恢复两个旧镜像，并再次验证镜像引用、应用HTTP、Django检查和Alert Worker；回滚验证失败时状态明确记录为`rollback_failed`。
11. 无论成功或失败，都在`finally`释放本进程实际创建的维护标记、文件锁和两个Mutex；未取得文件所有权的并发进程不得删除其他部署的锁或维护标记。状态文件保留Run ID、候选镜像、旧镜像ID、迁移备份和最终结果。

### 8.4 当前生产基线与候选镜像限制

2026-08-24只读基线：

| 项目 | 当前生产值 |
|---|---|
| 服务器工作区HEAD | `8e4e74a4ba1eb171b3ad509a486716011d2afe80` |
| `DKT_iwork`配置镜像 / image ID | `iwork-iwork` / `sha256:b9b3410e4b14c79dd58765ef383fedf3c1fa8acb8306df39ae368c4769811125` |
| `DKT_iwork_alert_worker`配置镜像 / image ID | `iwork-alert-worker` / `sha256:c9d28284e3ce0334477e8873cca31e45213a179f08b2ddd9834c3a52bea093a8` |
| Compose项目与服务 | `iwork`；`iwork`、`alert-worker` |

阶段2旧GHCR镜像revision为`51c1911e867c7183eef45b66b7fa6bc35ee8d676`，缺少生产已经部署的`96cd508`和`8e4e74a`两次SSE无感续订修复，禁止部署。阶段4实现提交通过纯CI后必须重新发布当前Commit镜像并使用新Digest。

### 8.5 尚未完成的真实验收

- 阶段4实现尚未提交和推送，纯CI运行链接、新GHCR Digest与Release运行链接待生成。
- `production-iwork` Environment尚未创建；创建后仍没有Required Reviewer保护，这是已接受但必须持续披露的平台风险。
- 服务器准入脚本尚未按阶段4实现提交SHA安装。
- 生产`apply=false`真实预检尚未执行。
- 生产容器尚未替换、重启或重建，数据库和物理卷未发生变更。
- 真实登录页面、业务API、SSE无感续订、通知SSE及告警投递仍需在候选切换后人工验收；当前自动脚本的HTTP检查不能替代这些认证态验收。
- 看门狗尚未识别新的`production_deployment`维护标记；部署期间共享恢复Mutex可阻止看门狗和周重启执行恢复，但仍可能产生短暂健康告警。该兼容改造归入阶段6，在此之前作为已知风险观察。
- 迁移失败时只自动回滚应用镜像，不自动还原数据库。`run_migrations=true`只允许用于已审查的expand/contract兼容迁移；备份用于受控人工恢复，禁止脚本自动覆盖生产数据库。

### 8.6 阶段验收标准

- 部署只影响iwork两个应用容器。
- 候选失败能自动恢复两个部署前本地镜像，并完成回滚后应用复验。
- SSE自动重连且无持续403或503。
- 数据库、Redis和历史数据不重建。
- 看门狗不会在合法部署锁持有期间执行恢复。
- Actions摘要包含候选Digest、旧镜像ID、部署ID、耗时和验收结果。
- 生产预检、真实切换、认证态业务验收和至少一次受控回滚证据全部具备后，阶段4才能标记为已完成。

### 8.7 2026-08-24本地实施证据

- `python -m pytest -q tests\test_production_runner_stage3.py tests\test_production_deployment_stage4.py`：16项通过。
- `python -m pytest tests\ -q`：557项通过；仅保留本机`requests`依赖版本告警，不影响测试结论。
- Ruff按CI口径检查`iwork`及阶段3/4测试：通过。
- Windows PowerShell 5.1语法解析：三个生产Runner/部署脚本全部通过。
- 四个GitHub Actions YAML文件解析：通过。
- 使用非生产占位密钥执行`docker compose --env-file env\local.env config --quiet`：通过。
- `git diff --check`：通过。
- 隔离伪Docker测试已覆盖：只读预检不切换容器、部署前容器基线、双服务成功切换、候选验收失败后双镜像回滚及回滚后应用复验、回滚失败显式报警、迁移前数据库备份与SHA-256、备份ACL、共享恢复锁和Runner准入钩子保留。

阶段状态：进行中。代码、安装器和隔离测试已实现；生产预检、生产切换、真实健康验收和真实回滚尚未执行。

## 9. 阶段5——Portal高风险受控部署与回滚

Portal是全系统认证网关，必须在iwork自动部署稳定后单独实施。

### 9.1 部署前基线

- 记录Portal、Authorizer、oauth2-proxy和Nginx当前镜像Digest。
- 导出Nginx有效配置。
- 记录OIDC discovery、登录回调和权限拒绝页基线。
- 检查数据库迁移计划，必要时执行经批准的PostgreSQL备份。
- 保留服务器未跟踪证书与文档，不清理工作区。

### 9.2 候选切换

1. 拉取指定镜像Digest。
2. 启动隔离候选Portal和Authorizer实例。
3. 验证Django、数据库、Keycloak、Authorizer和OIDC。
4. 运行`nginx -t`。
5. 原子替换Nginx配置并执行graceful reload。
6. 验证Portal及所有已注册应用的页面、API和静态资源。
7. 验证登录、退出、Remote-User、Remote-Groups和应用授权。
8. 失败时恢复旧Nginx配置和旧镜像Digest。

首次自动部署不得修改：

- Keycloak Realm和Client。
- TLS证书。
- Docker网络和物理卷。
- Portal数据库。
- 应用slug和既有路由。

### 9.3 验收标准

- 新旧入口和OIDC行为符合当前生产规范。
- Portal、Authorizer、oauth2-proxy和Nginx均healthy。
- 六个应用真实登录后可用，不能以单纯302代替成功。
- 回滚演练通过。
- 不影响Keycloak用户、组和客户端关系。

阶段状态：未开始。

## 10. 阶段6——跨仓库部署锁与运维任务协调

### 10.1 全局锁

建议路径：

```text
D:\DM\cicd-locks\production-deploy.lock
```

锁内容：

- 仓库和服务。
- Workflow Run ID。
- Commit SHA和镜像Digest。
- 触发账号。
- 开始时间、过期时间和当前阶段。

### 10.2 协调规则

- iwork部署期间Portal必须等待，反之亦然。
- 部署流程必须识别Docker周重启和看门狗维护标记。
- Docker周重启进行中时不得开始部署。
- 部署开始后看门狗应在合法维护时间内放行。
- 超过维护期限且应用未恢复时，看门狗应恢复应用或报警。
- 锁文件超时不能直接删除，必须先检查原Run和进程状态。
- 工作流无论成功、失败还是取消，都必须在`finally`逻辑中安全释放锁。

### 10.3 验收标准

- 并发触发两个部署时只有一个执行。
- Runner异常退出后不会永久死锁。
- 周重启、看门狗和部署任务不会重复操作同一容器。
- 所有锁事件都有日志和Run ID可追溯。

阶段状态：未开始。

## 11. 阶段7——`dkt-cicd` Skill

### 11.1 安装位置

```text
C:\Users\lipengfei\.agents\skills\dkt-cicd
```

### 11.2 设计原则

- 复用本机已登录的`gh`，不读取`.git-credentials`。
- 不保存GitHub Token、生产密码、Cookie或私钥。
- Skill只负责参数校验、触发、监控和汇报；真实CI/CD逻辑留在Workflow。
- 查询、测试和构建无需生产确认。
- 生产部署必须在触发前展示服务、分支、Commit、镜像Digest和环境并请求确认。
- Portal部署要求更高等级确认。

### 11.3 功能

```text
查看CI状态
查看失败日志
运行iwork测试
构建iwork镜像
构建Portal镜像
部署iwork
部署Portal
查看生产容器状态
回滚上一次部署
```

主要调用：

```powershell
gh workflow run
gh run list
gh run watch
gh run view --log-failed
```

### 11.4 验收标准

- 自然语言可以准确路由到正确仓库和Workflow。
- queued、in_progress、success和failure状态不会误报。
- 能输出Run链接、失败步骤、Commit、Digest和耗时。
- 部署确认不可绕过。
- Token不会出现在日志、参数或文件中。

阶段状态：未开始。

## 12. 阶段8——端到端验收与稳定观察

按以下顺序执行，不得跳级：

1. 通过Skill手工触发iwork纯CI并监控到成功。
2. 发布iwork GHCR镜像，不部署。
3. 生产Runner只拉取并inspect镜像，不启动。
4. 在批准的维护窗口部署iwork。
5. 人工注入健康检查失败，验证自动回滚。
6. 验证Runner服务或计划任务重启恢复。
7. Portal只构建、只发布、只拉取，不部署。
8. 在独立维护窗口部署Portal候选实例。
9. 验证Portal真实登录、应用授权、API和回滚。
10. 并发触发iwork和Portal部署，验证全局锁。
11. 验证看门狗和Docker周重启协调。
12. 连续观察24小时：容器健康、重启次数、认证错误、SSE、警报Worker和Actions失败率。

最终完成条件：

- 所有阶段均为已完成。
- 两仓库文档与实际Workflow一致。
- 生产部署和回滚各至少成功演练一次。
- Runner重启恢复通过。
- Skill自然语言场景验收通过。
- 24小时观察无持续异常。

阶段状态：未开始。

## 13. 全局风险控制

| 风险 | 控制措施 |
|---|---|
| Docker仅在交互用户上下文可用 | 阶段1先验证身份和常驻方式，不直接装SYSTEM Runner |
| 两仓库同时部署 | 使用服务器级共享锁，不只依赖GitHub concurrency |
| 生产服务器源码构建不稳定 | GitHub托管Runner构建GHCR不可变镜像，生产只拉取Digest |
| Portal故障影响所有应用 | 候选实例、Nginx原子切换、真实登录验收和自动回滚 |
| 看门狗误判合法维护 | 统一维护标记、超时和Run ID协议 |
| 生产密钥泄露 | 密钥只留服务器，不传GitHub、不写日志、不进入镜像 |
| PR代码接触生产Runner | 生产Runner禁止PR和pull_request_target触发 |
| Runner覆盖服务器工作区 | 使用独立Runner工作目录，禁止clean/reset生产仓库 |
| 可变镜像无法追溯 | 生产仅使用完整Digest，不使用latest |
| 自动回滚破坏数据 | 回滚只切换应用镜像，不回滚或重建共享数据库和卷 |

## 14. 下一步

阶段3已经完成且不存在外部授权阻断。下一步是阶段4“iwork受控部署与自动回滚”，但本次不自动实施阶段4。

阶段4开始前必须先形成可审查的最小实施切片：

1. 盘点iwork当前生产Compose、部署脚本、看门狗维护标记和服务器级部署锁协议，只读记录现状。
2. 明确Workflow输入只接受固定镜像Digest、目标环境、迁移开关和变更说明，不接受任意Shell命令。
3. 先实现“预检与生成部署计划”路径，验证Digest来源、CI/release状态、Compose解析、当前容器和回滚Digest，不替换生产容器。
4. 再实现只更新`DKT_iwork`和`DKT_iwork_alert_worker`的部署与健康检查；MySQL、Redis、PostgreSQL、Keycloak和共享卷必须排除。
5. 设计可重复的失败注入，在隔离或明确批准的维护窗口验证自动恢复旧Digest，禁止通过破坏数据库或删除卷测试回滚。
6. 阶段4代码、测试和预检通过后，先更新本文档为“实施中”；只有真实部署和回滚验收均有证据后才标记“已完成”。

阶段4继续沿用以下边界：

- Package保持私有，发布Job使用`packages: write`，生产部署Job使用`packages: read`。
- 生产Runner不保存个人PAT，不运行PR代码，不读取或提交`D:\DM\dkt-secrets.env`。
- 生产镜像只允许完整Digest，不允许`latest`或其他可漂移标签。
- 不清理或重置`D:\DM\iwork`和`D:\DM\DTD_nginx`工作区。
- 未获得明确部署授权前，只能建设、测试和执行只读预检，不能替换生产容器。
