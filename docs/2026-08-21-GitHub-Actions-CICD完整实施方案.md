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

截至2026-08-28，阶段0—7的既有交付仍保留：两仓库纯CI、GHCR不可变镜像、生产Self-hosted Runner、iwork与Portal受控部署和回滚能力均已有隔离或历史生产证据；阶段6的跨仓库部署锁与运维任务协调也已完成隔离验收。阶段8本轮已以远程 HEAD `285da66c2fcc04b2477a68a7617a7e24cce4406b` 完成真实 CI、Release、生产准入、`apply=false` 预检和正式部署，生产切换成功且两容器健康。真实账号浏览器登录验收仍按用户明确决定记录为风险豁免，不将其表述为实际验收通过；24小时稳定观察尚未完成，阶段8继续进行中。

| 阶段 | 名称 | 当前状态 | 关键结果 |
|---:|---|---|---|
| 0 | 基线与纯CI | 已完成 | 两仓库GitHub托管Runner流水线已跑绿 |
| 1 | 生产Runner与Docker身份验证 | 已完成 | `DONGMING\shuju`临时Runner已完成真实只读Job，临时注册与目录已清理 |
| 2 | GHCR不可变镜像发布 | 已完成 | iwork、Portal和oauth2-proxy镜像已按完整SHA发布并按Digest复验 |
| 3 | 生产Self-hosted Runner安装 | 已完成 | 两个永久Runner在线且可自动恢复；iwork、Portal和oauth2-proxy固定Digest均完成生产只读验收 |
| 4 | iwork受控部署与回滚 | 已完成 | 真实切换、自动验收和唯一一次受控回滚演练均成功；浏览器验收由用户豁免 |
| 5 | Portal受控部署与回滚 | 已完成 | v3回滚演练与最终生产切换成功；真实账号浏览器验收由用户明确风险豁免 |
| 6 | 跨仓库部署锁与运维任务协调 | 已完成 | 统一协调模块、运维互斥、生产准入安装、Runner smoke及只读预检均通过 |
| 7 | `dkt-cicd` Skill | 已完成 | 固定路由、状态监控、日志脱敏、Digest提取和生产两段确认已通过离线及真实只读验收 |
| 8 | 端到端验收与观察 | 进行中 | `285da66c`已完成真实CI/Release、生产准入、预检和正式切换；当前待24小时稳定观察，真实账号浏览器验收按风险豁免记录 |

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

2026-08-25后续状态勘误：上述“尚未切换”是阶段3完成当时的下一阶段状态，不代表当前进度。阶段4后续已完成真实生产切换、自动验收和唯一一次受控回滚演练，证据见第8节。

## 8. 阶段4——iwork受控部署与自动回滚

### 8.1 已实现的工作流输入

`.github/workflows/deploy-iwork.yml`只允许`workflow_dispatch`，目标环境在Workflow中固定为`production-iwork`，不接受环境名或任意Shell命令输入。实际输入为：

- `image_digest`：完整`sha256:` Digest，必填。
- `expected_revision`：镜像OCI revision对应的40位Commit SHA，必填。
- `apply`：默认`false`；关闭时会拉取并验证候选Digest，但不重建、重启或替换运行容器。镜像缓存会增加候选镜像，因此不称为严格零写入。
- `rollback_drill`：默认`false`；仅用于一次性受控回滚演练，要求`apply=true`且`run_migrations=false`。
- `run_migrations`：默认`false`。
- `change_description`：1—500字符变更说明。
- `confirmation`：预检为`PREFLIGHT IWORK`；无迁移部署为`DEPLOY IWORK`；迁移部署为`DEPLOY IWORK WITH MIGRATIONS`；一次性演练为`ROLLBACK DRILL IWORK ONCE`。

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

### 8.5 风险豁免与已知边界

- 真实账号登录、退出、生产详情页面、实时SSE无感续订和通知SSE原计划由已信任当前自定义证书的外部Edge人工验收。用户于2026-08-25明确决定跳过该项；本文记录为风险豁免，不将其表述为“验收通过”。现有自动化页面、API和SSE检查结果继续保留。
- 首轮正式部署实际执行了旧镜像恢复，但PowerShell 5.1误把Compose正常stderr进度判为错误，使状态文件记录为`rollback_failed`。修复版随后通过隔离回归测试及唯一一次受控生产回滚演练，已形成`rolled_back / RollbackSucceeded=true`证据，详见8.11节。
- `production-iwork` Environment已经创建，但实际`protection_rules=[]`且`can_admins_bypass=true`；服务器完整SHA准入仍是当前主要补偿控制。
- 阶段4完成时，看门狗尚未识别新的`production_deployment`维护标记；该风险已在阶段6通过双Schema维护标记校验、共享恢复Mutex和隔离回归测试关闭。
- 迁移失败时只自动回滚应用镜像，不自动还原数据库。`run_migrations=true`只允许用于已审查的expand/contract兼容迁移；备份用于受控人工恢复，禁止脚本自动覆盖生产数据库。

### 8.6 阶段验收标准

- 部署只影响iwork两个应用容器。
- 候选失败能自动恢复两个部署前本地镜像，并完成回滚后应用复验。
- SSE自动重连且无持续403或503。
- 数据库、Redis和历史数据不重建。
- 看门狗不会在合法部署锁持有期间执行恢复。
- Actions摘要包含候选Digest、旧镜像ID、部署ID、耗时和验收结果。
- 生产预检、真实切换、自动化业务验收和一次受控回滚证据全部具备，并记录真实账号浏览器验收风险豁免后，阶段4才能标记为已完成。

### 8.7 2026-08-24本地实施证据

- `python -m pytest -q tests\test_production_runner_stage3.py tests\test_production_deployment_stage4.py`：18项通过。
- `python -m pytest tests\ -q`：559项通过；仅保留本机`requests`依赖版本告警，不影响测试结论。
- Ruff按CI口径检查`iwork`及阶段3/4测试：通过。
- Windows PowerShell 5.1语法解析：三个生产Runner/部署脚本全部通过。
- 四个GitHub Actions YAML文件解析：通过。
- 使用非生产占位密钥执行`docker compose --env-file env\local.env config --quiet`：通过。
- `git diff --check`：通过。
- 隔离伪Docker测试已覆盖：预检不切换容器、部署前容器基线、双服务成功切换、Compose退出码为0时允许stderr正常进度、候选验收失败后双镜像回滚及回滚后应用复验、回滚失败显式报警、迁移前数据库备份与SHA-256、备份ACL、共享恢复锁和Runner准入钩子保留。

### 8.8 首轮真实预检阻断与修复

- 首轮阶段4实现提交为`b9bb73c6f2b84ca27b3a11047def905c96f417f6`；纯CI运行[`32703867226`](https://github.com/GuChenkano/iwork/actions/runs/32703867226)成功。
- 同一提交GHCR发布运行[`32704184174`](https://github.com/GuChenkano/iwork/actions/runs/32704184174)成功，新镜像Digest为`sha256:a0174a09a8eef63a7984323e5bb32b914bf5b7c61afbfd2d7334d3c667989e7f`，OCI revision复验一致。
- 已创建`production-iwork` Environment；实际`protection_rules=[]`且`can_admins_bypass=true`，再次确认当前套餐没有Required Reviewer保护。
- 服务器曾按`b9bb73c6`安装准入钩子和固定部署脚本，脚本SHA-256为`1475674284b4e5a270628976e62f657bb6a5f0dd8ab9141213664c2247679ff3`；安装时Runner为Online、Idle且没有`Runner.Worker.exe`。
- 首轮真实预检运行[`32704619681`](https://github.com/GuChenkano/iwork/actions/runs/32704619681)在16秒内失败。准入钩子与Environment已生效，但Windows PowerShell 5.1把GitHub Actions生成的无BOM临时脚本按系统代码页解析，Workflow内联中文字符串导致ParserError。
- 失败发生在首条Docker命令之前：没有拉取候选镜像，没有创建部署状态/锁/维护标记，没有重建、重启或替换任何生产容器。
- 修复方式是只把`run: |`内联PowerShell源码改为ASCII；Workflow名称、输入说明和步骤名称仍保留中文，服务器固定脚本继续使用UTF-8 BOM输出中文。新增YAML结构级回归测试，直接断言Windows PowerShell 5.1内联脚本`isascii()`，能够稳定复现并防止同类编码回归。
- 第一轮编码修复提交`f8378d872e40b835f25636a990f3706b12e5210a`的纯CI运行[`32705048361`](https://github.com/GuChenkano/iwork/actions/runs/32705048361)、GHCR发布运行[`32705409027`](https://github.com/GuChenkano/iwork/actions/runs/32705409027)和生产预检运行[`32705882615`](https://github.com/GuChenkano/iwork/actions/runs/32705882615)均成功；候选Digest为`sha256:9c45624b70a4f3eefc15e4e45761fe5a42a34266d69b3728d86704af72d4f2b7`。

### 8.9 首轮正式部署失败、恢复与修复

- 正式部署运行[`32710436612`](https://github.com/GuChenkano/iwork/actions/runs/32710436612)使用`apply=true / run_migrations=false`，在`docker compose up`输出`Container DKT_iwork Recreate`时被Windows PowerShell 5.1误判为终止异常。
- 根因是固定脚本全局使用`ErrorActionPreference=Stop`，而Docker Compose会把正常进度写入stderr；PowerShell 5.1在原生命令退出码仍为0时先产生`NativeCommandError`。同一误判也发生在自动回滚命令，因此状态文件为`rollback_failed`。
- 实际运行结果是两个旧镜像均已恢复：Web为`sha256:b9b3410e4b14c79dd58765ef383fedf3c1fa8acb8306df39ae368c4769811125`，Alert Worker为`sha256:c9d28284e3ce0334477e8873cca31e45213a179f08b2ddd9834c3a52bea093a8`；两容器均`healthy`、重启0次，锁与维护标记已清除。
- 修复提交`76b304acb92b4814f642a5ba98bf8d293ba855c9`只在Docker原生命令调用期间暂时使用`ErrorActionPreference=Continue`并保存退出码，恢复调用方策略后只按退出码判定成败；新增真实Windows PowerShell 5.1原生stderr回归适配器，修复前稳定失败、修复后通过。

### 8.10 修复版发布、正式切换与自动验收

- 修复提交纯CI运行[`32711175088`](https://github.com/GuChenkano/iwork/actions/runs/32711175088)成功；GHCR发布运行[`32711588818`](https://github.com/GuChenkano/iwork/actions/runs/32711588818)成功，Digest为`sha256:428468d2b6f75de18d0a8b7c046634e76818b24fcbddb34abfe188b27e8c2c59`。
- 服务器在Runner空闲、无`Runner.Worker`、无部署锁和周重启标记时重新固定`ApprovedHeadSha=76b304ac...`；固定部署脚本SHA-256为`f31cb93b69dcb755fa82996078f7713cfb29889a266faf705d174c66ba5b5a25`。
- 修复版生产预检运行[`32711975445`](https://github.com/GuChenkano/iwork/actions/runs/32711975445)成功；正式部署运行[`32712304952`](https://github.com/GuChenkano/iwork/actions/runs/32712304952)成功，状态文件为`deployed`。
- `DKT_iwork`与`DKT_iwork_alert_worker`均使用上述完整Digest，底层image ID均为`sha256:3d26cdfa20c07deb64573290c960eb61f2776a22c433e65757d7b75b3efb07f2`，两容器`healthy`、重启0次，OCI revision严格等于`76b304ac...`。
- Django `check --deploy`无错误，保留4项既有反向代理安全提示；Alert Worker和Realtime Worker均返回`pong`。实时数据、Flow概览、产品概览API返回200，生产详情两类页面返回200，实时SSE立即返回`dashboard_update`，通知SSE在可信只读测试身份下返回200和`retry: 3000`，无身份时稳定返回JSON 401。
- 新Portal入口返回302到`auth.dituportal.dongming.local/realms/ditu`，回调仍为新Portal；Nginx健康探针返回204。部署后日志未发现Traceback、500或503。
- 其余14个容器保持原启动时间和健康状态；MySQL、Redis、PostgreSQL、Keycloak、物理卷及服务器生产Git工作区均未重建或切换。部署锁、iwork维护标记和周重启标记均不存在。
- 本验收证据将在部署后以独立文档提交推送，因此分支HEAD将晚于服务器当前批准的部署提交`76b304ac...`。服务器不自动重钉文档提交，后续smoke或部署应继续fail-closed；只有新的候选提交完成审查、CI和GHCR发布后才能重新批准。

### 8.11 2026-08-25一次性受控回滚演练实现

- Workflow新增默认关闭的`rollback_drill`布尔输入；只有`apply=true`、`run_migrations=false`和确认词`ROLLBACK DRILL IWORK ONCE`同时满足才进入演练。
- 固定部署脚本在生产共享锁内使用`FileMode.CreateNew`原子创建`rollback-drill-v1.json`。记录一旦存在，无论上次成功、失败或中断，后续演练都在容器切换前fail-closed，禁止自动或人工误重复。
- 候选两个容器必须先完成健康、镜像、Django、HTTP和Alert Worker验收，之后才触发明确的受控回滚信号；回滚继续走普通部署失败的同一恢复路径。
- 只有受控信号和回滚后全部复验同时成功，Workflow才以`rolled_back / RollbackSucceeded=true`返回成功；任何非预期异常或回滚异常均返回失败并永久保留失败记录，按用户要求立即停止分析，不进行第二轮。
- 演练强制关闭数据库迁移，不停止或重建MySQL、Redis、PostgreSQL及其他应用容器，不删除物理卷；最终应恢复演练前两个iwork镜像。
- 实现提交`bb47126`增加一次性受控回滚演练；修复提交`3bf9877779b9bc4c7fb2378d78c4b1e33087fd9f`避免预检误判瞬时健康波动。目标测试24项、全量测试565项、Ruff、PowerShell语法、Actions YAML及`git diff --check`均通过。
- 首次演练前生产预检运行[`32795142316`](https://github.com/GuChenkano/iwork/actions/runs/32795142316)在候选Digest完整拉取后失败，未进入容器切换且未创建一次性演练记录。根因是Docker解压镜像层期间宿主机I/O/CPU短时争用，使`DKT_iwork_alert_worker`连续三次健康探针超过10秒；镜像拉取完成后的下一轮探针自行恢复，容器重启0次、Redis健康、Celery返回`pong`。
- 原预检只读取一次当前健康状态，容易把上述已恢复的瞬时状态当成持续故障。修复为在既有180秒严格窗口内等待两个现有容器恢复，再记录部署基线；持续不健康仍然fail-closed。新增隔离测试稳定复现`unhealthy → healthy`，禁止通过忽略健康状态或放宽容器探针绕过。
- 修复提交的纯CI运行[`32795782056`](https://github.com/GuChenkano/iwork/actions/runs/32795782056)、GHCR发布运行[`32796035903`](https://github.com/GuChenkano/iwork/actions/runs/32796035903)及生产预检运行[`32796265379`](https://github.com/GuChenkano/iwork/actions/runs/32796265379)均成功。候选Digest为`sha256:8974135a40cdb04e1002b257c133944661fd6dd0e8d3607a2a5a45baa97c127c`，服务器准入固定`ApprovedHeadSha=3bf9877779b9bc4c7fb2378d78c4b1e33087fd9f`，部署脚本SHA-256为`e9cd76bc6cc8f63c106d60bbf0e258f65891ee2085e80df4539cdf4c2113805b`。
- 唯一一次受控回滚演练运行[`32796621375`](https://github.com/GuChenkano/iwork/actions/runs/32796621375)于2026-08-25成功完成，耗时2分13秒；参数为`apply=true / rollback_drill=true / run_migrations=false`，未再次触发。
- 状态文件`D:\DM\cicd-state\iwork\32796621375-1.json`记录`Status=rolled_back`、`RollbackSucceeded=true`；不可覆盖收据`rollback-drill-v1.json`记录`Status=succeeded`，后续重复演练将按设计fail-closed。
- 回滚后`DKT_iwork`与`DKT_iwork_alert_worker`均为`running/healthy`、重启0次，底层镜像ID均恢复为演练前`sha256:3d26cdfa20c07deb64573290c960eb61f2776a22c433e65757d7b75b3efb07f2`。运行容器配置镜像为本次部署ID对应的本地只读回滚标签，底层内容与演练前镜像一致。
- 部署文件锁、iwork维护标记和周重启标记均已清除。MySQL、Redis、PostgreSQL、Keycloak等基础容器保持原有连续运行状态，未重建或重启。
- 回滚后复验：Django `check --deploy`退出码0，仅保留4项既有反向代理安全提示；首页、实时数据API和Flow概览API均返回200；实时SSE返回200、`text/event-stream`及`dashboard_update`；Alert Worker与Realtime Worker均返回`pong`。

阶段状态：已完成。修复版真实生产切换、自动验收和唯一一次受控回滚演练均已形成生产证据；真实账号浏览器验收由用户明确豁免并保留为已知风险，不表述为验收通过。

## 9. 阶段5——Portal高风险受控部署与回滚

Portal是全系统认证网关，必须在iwork自动部署稳定后单独实施。

当前候选实现已经包含：仅手工触发的Workflow输入门禁、完整Portal和oauth2-proxy Digest校验、OCI revision校验、同Commit CI/release/Runner smoke证据校验、隔离候选容器、Portal/Authorizer/oauth2-proxy受控切换、Keycloak/Nginx不变性检查、状态收据、失败自动回滚和版本化的一次性回滚演练门禁。首轮提交为`3c159ef`，多轮安全审查加固收口于`5f96232`；真实Windows PowerShell 5.1预检随后暴露两项参数边界缺陷，分别由`cdb8bb2`和`473d6ec`修复。首次演练暴露动态镜像标签中的PowerShell变量插值错误，由`5076646db2c4fe233a97756893551da7c7802fc9`修复；修复后重跑门禁由`87ce31920aef9ac8cd11b6c64a6c42a5dfd71a99`实现。最终标准与规格复审均无代码推送阻断；Runner smoke通过运行标题精确绑定本次Commit和两个镜像Digest，旧镜像验收不能充当新部署证据，Runner临时GHCR认证的生成、写入和严格清理处于同一`try/finally`边界。最新提交的本地目标测试、全量测试、Ruff、PowerShell语法、Actions YAML和`git diff --check`均通过；CI、GHCR发布、精确Digest Runner smoke及迁移后的生产预检也已成功。修复后唯一一次重跑在切换入口发现生产Compose项目名不一致并失败，审计记录已永久保留；最终切换等待新的显式风险授权和版本化恢复设计，本阶段保持“进行中”。

2026-08-25后续状态勘误：上段末尾是v2失败后的历史快照。用户随后批准独立v3恢复方案，Compose归属修复、v3演练和最终生产切换均已完成；当前实际状态以9.8节为准。

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

当前候选版本没有Nginx配置变更，也不执行数据库迁移：脚本会导出当前Nginx有效配置、执行`nginx -t`和graceful reload，并通过`makemigrations --check --dry-run`及`migrate --check`拒绝未同步迁移。由于没有候选Nginx配置或数据库写入，本轮不为形式验收制造配置替换或数据库备份。后续若部署包含Nginx配置或数据库迁移，必须先增加候选配置原子替换/恢复以及经批准的数据库备份流程，否则fail-closed。

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

每项验收必须记录Actions运行链接、Commit SHA、两个镜像Digest、生产状态文件和具体结果。“真实登录后可用”必须覆盖新旧Portal入口、OIDC登录/退出、Remote-User、Remote-Groups、权限拒绝页及六个应用的页面、API和静态资源，不能以302或容器healthy代替。若无法取得有效浏览器会话，必须明确记录人工验收阻断或由用户作出风险豁免。

阶段5完成时只实现了Portal单仓库部署Mutex、Docker恢复Mutex、共享锁文件和Portal维护标记，属于当时的局部保护。跨仓库统一锁协议、看门狗消费Portal维护标记、周重启协调、锁超时接管和并发异常验收随后已在阶段6完成。

### 9.4 2026-08-25真实Runner与生产预检证据

- 首轮预检运行[`32804677391`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32804677391)在固定部署脚本真正启动前失败。根因是Workflow将`Generic.List[object]`直接splat给Windows PowerShell 5.1，`-Mode`被错误绑定为参数值；没有候选容器、生产切换、锁或维护标记残留。
- `cdb8bb29622e2d5cce43391b6e8ed65861b24d1f`修复Windows PowerShell 5.1不能将`Generic.List[object]`直接作为参数列表展开的问题，改用命名参数Hashtable splatting；CI运行[`32805144756`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32805144756)和GHCR发布运行[`32805275403`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32805275403)成功。
- 首次精确Digest smoke运行[`32805447403`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32805447403)在`Set up runner`阶段被旧`ApprovedHeadSha=5f96232...`拒绝，验证强SHA准入确实fail-closed。管理员重新固定`cdb8bb2...`后，smoke运行[`32805565960`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32805565960)成功。
- 预检运行[`32805679504`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32805679504)在生产切换前失败。根因是候选Compose参数数组把`$ComposeServices`作为嵌套数组元素传入Windows PowerShell 5.1，Docker未收到三个独立服务名；状态收据为`failed_before_switch`，没有候选容器、生产切换、部署锁、维护标记或临时Docker认证目录残留。
- `473d6ece26c0374a8753dcb51206724d97f4d143`改为逐项展开候选服务参数，并增加Windows PowerShell 5.1动态回归测试。CI运行[`32806376250`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32806376250)、GHCR发布运行[`32806504608`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32806504608)和精确Digest smoke运行[`32806644095`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32806644095)均成功。
- 当前Portal镜像Digest为`sha256:d4a9e3b82db6952af730378e1c0c91013faf69dd98c7a0c82c64b486df42cd46`；oauth2-proxy镜像Digest为`sha256:2298ca1a29c21b89c6a98181346083308616e28f929a35b81f63fc8b9e21ee57`；两者OCI revision均严格等于`473d6ec...`。服务器准入固定脚本SHA-256为`fd97783a1b672a7540da5ab1e4a5daecd740f76c158ece01184a2047106ebb08`。
- 修复后的预检运行[`32806781151`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32806781151)已成功越过候选Compose启动、三个候选容器健康检查、Django deploy check和模型同步检查，随后被`python manage.py migrate --check`拒绝。生产当前Portal镜像执行相同检查也返回1，确认不是候选镜像新增故障。
- 唯一未应用迁移为`apps_registry.0004_alter_registeredapp_slug`。只读检查确认表内6行、最长slug为15、无重复值；迁移SQL会删除既有slug索引、增加唯一约束并重建`varchar_pattern_ops`索引。阶段5当前明确不执行数据库迁移，因此必须在获得生产数据库写入授权并建立PostgreSQL备份、锁影响评估和回滚方案后单独处理，不能通过删除`migrate --check`绕过。
- 三次生产预检失败均发生在正式切换之前；Portal、Authorizer、oauth2-proxy、Nginx和Keycloak生产容器保持原镜像、原启动时间、healthy且无重启。服务器未跟踪证书和待办文档未被清理或覆盖。

阶段状态：进行中。代码、CI、GHCR发布和精确Digest Runner smoke已完成；当前阻断为生产数据库既有未应用迁移。生产预检、真实切换、六应用验收和回滚演练需在迁移阻断被明确处理后继续。

### 9.5 历史未应用迁移评估

2026-08-25通过生产`DKT_kc_portal`容器做只读核验，未读取密码或完整连接串，未执行任何数据库写入。核验使用Django`showmigrations`、数据库连接与约束内省、重复值只读聚合以及`sqlmigrate`预览：

- Portal默认库实际引擎为PostgreSQL，数据库为`DKT_portal`，Docker内部主机为`postgres:5432`。
- `django_migrations`中`apps_registry`只有`0001`、`0002`和`0003`；最后一次Portal业务迁移应用时间为2026-06-15，不存在`0004`的已应用记录。
- `0004`由提交`23da925f84ae2c27a014d9e64011c34e3246ae81`于2026-06-26引入，同一提交把`RegisteredApp.slug`从普通`SlugField(32)`改为`unique=True`。因此它是进入仓库约两个月但生产从未应用的历史遗留迁移，不是本次候选镜像新生成的迁移。
- 同期变更记录明确把该约束归类为代码Bug修复；此后模型、迁移链和架构规范均未撤销或替代这项唯一性要求。
- 生产表当前有6条应用记录，slug分别为`design-progress`、`dsm`、`fabric`、`gitea`、`iwork`和`pattern`；最长15个字符，无重复值，字段为非空`varchar(32)`。
- 当前数据库只有slug普通索引和`varchar_pattern_ops`索引，没有唯一约束；而当前Django模型、`/apps/{slug}` Keycloak Group、`app:{slug}`授权资源及数据库驱动的Nginx路由都把slug当作全局唯一业务标识。
- Portal管理API存在直接赋值后调用`save()`的路径，没有统一调用`full_clean()`；因此只在Django模型上声明`unique=True`不足以阻止所有重复写入，数据库唯一约束仍是必要的最终边界。
- `sqlmigrate`确认该迁移会在一个事务中删除旧slug索引，添加唯一约束，再重建`varchar_pattern_ops`索引；不改写slug值，不增删业务行。

判断：该迁移属于历史遗留，但当前仍然需要执行。删除迁移、`--fake`标记已应用或移除生产预检都会使代码声明的唯一性与数据库实际约束继续不一致，不予采用。由于当前仅6行且无重复，数据转换风险低；主要生产风险是PostgreSQL执行DDL时的短时表锁和极端情况下的回滚处理。

执行前必须单独完成：

1. 对`DKT_portal`建立可验证恢复的整库逻辑备份；如果只做定向备份，必须同时包含`django_migrations`和`apps_registry_registeredapp`的表结构、约束、索引及数据，并记录备份时点。
2. 在维护窗口再次只读检查重复slug、活动会话和表锁，设置受控的`lock_timeout`和`statement_timeout`，获取不到锁时fail-closed，不无限等待。
3. 只执行`python manage.py migrate apps_registry 0004 --noinput`，不运行不受限制的全库迁移。
4. 立即复验迁移记录、slug唯一约束、6条业务记录和Portal只读接口；复验通过后才重跑阶段5生产预检。
5. 数据库写入、备份和迁移仍需用户单独明确授权；本次评估不执行迁移。

### 9.6 2026-08-25迁移执行、失败演练与修复后证据

用户授权后已完成历史遗留迁移和迁移后证据链，执行期间没有重建或重启PostgreSQL、Keycloak、Nginx、Redis或任何物理卷：

- 迁移前再次确认目标表6行、slug无重复、最长15字符，且没有活动事务或目标表锁；数据库约9.8 MB，目标表约64 KB。
- 已建立整库逻辑备份`D:\DM\backups\portal\DKT_portal-before-apps-registry-0004-20260825-152141.dump`，文件大小110158字节，SHA-256为`2a39a7fedf79924579a1eb5c00bd721037a3ac1934762e1b0116dacb19213f8e`；备份限制ACL并通过`pg_restore --list`结构检查。
- 仅执行`python manage.py migrate apps_registry 0004 --noinput`，连接级设置`lock_timeout=5s`和`statement_timeout=30s`；迁移耗时2.652秒并成功完成。
- 迁移后6条应用数据未变化，slug唯一约束已建立，`migrate --check`返回0；相关容器没有重启。
- 迁移后首轮预检运行[`32821310691`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32821310691)成功，状态为`preflight_passed`，没有候选容器、部署锁或维护标记残留。

唯一一次受控回滚演练运行[`32821504238`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32821504238)在正式生产切换前失败：

- 状态收据`D:\DM\cicd-state\portal\32821504238-1.json`记录`Status=failed_before_switch`和`RollbackSucceeded=false`。
- 一次性审计标记`D:\DM\cicd-state\portal\rollback-drill-v1.json`记录`Status=failed`；该标记不得删除、修改或用重复运行覆盖。
- 失败发生在创建本地回滚镜像标签时，PowerShell将`"portal-rollback-$RunId:latest"`中的`$RunId:latest`解析为带作用域的变量名，生成了不完整标签`portal-rollback-`。生产Portal、Authorizer和oauth2-proxy没有切换，Keycloak和Nginx保持原状态，所有相关容器均healthy且无异常重启。
- 修复将三个动态标签统一改为`${RunId}`显式变量边界，并增加Windows PowerShell 5.1动态回归测试，直接执行真实`New-ReleaseTags`函数验证完整的源镜像与目标标签参数。
- 修复提交`5076646db2c4fe233a97756893551da7c7802fc9`已推送；本地72项目标测试、114项全量测试（跳过2项，另有39个subtests）、Ruff、迁移检查、PowerShell语法、Actions YAML和`git diff --check`均通过。
- 同提交CI运行[`32822019243`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32822019243)和GHCR发布运行[`32822211897`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32822211897)成功。Portal Digest为`sha256:5fcd6f867f5b3fd5bee6ca0c778a0ba9d881c72b5f8fe98fe8b9d01313e36fbf`，oauth2-proxy Digest为`sha256:814ac4af3eafb66e0365a267015248f22789038e73fb264664dc80b93bb206eb`。
- 修复后精确Digest Runner smoke运行[`32822609980`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32822609980)成功；迁移后`apply=false`预检运行[`32822771675`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32822771675)成功。两项均未切换生产业务容器。

当前决策边界：数据库迁移阻断已经解除，候选代码、镜像和生产预检均已通过，但“一次性回滚演练必须成功”这一验收项尚未满足。依据用户此前明确的“一轮失败立即停止且不得重复执行”要求，不能删除失败标记、不能再次触发`rollback_drill=true`，也不把任何后续动作称为“补偿演练”。最终`apply=true / rollback_drill=false`切换之前只能选择并记录以下一种处理：

1. 保持现有验收标准并暂停最终切换，另行设计和审批“部署成功后人工验收失败”的独立受控回退入口；该入口不是重复运行一次性演练，必须使用新的命令、权限、状态文件和审计规则，完成实现与验证后再重新评估是否满足阶段5回滚能力要求。
2. 用户明确修改阶段5验收标准并接受“没有成功生产回滚演练证据”的剩余风险，授权执行最终普通切换；即使切换和业务验收成功，文档也必须标记为“带风险例外完成”，不能表述为回滚演练通过。

在上述决策产生前，本阶段不得标记为完成，也不执行最终生产切换。

### 9.7 2026-08-25修复后重跑结果与新阻断

用户明确批准保留首次失败证据，并允许对`32821504238-1`执行唯一一次修复后回滚演练重跑。实施和结果如下：

- Portal仓库候选提交为`87ce31920aef9ac8cd11b6c64a6c42a5dfd71a99`；CI运行[`32827003935`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32827003935)和GHCR发布运行[`32827173871`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32827173871)成功。
- Portal镜像Digest为`sha256:9007bbcfc86794be40b173d8c2b5adc184f11c45a43ab27300bcea31330a6a69`；oauth2-proxy镜像Digest为`sha256:33edf5e00d9b6bb6e0d84b401ac38e5b59032dc6044e879306432c665f67cee0`；固定部署脚本SHA-256为`e7b897f89cd8267022520e90c6daae34eefaff2e33376024f3c2e21dedf92c35`。
- 服务器仓库以`--ff-only`从`5076646...`快进到`87ce319...`，原有未跟踪`docker/certs/`和证书待办文档保持不变。生产准入重新固定到该提交和脚本哈希。
- 精确Digest Runner smoke运行[`32827603496`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32827603496)成功；`apply=false`预检运行[`32827734316`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32827734316)成功，状态收据为`preflight_passed`，候选容器、部署锁和维护标记均已清理。
- 唯一一次修复后重跑运行[`32827854376`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32827854376)失败。不可覆盖的`rollback-drill-v2.json`记录`RunId=32827854376-1`和`Status=failed`；运行收据`32827854376-1.json`保守记录`Status=rollback_failed`和`RollbackSucceeded=false`。v1、原运行收据和v2均不得删除、覆盖或伪造成功。
- 失败根因不是候选镜像或应用健康，而是部署脚本把Compose项目名固定为`dkt-keycloak`，生产现有Portal、Authorizer和oauth2-proxy容器的实际`com.docker.compose.project`均为`docker`。使用另一个项目执行`compose up`时无法接管相同的固定`container_name`，正式切换命令和自动恢复命令均以退出码1结束。
- 脚本在调用`compose up`之前已把`switchAttempted`置为真，因此收据按严格失败语义写成`rollback_failed`；但Docker证据确认三个生产容器ID、镜像ID和启动时间与演练前完全一致，候选容器不存在，Keycloak和Nginx容器也未变化。即本轮没有实际替换生产容器，也没有发生需要恢复的数据或基础设施变更。
- 失败后只读复验确认Portal、Authorizer和oauth2-proxy均为`running/healthy`；Nginx内部健康检查成功；OIDC issuer仍为`https://auth.dituportal.dongming.local/realms/ditu`；新Portal未登录返回302并使用新认证域名与新回调；旧Portal返回307到新Portal。

当前阻断：依据“修复后重跑只允许一次，失败立即停止”的审计规则，不能删除v2、不能第三次触发演练，也不能绕过`Assert-SuccessfulDrillEvidence`执行最终普通部署。继续阶段5需要用户另行明确授权一个新的版本化恢复方案：先修正并验证Compose项目归属，再以新的v3状态文件绑定v1、v2及两个运行收据，且只能再执行一次；或者明确接受没有成功回滚演练证据的风险例外并调整验收标准。当前不采用后者。

### 9.8 2026-08-25 v3恢复演练与最终生产交付

用户批准“小范围问题直接修复并重跑，大型问题停止汇报”，并明确授权新的版本化v3恢复演练。v3不是删除或重跑v1/v2：它使用独立输入、确认词和`rollback-drill-v3.json`，同时绑定v2失败Run ID、v1/v2状态文件及两个运行收据的固定SHA-256，且只允许登记一次。

修复和验证：

- Portal修复提交为`254cb2d63c4c75761dc9797c894afb323ac45b82`。正式Compose项目从错误的`dkt-keycloak`修正为生产实际项目`docker`；切换前严格核对三个容器的Compose project、service、working directory和基础Compose文件，正式Compose命令从`D:\DM\DTD_nginx\docker`执行。
- 原生命令失败输出增加敏感关键词整行脱敏、URI userinfo、Bearer/Basic凭据脱敏及2000字符限长；不会把Token、Cookie、数据库连接串或密钥写入Actions摘要和部署收据。
- v3固定绑定`32827854376-1`及四份既有生产审计文件的真实哈希。测试同时验证当前生产基线必须与v2收据的`Previous`一致、任何证据改写均fail-closed、v3重复登记被拒、最终部署必须取得v3成功状态和`rolled_back / RollbackSucceeded=true`收据。
- 本地目标测试25项、Django测试72项、离线配置测试122项（跳过2项，另有39个subtests）、Ruff、迁移一致性、PowerShell语法、Actions YAML及`git diff --check`全部通过；规范与规格双轴审查均无P1/P2阻断。
- 同提交CI运行[`32830823323`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32830823323)成功；GHCR发布运行[`32831012581`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32831012581)成功。Portal Digest为`sha256:6c5cf71b39b5b1937215bddd50d2555710abb7e41baa3e46d2dc5d4102c2b41a`，oauth2-proxy Digest为`sha256:143756a92516220d1915678f69650343cb91c46b248df597266acca8c4a72065`，两者OCI revision均严格等于`254cb2d...`。
- 服务器仓库通过`git merge --ff-only`从`87ce319...`快进到`254cb2d...`，原有未跟踪`docker/certs/`和证书待办文档保持不变；生产准入固定脚本SHA-256为`3836bcb32f849d664fe9fbffcab16c23ca372dfd5465bcb5cbde6af064a225df`。
- 精确Digest Runner smoke运行[`32831345663`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32831345663)成功；`apply=false`预检运行[`32831471732`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32831471732)成功。预检后生产三容器ID、镜像和启动时间仍与v2演练前基线一致，四份v1/v2审计哈希未变，v3不存在，候选容器、锁和维护标记均已清理。

唯一一次v3恢复演练运行[`32831639384`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32831639384)成功：

- `D:\DM\cicd-state\portal\rollback-drill-v3.json`记录`Status=succeeded`，SHA-256为`3935a5027548c02fb339a7b344a95078bf3da82e07820d9afb28be48fb390d3e`。
- 运行收据`32831639384-1.json`记录`Status=rolled_back`和`RollbackSucceeded=true`，SHA-256为`bb45f5ce71eb1c381b84a2805b684d9e59c99d8259ea5538856bed4f57d6d3e3`。
- Portal、Authorizer和oauth2-proxy均恢复演练前镜像并为healthy；Keycloak和Nginx的容器ID、启动时间及健康状态未变化。v1/v2四份证据哈希保持原值，且无候选容器、锁或维护标记残留。

最终生产部署运行[`32831954325`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32831954325)成功：

- 收据`D:\DM\cicd-state\portal\32831954325-1.json`记录`Status=deployed`，SHA-256为`5caabfc9174eb70ee20ce78c46aac0afef6e35811d79302cfd32cdf4f854b6b5`。
- `DKT_kc_portal`与`DKT_kc_authorizer`使用固定Portal Digest，`DKT_kc_oauth2proxy`使用固定proxy Digest；三者均为`running/healthy`、重启次数0，OCI revision均为`254cb2d...`。
- `DKT_kc_keycloak`和`DKT_kc_nginx`未重建；Portal数据库、MySQL、Redis、网络和物理卷未重建或删除。iwork及Alert Worker保持`running/healthy`、重启次数0。
- 新Portal未登录请求返回302到`auth.dituportal.dongming.local/realms/ditu`，回调严格使用新Portal；旧Portal和旧认证入口返回单次307，`dkt` Realm路径正确映射为`ditu`，`master`路径保持不变；discovery issuer严格等于新认证地址。
- iwork生产详情内部真实请求返回200；SSE返回200、`text/event-stream`和非stale的`snapshot_published`事件。六个应用入口未登录请求均进入新认证地址，未发现旧认证域名或跳转循环。

风险豁免：内置浏览器访问新Portal时因当前自定义证书未被该浏览器信任，返回`ERR_CERT_AUTHORITY_INVALID`；安全规则禁止自动绕过证书警告。真实登录/退出、Remote-User、Remote-Groups、权限拒绝页，以及六个应用登录后的页面、API和静态资源未实际执行。用户于2026-08-26明确要求跳过该项并接受风险豁免；证书仍按既有待办方案后续处理。本项不表述为验收通过，但不再阻断阶段5完成。

阶段状态：已完成（2026-08-26）。

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

本阶段的并发触发、异常退出和运维互斥验收使用隔离目录、独立PowerShell进程、伪GitHub Run
解析器及假维护标记完成，不操作生产容器、生产锁或真实计划任务。生产环境只执行准入安装、
Runner smoke和`apply=false`预检。真实生产部署并发、强制终止生产Runner、真实周重启及故障注入
属于阶段8验收范围；阶段6标记完成不表示这些生产破坏性场景已经执行。

### 10.4 实际实现

两个仓库共用字节完全一致的`ProductionCoordination.psm1`，锁Schema固定为
`production-deploy-lock-v1`。服务器分别安装到`D:\DM\cicd-tools\portal`和
`D:\DM\cicd-tools\iwork`，避免一个仓库更新生产策略时覆盖另一仓库正在使用的模块。
Portal与iwork部署均先取得
`Global\DKT-Production-Deploy`、`Global\DKT-Docker-Recovery`和统一文件锁，再进入候选校验、
切换、生产验收或回滚阶段。Runner准入Hook和Workflow同时固定部署脚本与协调模块的
SHA-256，禁止从Runner工作区直接替换生产脚本。

过期锁不能按文件时间或租约单独删除。自动接管必须同时确认：锁Schema与仓库身份可信、
本机原PID不存在或PID已复用、原GitHub Actions Run已经进入明确终态。GitHub不可达、`gh`
不可用、Run字段不一致、进程状态未知或锁来自其他主机时均失败关闭；两个安装器会先验证
Runner账号的`gh`登录状态，并直接读取另一私有仓库的`actions/runs`接口，不能用仅可读取
仓库元数据的权限冒充Actions读取能力。跨仓库Run核验会暂存并清除Workflow注入的
`GH_TOKEN / GITHUB_TOKEN`，强制使用安装器已验证的Runner持久`gh`身份，调用结束后在
`finally`中恢复原环境变量。安全接管前将旧锁原子
改名为审计归档。协调事件以JSONL记录`acquire_attempt`、`contention`、`acquired`、
`phase_updated`、`stale_archived`、`stale_rejected`、`released`和`cleanup_failed`，每条均含
仓库、服务与Run ID，不记录Token、Cookie或密码；JSONL写入使用独立的全局审计Mutex，
避免并发竞争导致事件交错或丢失。

看门狗同时识别Portal和iwork部署维护标记。有效窗口内不执行Docker恢复；过期、未来、
无时区、超长、字段错误或非法JSON标记均不放行。Python应用健康监控继续检查容器，只跳过
正在部署应用的HTTP探测。iwork标记沿用既有`application / operation /
workflow_run_id / actor`契约，Portal沿用`scope / run_id`契约。Docker周重启保持周日03:00和
十分钟窗口，通过`Global\DKT-Docker-Recovery`与部署互斥；看门狗在03:10超时接管路径恢复。
看门狗和周重启各自生成运行级`run_id`写入日志。周重启维护标记的关闭或失败状态写入若失败，
任务会返回非零，不能用成功结果掩盖残留维护窗口。

部署进程异常退出后可能遗留应用维护标记。后续正式部署只有在已经取得生产部署Mutex、
Docker恢复Mutex和新的统一协调锁后，才允许对字段可信且已过期的旧标记执行同目录原子归档。
可信标记必须包含完整Schema、合法且不超过128字符的Run ID、带时区的开始和结束时间、
正确的时间顺序及最大窗口（Portal 30分钟、iwork 20分钟）；可选`status`存在时只能为
`running`，iwork还必须具有字符串类型、非空且不超过128字符的`actor`。只读预检、活动标记、
未来窗口、超长窗口、错误状态、非法ID、无时区和无法解析的标记均保留原文件并失败关闭。

### 10.5 本地隔离验收证据

2026-08-26已完成以下不触碰生产Docker、生产锁和真实GitHub Run的隔离验收：

- 两个独立PowerShell进程并发竞争，只有一个取得统一锁；另一个明确返回竞争结果。
- 强制终止隔离持锁子进程后，只有在伪Run为`completed`且PID核验通过时才归档并接管。
- 锁生命周期、阶段续租、活动进程拒绝、运行中Run拒绝、未知Run失败关闭、Run字段不一致
  拒绝、释放失败审计均通过。
- Portal阶段六目标测试`28 passed`；CI口径Django应用测试`72 passed`，离线配置测试
  `138 passed / 2 skipped / 39 subtests passed`。直接全仓pytest额外收集到需访问当前旧域名的
  `docker/test_auth_flow.py`并因旧入口307跳转而失败，该脚本不属于CI离线测试，本阶段未将其误报为
  代码回归。
- iwork阶段四及阶段六目标测试`31 passed`，iwork全量测试`574 passed`；仅保留第三方
  `requests`依赖版本告警，与本次变更无关。
- 看门狗完整隔离测试和周重启维护测试均为`0 failure(s)`；未运行会真实重启Docker/WSL的
  `test_docker_weekly_restart.ps1`。
- 统一锁生命周期测试、两个独立进程并发竞争、异常退出后双重核验恢复、跨仓库gh临时Token
  隔离与恢复全部通过；Portal与iwork维护标记覆盖缺少开始时间、时间倒置、超长窗口、非法Run ID、
  错误状态、未来窗口及可信过期归档。
- 两仓库协调模块字节完全一致，SHA-256为
  `39f04a102c13acc473d46f6d4dc58906619682890d65312aed1f39836318bee3`；Portal部署脚本SHA-256为
  `ba6b5c5d95213840169e6e076af13997e7f4fbbac45ac04d91a6b25c2406a830`，iwork部署脚本SHA-256为
  `7320713f6f9b0c445eb371ccf7c9f0926cfa020c88478ff1926453c59d44d7cd`，Workflow固定值均与文件匹配。
- Ruff、PowerShell语法解析、两个仓库`git diff --check`及标准/规格双轴复审通过，无剩余阻断。

本轮定位并修复两个测试无法提前暴露的兼容问题：Windows PowerShell 5.1读取无BOM UTF-8
脚本时会受中文注释影响，现已固定看门狗脚本为UTF-8 BOM并增加回归断言；Python健康监控
原先错误地用Portal字段解释iwork部署标记，现已按两个真实Schema分别校验。DITU已完成
正式切换，因此旧Keycloak认证地址不再作为健康检查回退，DITU discovery失败时严格失败。

### 10.6 生产安装与只读预检证据

2026-08-26在`192.168.0.97`完成生产准入安装和只读预检，未执行真实部署：

- 服务器GitHub CLI为`2.98.0`，使用`DONGMING\shuju`桌面账号完成GitHub设备授权；
  `gh auth status`确认账号为`GuChenkano`，并分别成功只读访问Portal与iwork的
  `actions/runs`接口。授权Token未输出或写入仓库。
- 两个生产仓库均使用`git pull --ff-only`安全快进：Portal固定到
  `3bcc7a114e9df4e354db5e84af4d125a1b4d8ae0`，iwork固定到
  `73417ff196098ed606a5354d4d101087d65359bb`。Portal既有的`docker/certs/`、
  `docs/iwork看板操作手册.md`和证书待办方案三项未跟踪内容原样保留；iwork工作区保持干净。
- Portal安装器将准入策略固定到上述Portal提交，部署脚本SHA-256为
  `ba6b5c5d95213840169e6e076af13997e7f4fbbac45ac04d91a6b25c2406a830`；
  iwork安装器固定到上述iwork提交，部署脚本SHA-256为
  `7320713f6f9b0c445eb371ccf7c9f0926cfa020c88478ff1926453c59d44d7cd`；
  两套已安装协调模块SHA-256均为
  `39f04a102c13acc473d46f6d4dc58906619682890d65312aed1f39836318bee3`。
- Portal准入固定仓库`GuChenkano/DTD_nginx`、分支`feature/keycloak-migration`、actor
  `GuChenkano`及`.github/workflows/runner-smoke.yml`、
  `.github/workflows/deploy-portal.yml`；iwork准入固定仓库`GuChenkano/iwork`、分支
  `Keycloak`、actor `GuChenkano`及`.github/workflows/runner-smoke.yml`、
  `.github/workflows/deploy-iwork.yml`。Workflow名称和完整`GITHUB_WORKFLOW_REF`由安装后的
  Job started Hook校验，浏览器输入不能覆盖。
- Portal Runner smoke运行
  [`32924939296`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32924939296)成功，
  验证当前Portal和oauth2-proxy固定Digest及OCI revision；iwork Runner smoke运行
  [`32924942094`](https://github.com/GuChenkano/iwork/actions/runs/32924942094)成功，
  验证Runner身份、隔离工作目录、Docker和GHCR只读拉取能力。
- Portal `apply=false`生产预检运行
  [`32925115404`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32925115404)成功；
  iwork `apply=false / run_migrations=false`生产预检运行
  [`32925118718`](https://github.com/GuChenkano/iwork/actions/runs/32925118718)成功。
  两次预检均未切换业务容器、未执行数据库迁移、未创建维护窗口。
- 收尾复核确认两个Runner均已空闲，`production-deploy.lock`、Portal/iwork部署维护标记和
  Docker周重启维护标记均不存在，没有候选容器残留。Portal、Authorizer、oauth2-proxy、
  iwork及Alert Worker保持原启动时长并为`healthy`，两个服务器Git工作区状态与快进前边界一致。

阶段状态：已完成（2026-08-26；代码、隔离测试、双轴复审、CI、GHCR、生产准入安装、
Runner smoke及`apply=false`生产预检全部完成；未执行真实部署或故障注入）。

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
查看生产交付证据
回滚上一次部署（缺少独立Workflow时失败关闭）
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

### 11.5 实际交付

2026-08-26已将Skill源码纳入iwork Git版本管理，并安装到用户级技能目录；安装过程不读取或复制本机`gh`凭据：

```text
版本化源码：
C:\Users\lipengfei\ZCodeProject\iwork\tools\skills\dkt-cicd

幂等安装入口：
C:\Users\lipengfei\ZCodeProject\iwork\scripts\Install-DktCicdSkill.ps1

安装副本：
C:\Users\lipengfei\.agents\skills\dkt-cicd\SKILL.md
C:\Users\lipengfei\.agents\skills\dkt-cicd\agents\openai.yaml
C:\Users\lipengfei\.agents\skills\dkt-cicd\references\workflow-map.md
C:\Users\lipengfei\.agents\skills\dkt-cicd\scripts\Invoke-DktCicd.ps1
C:\Users\lipengfei\.agents\skills\dkt-cicd\tests\Fake-Gh.ps1
C:\Users\lipengfei\.agents\skills\dkt-cicd\tests\Test-DktCicd.ps1
```

固定映射：

- iwork：`GuChenkano/iwork`、`Keycloak`、`ci.yml`、`release.yml`、
  `deploy-iwork.yml`、`production-iwork`。
- Portal：`GuChenkano/DTD_nginx`、`feature/keycloak-migration`、`ci.yml`、
  `release.yml`、`deploy-portal.yml`、`production-portal`。
- 查询支持按`ci / release / deploy / all`筛选；触发前复验固定分支远程HEAD，发布前
  复验同Commit成功CI，部署前复验同Commit成功CI和GHCR发布。Portal还会预检匹配
  Commit与两个Digest的Runner smoke证据。
- iwork生产确认词绑定本次完整Commit；Portal使用
  `DEPLOY PORTAL AND AUTHENTICATION <完整Commit>`高等级确认。确认缺失或不一致时返回
  `confirmation_required`和退出码4，不调用`gh workflow run`。
- 失败日志仅在明确查询时读取，并在输出前脱敏GitHub Token、Authorization、密码、
  Cookie和Secret形态的值。

主入口SHA-256：

```text
SKILL.md
6a6a883481ef1099955fde58a2f3fdf616fc5080f21508b83576f3fdb617324b

scripts\Invoke-DktCicd.ps1
0b425208571912266db7f5f1dec150f57d06dd1c0abd12dd86e55275816f5439
```

### 11.6 验收证据

- PowerShell语法检查通过；`skill-creator/quick_validate.py`在`PYTHONUTF8=1`下返回
  `Skill is valid!`。首次不带UTF-8模式运行时，校验器使用Windows默认GBK读取UTF-8
  `SKILL.md`而报`UnicodeDecodeError`，属于校验器启动编码差异，不是Skill文件损坏。
- `tests/Test-DktCicd.ps1`通过72个离线断言，覆盖固定仓库/分支/Workflow路由、
  `queued`、`in_progress`、`success`、`failure`、失败Step提取、日志脱敏、CI与发布触发、
  Digest提取、iwork/Portal确认门禁、回滚失败关闭及Actions证据与实时Docker状态分离；
  `-Wait`监控到失败时返回非零退出码，失败日志或Digest日志读取失败时失败关闭。
- 独立安全审查发现并修复四项问题：等待失败曾可能返回0、新版`github_pat_`及URI
  userinfo脱敏覆盖不足、日志读取失败未失败关闭、同Commit并发触发可能关联错误Run。
  修复后增加本地命名Mutex、触发时间窗口和4秒稳定窗口；出现多个候选Run时立即返回
  并发歧义并明确禁止重复触发，不再选择“最新一条”继续监控。
- Digest按固定镜像名解析并做唯一性校验；Portal必须分别得到一个`dtd-nginx`和一个
  `dtd-oauth2-proxy` Digest，两个不同的Portal镜像Digest不能冒充两个发布产物。
- 阶段8启动前双轴复审发现并修复三项生产门禁缺口：预检/部署输入Digest现在必须与
  同Commit成功Release日志中的发布产物逐项一致；生产确认增加15分钟有效、参数指纹绑定、
  单次消费的本地预览状态，不能再直接携带确认词跳过预览；Release状态查询会返回完整
  Digest。修复采用测试先行，新增iwork与Portal Digest错配、无预览直调、预览参数变化、
  单次消费和Release状态Digest回归断言；同一套72项断言同时在PowerShell 7与生产兼容的
  Windows PowerShell 5.1下通过，5个含中文的PowerShell入口固定为UTF-8 BOM以避免5.1按
  系统代码页误解析；JSON数组显式逐项写入管道，避免5.1把整个`Object[]`误当单个Run。
- 真实只读iwork CI查询返回[`32922442124`](https://github.com/GuChenkano/iwork/actions/runs/32922442124)：
  `completed / success`，Commit为`73417ff196098ed606a5354d4d101087d65359bb`，耗时258秒。
- 真实只读iwork生产证据查询返回[`32925118718`](https://github.com/GuChenkano/iwork/actions/runs/32925118718)：
  `completed / success`，并提取Digest
  `sha256:d7fae15d06672249b72f76d68b884fa93f83dc0df706ac87ecf69b59a1735dc7`。
- 独立前向测试读取Portal生产证据[`32925115404`](https://github.com/GuChenkano/DTD_nginx/actions/runs/32925115404)：
  `completed / success`，耗时64秒，正确提取Portal Digest
  `sha256:d53222466e4aa9b6e6395afd12c57e5450a04dd97301955dc676d05d0b017bdc`
  和oauth2-proxy Digest
  `sha256:abb644f6afaa60e37820fec177f0c360c1e0c95cccab57a1a7830a1b7fcd0586`。
- 使用上述Portal Commit与Digest执行无确认预览，返回退出码4和高等级确认词；预览前后
  最新部署Run ID均为`32925115404`，证明未触发真实Workflow。
- 阶段7没有执行`gh workflow run`真实触发、生产部署、数据库迁移、故障注入、并发锁
  测试或24小时观察。

### 11.7 方案偏差与安全收敛

- 原“查看生产容器状态”改为“查看GitHub Actions生产交付证据”。Actions无法证明当前
  Docker实时健康，Skill会明确返回`not live Docker health`；需要实时状态时另行执行获准的
  服务器只读检查，禁止混称。
- 原“回滚上一次部署”没有对应独立Workflow。现有`rollback_drill`是一次性受控演练，
  不能冒充手工回滚；强SHA准入也禁止直接用旧Digest替代当前批准版本。因此`rollback`
  固定返回`manual_rollback_workflow_missing`并失败关闭。部署失败时的自动回滚仍由现有
  Workflow和服务器固定脚本负责。若未来确需手工回退，应单独设计、审查和安装版本化
  Workflow，不在Skill中直接SSH执行。
- iwork `runner-smoke.yml`仍固定历史Revision/Digest，不是当前分支动态入口；Skill未把它
  暴露为当前版本通用smoke，避免错误验收。
- 原“Skill只安装在用户目录、本阶段Git只追踪文档”的结论已修正：用户目录仍是运行时
  安装副本，但完整源码已纳入
  `tools/skills/dkt-cicd`。`scripts/Install-DktCicdSkill.ps1`使用暂存目录、逐文件SHA-256
  校验和失败恢复完成幂等安装；`tests/test_install_dkt_cicd_skill.ps1`验证首次安装、文件
  清单一致与重复安装不变。后续禁止只修改用户目录而不提交仓库版本源。

阶段状态：已完成（2026-08-26；Skill安装、离线行为测试、真实只读查询、生产确认不触发
验收及独立前向测试全部完成；没有提前执行阶段8的真实Workflow和生产动作）。

## 12. 阶段8——端到端验收与稳定观察

### 12.1 首轮iwork CI与GHCR发布

2026-08-26阶段8正式开始：

- 阶段7提交及阶段8门禁修复推送后，iwork远程`Keycloak`指向
  `b0ca01b24295fe89be3832a631f1df3ccb55381b`。
- Skill手工触发的纯CI运行
  [`32940305292`](https://github.com/GuChenkano/iwork/actions/runs/32940305292)成功；同Commit的
  push触发运行`32940297739`因Workflow并发策略被正常取消，没有重复执行结果。
- Skill的45秒Run发现窗口未及时看到已经提交的手工CI和Release运行，均按设计失败关闭；
  后续只查询并监控已存在Run，没有重复触发。该延迟作为阶段8观察项保留。
- GHCR发布运行
  [`32940662133`](https://github.com/GuChenkano/iwork/actions/runs/32940662133)完成镜像构建与推送，
  日志产生Digest`sha256:4ad72cbb57414918ae522d06753e3a91685a19e7ee9162f0cf9491c402a86002`，
  但推送后立即执行的`imagetools inspect`尚未读取到清单，运行因此失败；未将失败Run或其
  Digest作为成功发布证据。
- 根因是GHCR推送后清单短暂最终一致，而非构建、权限或推送失败。修复为仅在`docker push`
  成功后对Digest解析执行6次、每次间隔5秒的有界重试；发布前复用检查仍为单次，构建、
  推送、Digest格式及OCI revision失败继续立即停止。目标Workflow测试已先红后绿。

当前仍需对修复Commit重新执行CI、GHCR发布、生产只拉取预检和后续生产验收；不得复用首轮
失败Release作为前置证据。

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

本小节状态：历史记录（2026-08-26）。首轮失败证据保持不可变，后续修复与真实交付证据见12.2节。

### 12.2 2026-08-27 iwork通知修复真实交付与配置漂移复盘

#### 12.2.1 真实交付证据

2026-08-27，Commit `4cb8e31188a0022ea5441e1e10490adc4cc8ad8a` 的站内通知详情与生产CSRF修复完成
以下受控交付链路：

- 纯CI运行[`33051286997`](https://github.com/GuChenkano/iwork/actions/runs/33051286997)：`completed / success`。
- GHCR发布运行[`33051630263`](https://github.com/GuChenkano/iwork/actions/runs/33051630263)：`completed / success`；
  iwork镜像Digest为
  `sha256:6b131b70ef209073adf9e6de7e048f230e2c9ce00b8b3eea0d78187455ff3285`，OCI revision与该Commit一致。
- 生产`apply=false`预检运行[`33053478836`](https://github.com/GuChenkano/iwork/actions/runs/33053478836)：`completed / success`。
- 正式部署运行[`33053638336`](https://github.com/GuChenkano/iwork/actions/runs/33053638336)：`completed / success`，
  输入为`apply=true`、`run_migrations=false`，部署摘要记录了同步服务器生产配置及通知详情CSRF修复。

上述证据证明该Commit的镜像已通过CI、GHCR、生产预检和受控部署Workflow；它不等价于真实浏览器登录、
通知点击、Remote-User和退出链路已经完成。当前仍需保留真实账号浏览器验收及24小时观察的未完成状态。

#### 12.2.2 首次配置漂移根因

本次修复同时暴露了生产配置交付边界：`env/production.env` 中新增的
`DJANGO_CSRF_TRUSTED_ORIGINS` 属于版本化代码库，但既有部署Workflow只校验候选镜像的完整Digest、
OCI revision、固定部署脚本和协调模块哈希，不校验服务器 `D:\DM\iwork\env\production.env` 的内容哈希。
固定部署脚本也只确认配置文件存在并把它传给Compose。因此，镜像Commit可以已经更新，而服务器仍可能使用
旧生产配置；变更说明中的“同步服务器生产配置”不是可验证的配置一致性证据。

本次正式部署能够成功，不应倒推旧机制已经具备配置一致性门禁。首次漂移的根因是生产配置没有作为不可变发布
产物进入Release、Preflight和Deploy的同一证据链，服务器Git工作区中的配置文件事实上承担了隐式运行时输入。

#### 12.2.3 不可变配置包、三类Digest与request_id长期方案

后续生产发布采用“镜像 + 配置包 + Commit”三元绑定，具体规则如下：

1. Hosted Runner从批准Commit生成不含密码的不可变生产配置包。配置包使用严格UTF-8规范化字节（LF、无BOM）和逻辑SHA-256 Digest；
   固定Schema清单包含`application`、完整Commit、镜像Digest、Compose哈希、生产环境文件哈希和配置包Digest。
   `compose_sha256`与`production_env_sha256`为64位小写十六进制，`config_digest`为完整`sha256:`加64位小写十六进制值。
   GitHub Actions Artifact仅包含清单、`docker-compose.yml`和`env/production.env`，保留90天且不允许覆盖同Run产物。
2. Release同时发布GHCR镜像与配置Artifact，并输出镜像Digest、配置逻辑Digest和Artifact存储Digest三种稳定机器记录。生产输入必须同时提供
   `image_digest`、`config_digest`和`expected_revision`；三者必须来自同一成功Release，不能只验证格式或只验证
   镜像OCI revision。
3. 生产Runner只拉取并校验不可变配置包，不从服务器Git工作区读取`env/production.env`作为候选配置。服务器
   工作区中的同名文件即使存在，也不能替代配置包；生产密钥继续只从服务器中央密钥文件注入。
4. iwork的Web和Alert Worker必须使用同一Commit、同一镜像Digest和同一配置包Digest；部署锁、状态收据和
   Step Summary均保存这组绑定。Portal继续使用自己的机制认证方案，不在本轮iwork配置包提交中改造。
5. 每次iwork Skill请求先生成不可复用的`request_id`，并原样传入CI、Release、Preflight和Deploy。该ID必须出现在
   Workflow run-name、机器可读摘要、Digest解析结果、部署锁、状态文件和回滚收据中。`GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT`
   仍是平台Run标识，不能代替用户请求关联ID。
6. 触发后的Run关联必须同时核对仓库、Workflow、分支、Commit、`workflow_dispatch`、`request_id`和唯一
   `databaseId`。无法取得唯一匹配、只看到旧Run或Run字段不完整时，必须失败关闭，不猜测“最新Run”。
7. Release必须输出每个制品的稳定`artifact_digest`记录；Skill按该记录解析并做唯一性校验，不能依赖任意Docker
   pull输出、颜色控制码或不可稳定的自由文本。缺少制品、同一制品出现不同Digest或配置包与镜像不成对时必须拒绝部署。

#### 12.2.4 TDD垂直切片与顺序

每个切片必须先增加会失败的测试，再实现最小修复，最后运行本地与CI验证：

| 切片 | 先失败的测试与范围 | 通过标准 |
|---|---|---|
| A 配置包契约 | `tests/test_production_deployment_stage4.py`：Workflow必须固定配置包路径、`config_digest`和当前版本化配置清单Digest；当前旧Workflow应失败 | Release、Preflight、Deploy使用同一配置包Digest，配置不含密码且来源Commit明确 |
| B 配置漂移阻断 | 阶段4隔离测试：服务器配置包缺失、Digest错误、Commit不一致时，必须在Compose切换前失败关闭；正确配置必须写入预检结果 | 不读取服务器Git工作区候选配置；state、锁和摘要记录镜像/配置/Commit三元绑定 |
| C Run唯一关联 | `tools/skills/dkt-cicd/tests/Test-DktCicd.ps1`与`Fake-Gh.ps1`增加旧Run、push Run、重复dispatch和延迟可见Run；没有唯一`request_id`匹配时必须拒绝 | `gh run watch`、详情、日志和Digest均使用同一唯一Run ID，禁止猜测最新Run |
| D Digest解析 | 增加缺少制品、同制品多Digest、Portal双镜像错配、仅有非规范Docker输出等失败测试 | Release输出稳定`artifact_digest`；重复同值可接受，不同值、缺失或跨Commit立即失败 |
| E 成对回滚 | 阶段4部署隔离测试注入健康失败和配置包损坏；验证Web/Worker镜像与配置包一起恢复 | 回滚收据同时记录并验证两个镜像Digest、配置包Digest、Commit和`request_id`，不自动回滚数据库 |
| F 端到端验收 | 依次执行CI、Release、Runner smoke、`apply=false`预检、正式部署和一次故障注入；最后执行浏览器与24小时观察 | 所有证据链可按`request_id`串联，未完成项仍明确标记，不以容器healthy替代业务验收 |

迁移期规则：在不可变配置包契约正式安装前，可以暂时保留旧Runner Hook的`ApprovedHeadSha`作为补偿门禁，
但它不能替代配置包Digest、镜像/配置/Commit绑定或`request_id`关联。只有安装器、Runner Hook、固定部署脚本、
协调协议、部署Workflow或Runner smoke契约等部署机制本身变化时，才需要重新安装生产准入；普通应用Commit或
配置包版本变化不应强制重装机制准入。

每完成一个TDD切片或一个实施阶段，都必须在同一阶段提交中更新本总方案，记录阶段状态、实际Commit、
Actions运行链接、测试与验收证据、未完成项、风险例外和下一阶段入口；测试通过或代码提交本身不能替代真实生产证据。

#### 12.2.5 迁移、成对回滚与验收边界

- 数据库迁移仍必须显式批准；`apply=false`和配置包预检不得执行迁移。
- 迁移失败时只自动恢复应用镜像和配置包，不自动覆盖数据库；仅允许已审查的expand/contract迁移，备份用于
  受控人工恢复。
- 普通部署失败、配置包校验失败或任一容器验收失败时，Web与Alert Worker必须以原部署收据中的旧镜像Digest
  和旧配置包Digest成对恢复，并再次验证HTTP、Django检查、Worker、实际镜像和配置包。
- 生产验收必须分别记录CI、Release、Runner smoke、预检、正式切换、通知点击、CSRF、真实登录/退出、权限拒绝、
  SSE、容器健康、锁清理、回滚和24小时观察；Actions成功或容器healthy不能单独代替业务验收。

本地实现状态（2026-08-28）：不可变配置包已经接入Release与Deploy Workflow；固定部署脚本会严格验证Schema、
Commit、镜像Digest、配置逻辑Digest、文件哈希、未知文件、重解析点和敏感键，并把候选配置保存到受控状态目录。
部署状态、活动发布指针和协调锁已记录镜像/配置/Artifact三类Digest与`request_id`；隔离故障测试已证明旧镜像和不同旧配置可以成对恢复。
`dkt-cicd`已完成120秒Run发现、iwork `request_id`关联、三类Digest解析、失败Run无Digest兼容，并已同步本机安装副本（版本源与安装副本6个文件逐项SHA-256一致）。
本地证据为目标测试`53 passed`、Python全量`596 passed`（另有1条既有requests依赖警告）、dkt-cicd离线验收`112`个断言、
Ruff、Compose、20个PowerShell脚本/模块解析、6个YAML、JavaScript和`git diff --check`通过。当前未完成项转为：推送本轮提交、
基于该提交的真实CI/Release、生产固定机制安装、`apply=false`预检、用户新确认后的正式切换、真实账号浏览器验收及24小时观察。
因此阶段8继续保持“进行中”，本地证据不等价于生产认证。

#### 12.2.6 预检日志源码占位符兼容修复（2026-08-28）

针对提交`5e77097db7e5c58310dc8ede1445a13f99b5a629`的正式部署预览，发现GitHub Actions的PowerShell日志会同时保留脚本源码行和实际输出行。源码行可能出现
`IWORK_CONFIG_ARTIFACT_DIGEST=$env:CONFIG_ARTIFACT_DIGEST"^[[0m`，不能被当作第二个Artifact Digest；此前因此在正式切换前失败关闭，未触发`apply=true`，生产未改变。

修复规则固定为：先去除PowerShell/ANSI尾码和引号，再过滤已知源码占位符（`$artifactDigest`、`$env:CONFIG_ARTIFACT_DIGEST`），最后要求实际值为唯一完整的`sha256:<64位小写hex>`；未知文本、非法Digest、缺失值或多个不同Digest仍失败关闭。回归测试新增真实预检日志形态，覆盖Release与Preflight两条路径；修复后的离线验收为`114`个断言通过，PowerShell Parser与`git diff --check`通过。

本修复尚未形成新的远程提交；必须以修复后的新Commit重新执行CI、Release和`apply=false`预检，不能复用旧Commit的Release/预检证据。正式部署仍需重新生成预览并等待用户逐字确认，避免把解析修复误当成生产切换成功。

### 12.3 2026-08-27 Portal部署阻断与机制认证迁移

Portal生产部署运行
[`33027031233`](https://github.com/GuChenkano/DTD_nginx/actions/runs/33027031233)
在生产切换前失败，状态收据为`failed_before_switch`。失败原因不是候选镜像、数据库或容器健康，
而是原`Assert-SuccessfulDrillEvidence`要求当前候选Commit及两个镜像Digest与历史v3演练完全
相同。历史v3绑定`254cb2d...`，因此不能授权新候选`3bcc7a1...`。只读核验确认Portal、
Authorizer和oauth2-proxy仍运行v3成功恢复后的`254cb2d...`镜像，均`healthy`、重启0次；没有
候选容器、部署锁或维护标记残留，本次失败没有发生生产切换。

长期修正采用“应用发布身份与部署机制身份分离”：

- 应用Commit和OCI Digest继续用于CI、Release、Runner smoke、候选验证及部署收据审计，但不再
  作为回滚能力证书的复用键。
- 部署机制由`production-deployment-mechanism/v1`清单绑定安装器/Runner Hook生成逻辑、认证核心模块、Portal部署Adapter、
  生产协调契约、部署Workflow和Runner smoke Workflow的SHA-256，并计算稳定机制指纹。Runner启动
  钩子按当前Commit从GitHub只读获取本次启动的Workflow并比对各自认证哈希，因此应用代码Commit
  可变，任一生产Runner Workflow变化都会失败关闭。
- `production-deployment-capability-proof/v1`登记一次真实机制演练；只有候选健康、生产切换、
  受控回滚、生产基线恢复和协调清理全部成功，才能签发90天有效的
  `production-deployment-capability-certificate/v1`。任一观察失败时只生成带签名的失败Proof Result，
  不创建能力证书。
- 能力claim、证书和吊销收据使用受ACL保护的本机随机密钥进行HMAC-SHA256签名；证据采用
  `CreateNew`、同目录临时文件持久化后原子移动，禁止覆盖相同Run ID。
- 普通发布只验证当前机制指纹下未过期、未吊销、签名和载荷完整的成功证书；同一机制下更换
  应用Commit或Digest不要求重复演练。机制核心、部署Adapter或协调契约变化时，指纹变化并
  自动fail-closed，必须重新认证。
- 原`rollback_drill`、retry和recovery输入从活动Workflow移除，统一为`capability_drill`；
  Runner准入钩子不再按每个应用Commit钉死`GITHUB_SHA`，但继续固定Actor、仓库、分支、
  Workflow引用和服务器安装件SHA-256。安装器在Runner停止状态下原子注册
  `ACTIONS_RUNNER_HOOK_JOB_STARTED`，未完成Hook注册不得视为安装成功。

旧v1/v2/v3处理规则：

| 对象 | 处理 | 是否能授权新部署 |
|---|---|---:|
| `rollback-drill-v1.json` | 原路径、原内容和SHA-256永久保留 | 否 |
| `rollback-drill-v2.json` | 原路径、原内容和SHA-256永久保留 | 否 |
| `rollback-drill-v3.json` | 原路径、原内容和SHA-256永久保留 | 否 |
| 对应历史部署收据 | 继续作为审计事实保存 | 否 |
| `legacy-evidence-index.json` | 安装时将每个旧状态文件与Run ID一致的部署收据成对索引，标记`legacy_history / authoritative=false`；缺失收据则失败关闭 | 否 |
| `capabilities/portal/<fingerprint>/...` | 新claim、证书和吊销收据的唯一权威命名空间 | 是 |

禁止删除、移动、改名、覆盖或伪造旧v1/v2/v3；需要清理的只有候选容器、临时Compose、候选敏感
环境文件、过期锁和维护标记。旧证据保留不会造成门禁混淆，因为新认证模块只扫描
`capabilities/<service>/<fingerprint>/certificates`和对应吊销目录，永不读取状态根目录下的
旧文件作为授权依据。

本地实现范围位于Portal仓库，包含能力模块、机制清单、部署Adapter、安装器、Workflow、CI和
行为测试；本轮不安装服务器策略、不触发Workflow、不重启或切换生产。生产落地仍需单独完成：

1. 合并并发布Portal变更，通过CI、Release和Runner smoke。
2. 在提升权限的生产执行会话安装新部署机制包；安装器幂等创建签名密钥并生成旧证据索引，
   不修改任何旧证据；同时注册Runner作业启动Hook，之后按既有运维流程启动Runner并先做smoke。
3. 先执行`apply=false`候选预检。
4. 在独立维护窗口显式执行一次`capability_drill=true`机制认证；失败即停止，不自动重复。
5. 认证成功后再以新候选执行普通部署；普通部署复用机制证书，不再按每个Commit重演练。
6. 完成真实登录、六应用、iwork SSE、容器健康、锁清理及24小时观察。

本地验收结果：机制认证与阶段5目标测试48项通过；Portal Django测试72项通过；离线配置测试
158项通过、2项跳过、39个subtests通过；Ruff、迁移检查、Windows PowerShell 5.1语法、Actions YAML、
六项机制哈希及`git diff --check`均通过。双轴复审发现的失败证书、临时Compose残留、Runner Hook
未注册、旧证据集合不完整、未知清单字段、异机制证书静默跳过和Runner注册文件可写问题均已修复并复测。
当前机制证书目录中只要出现签名有效但身份不属于当前机制的证书，整个准入即失败关闭；安装器仅在
Runner已停止的维护阶段临时给予生产执行身份必要写权限，结束或失败后会把固定工具、Hook、Runner
`.env`、legacy index及其索引的旧状态/收据恢复为只读，并显式拒绝该身份写入或删除。
能力证书还会回查同一Run ID的原始claim文件、文件SHA-256、身份、载荷哈希和HMAC签名；固定
工具/策略目录与Runner注册文件锚点拒绝重解析点及父目录替换。
固定工具、策略和状态目录使用专用父目录锚点；StateRoot全程保持旧证据删除保护，候选临时文件
依靠自身权限正常清理，最终阶段重新断言保护且目录缺失时阻断。部署与Runner smoke的临时Docker凭据目录也必须
位于`RUNNER_TEMP`内且不是重解析点。

阶段状态：进行中（2026-08-27；生产保持未变；部署机制认证本地实现、验证、复审和仓库提交完成后，
仍需CI/Release、生产安装、一次真实机制认证和最终Portal部署，不能把本地测试表述为生产认证成功）。

## 13. 全局风险控制

| 风险 | 控制措施 |
|---|---|
| Docker仅在交互用户上下文可用 | 阶段1先验证身份和常驻方式，不直接装SYSTEM Runner |
| 两仓库同时部署 | 使用服务器级共享锁，不只依赖GitHub concurrency |
| 生产服务器源码构建不稳定 | GitHub托管Runner构建GHCR不可变镜像，生产只拉取Digest |
| Portal故障影响所有应用 | 候选实例、Nginx原子切换、真实登录验收和自动回滚 |
| 看门狗误判合法维护 | 统一维护标记、超时和Run ID协议 |
| 生产密钥泄露 | 密钥只留服务器，不传GitHub、不写日志、不进入镜像 |
| 生产配置漂移 | 配置由批准Commit生成不可变配置包；部署只接受配置Digest，并与镜像Digest、Commit和request_id成对核验 |
| PR代码接触生产Runner | 生产Runner禁止PR和pull_request_target触发 |
| Runner覆盖服务器工作区 | 使用独立Runner工作目录，禁止clean/reset生产仓库 |
| 可变镜像无法追溯 | 生产仅使用完整Digest，不使用latest |
| Actions Run误关联或Digest误解析 | 以request_id、仓库、Workflow、分支、Commit和唯一databaseId关联；Release输出稳定artifact_digest，歧义即失败关闭 |
| 自动回滚破坏数据 | 回滚只切换应用镜像，不回滚或重建共享数据库和卷 |

## 14. 下一步

阶段5、阶段6和阶段7已经完成。真实账号浏览器业务验收按用户2026-08-26明确决定记录为风险豁免，不再阻断后续阶段：

1. 已完成：Portal修复提交`254cb2d...`通过本地全套测试、双轴审查、CI和GHCR发布。
2. 已完成：服务器准入固定到`254cb2d...`及部署脚本SHA-256；服务器仓库安全快进且保留未跟踪证书材料。
3. 已完成：精确Digest Runner smoke和`apply=false`生产预检成功。
4. 已完成：独立v3状态文件绑定并保留v1/v2失败证据；唯一一次v3恢复演练成功，形成`rolled_back / RollbackSucceeded=true`收据。
5. 已完成：最终生产部署成功，Portal、Authorizer和oauth2-proxy使用批准Digest并healthy；Keycloak、Nginx、数据库、Redis、网络和物理卷未重建。
6. 已完成：新旧入口、OIDC issuer、六应用未登录路由、iwork生产详情和SSE自动化验收。
7. 风险豁免：真实账号浏览器验收未执行，不表述为实际通过；证书工作继续沿用既有待办方案。
8. 已完成：统一跨仓库锁、维护标记、看门狗、周重启和异常恢复协议，并完成本地隔离测试及双轴复审。
9. 已完成：服务器安全快进两个批准提交，保留Portal既有未跟踪文件；生产准入脚本和协调模块按固定哈希安装。
10. 已完成：Portal与iwork的Runner smoke及`apply=false`生产预检成功；收尾无锁、无维护标记、无候选容器残留，业务容器保持`healthy`。
11. 已完成：安装并验收`dkt-cicd` Skill；72个离线断言、真实只读Actions查询、Digest提取、
    高等级生产确认门禁和独立前向测试通过，阶段7没有触发真实Workflow。
12. 进行中：Portal运行`33027031233`因旧v3证据精确绑定旧候选而在切换前失败，生产未变。
     当前先完成部署机制认证的本地代码、测试、审查和提交；后续需经CI/Release、生产安装、
     一次真实机制认证和新的Portal部署。旧v1/v2/v3永久保留为非权威历史证据，不做物理清理。
13. 已完成代码交付与生产切换：iwork实时读模型缓存残留修复已提交为`285da66c2fcc04b2477a68a7617a7e24cce4406b`，
      本地全量`602 passed`，并完成真实CI、Release、生产准入、`apply=false`预检和正式部署。CI运行
      `33156467031`、Release运行`33156869242`、预检运行`33157349938`、正式部署运行`33157867624`均为
      `completed/success`；三类Digest和四个`request_id`已在证据链中逐项一致，服务器`active-release.json`与两容器
      均已切换到该Commit和镜像。真实账号浏览器验收按风险豁免记录，阶段8仅剩24小时稳定观察。

阶段5继续沿用以下边界：Package保持私有，生产只接受完整Digest；Runner不checkout、不build、不运行PR代码、不保存个人PAT，不读取或提交`D:\DM\dkt-secrets.env`；不清理或重置服务器Git工作区；任何证据缺失、身份不符、健康失败或回滚失败均fail-closed。

## 14.1 2026-08-28 iwork 正式部署阻断与跨身份 Mutex 修复（追加记录）

提交 `029fa6fc6203f5b4f785d800e649d4eac7c7521f` 的正式部署 Run
[`33146302986`](https://github.com/GuChenkano/iwork/actions/runs/33146302986)
在生产切换前失败，原始错误为：

```text
Access to the path 'Global\\DKT-Docker-Recovery' is denied.
```

生产只读核验确认未发生切换：`DKT_iwork` 与 `DKT_iwork_alert_worker` 仍为旧版本且健康，未留下部署锁、维护标记或候选容器。根因是 Docker 健康看门狗以 `SYSTEM` 身份创建共享恢复 Mutex，而生产 Runner 以 `DONGMING\\shuju` 运行；首个创建者的默认 DACL 未授权另一身份打开。

修复要求覆盖全部共享创建方，而不是仅在 iwork 端增加重试：iwork/Portal 部署脚本和 DTD_nginx Docker 看门狗的生产共享Mutex继续使用显式ACL（`SYSTEM`、本机 Administrators和严格解析的`ExpectedIdentity`）；两仓库生产协调审计Mutex与环境无关，只授权`SYSTEM`、本机Administrators和当前执行SID，不解析或硬编码生产域账号。对短暂 `UnauthorizedAccessException` 仅做有界重试，权限错误始终失败关闭并输出身份、Mutex 名称和原始错误。Windows named Mutex 的安全描述符只在新建对象时生效，因此生产安装前还必须确认没有看门狗/部署任务持有旧对象；不能把重试当作旧 ACL 修复。

本轮当前已完成两仓库本地修复与回归：iwork 协调模块新SHA-256为`0f2e7346e32bcc3dd59195b607c0ade58d11e3ee264d16292e8e669a7f614bc7`，Workflow已同步固定该哈希，阶段4测试`39 passed`、全量测试`601 passed`；DTD_nginx 协调模块新SHA-256为`5a19f0a43735f2e4ac73dde516c755a7a4fb42391fe5b705c631e5ca6fee077c`，机制清单已同步，目标测试`90 passed`且协调、并发和看门狗PowerShell测试通过。待完成两仓库提交推送、真实Hosted CI、生产固定机制安装与Portal机制重新认证、iwork Release、`apply=false`预检和一次正式部署。`029fa6f` 的旧 Release、配置包、预检与失败 Deploy 证据不可复用；正式部署必须使用修复后新 Commit 的完整三类 Digest和新的`request_id`。阶段8继续保持“进行中”。

首次修复提交 `7ac31b9...` 的 CI Run `33148404438` 暴露托管Runner身份兼容问题：Hosted Runner 没有 `DONGMING\\shuju` 域账号，协调审计 Mutex 的无条件SID解析使隔离测试失败，生产未受影响。当前修复为协调审计ACL仅授权`SYSTEM`、本机Administrators和当前执行SID，完全移除生产域账号解析；生产入口仍严格校验真实 `ExpectedIdentity`，错误身份继续失败关闭。新增真实协调锁/审计写入和错误身份门禁回归，阶段4目标测试本地`39 passed`；当前改动尚未提交，必须重新通过真实CI后才能进入Release和生产准入。

## 14.2 2026-08-28 iwork 最终生产交付与观察

本节覆盖并更新14.1之后的实际证据；旧失败Run和旧Digest仍只作历史审计，未被复用。

- 最终提交：`285da66c2fcc04b2477a68a7617a7e24cce4406b`，本地、`origin/Keycloak`和服务器部署收据一致。
- CI：[`33156467031`](https://github.com/GuChenkano/iwork/actions/runs/33156467031)，`completed/success`，`request_id=3fec1a71-ffca-40d4-81b8-f51349b542a9`。
- Release：[`33156869242`](https://github.com/GuChenkano/iwork/actions/runs/33156869242)，`completed/success`，`request_id=c11b9b6a-7b8f-4c1d-8b6a-4f4b3120497e`。
- Release三类Digest：Image=`sha256:ff24fa37f26f461005fa52838c9f49078a0b605171470dccb5064a8da3403be3`；Config=`sha256:979bbbf1dfecd37a37f8eb654911ed9075c94df3f981b24198699301364fb53b`；Config Artifact=`sha256:a304118c8bad767a4b678a3f8d5d40737c1db3a25a917eb00f3c75b7538532a1`。
- 生产准入已更新到最终机制哈希；预检：[`33157349938`](https://github.com/GuChenkano/iwork/actions/runs/33157349938)，`completed/success`，`request_id=c8b494ee-b4be-4c1f-9c94-9a4b09bc3156`，`PreflightRunId=33157349938-1`。
- 正式部署：[`33157867624`](https://github.com/GuChenkano/iwork/actions/runs/33157867624)，`completed/success`，`request_id=bb2051bf-b3bb-4a58-9c1c-ca0a5f142628`，耗时76秒；确认词为`DEPLOY IWORK 285da66c2fcc04b2477a68a7617a7e24cce4406b`。服务器收据`33157867624-1.json`为`deployed`，`active-release.json`四项绑定值与Release一致。
- 生产只读核验（2026-08-28 17:08 +08:00）：`DKT_iwork`和`DKT_iwork_alert_worker`均`running/healthy`、RestartCount=0，配置镜像均为上述Image Digest且OCI revision为最终Commit；`DKT_iwork_redis`、`DKT_mysql`健康，Celery ping为`pong`，Redis为`PONG`。
- 业务探针：HTTPS健康端点`204`；容器内应用根路径`200`；实时API`200 application/json`；SSE`200 text/event-stream`。外部未带用户会话的实时API/SSE返回`401`，符合认证预期。部署后最近10分钟iwork/worker日志未发现错误或连接失败。
- 收尾：部署锁、维护标记、候选/回滚运行容器均不存在；历史`.candidate.yml/.rollback.yml`仅作为审计留存。未执行数据库迁移、Redis清理、Keycloak/共享卷/网络/Nginx重建。
- 当前状态：阶段8仍为“进行中”，原因仅为24小时稳定观察尚未完成；真实账号浏览器验收按用户决定作为风险豁免，不宣称实际通过。
## 14.3 2026-08-31 阶段8后续改造实施（本地已验证，外部未执行）

用户提出的《2026-08-31-iwork-CICD最终修改方案》作为设计入口，进度仍以本总方案为唯一基线。
本轮在工作树实现了部分切片并完成隔离验证；尚未推送本轮Commit、未配置生产签名材料、未更新
生产Runner准入，也未触发新的Actions或生产部署，因此阶段8继续保持“进行中”。

设计稿已按审查结论明确：
- 完整 CI 与无生产权限的轻量 PR/Push 检查分离；切换触发器必须在 Skill 编排验证完成后最后执行。
- 采用 publish（本次 CI→Release）与 release（消费明确 CI 证据）两个语义，Release 成功不自动进入生产 Preflight。
- 配置 Artifact 先上传，随后单独生成并上传 Release Manifest；Manifest Artifact digest 作为外部信任锚，禁止自引用。
- Deploy 绑定 Release Run/attempt、两个 Artifact 的 id/name/digest、Commit、request_id 和三类 Digest，禁止“最新成功”猜测。
- GHCR 仅明确 404 允许创建新标签；其他认证、网络、限流和服务端错误失败关闭；新镜像须隔离 Smoke 后推送。
- 外部 HTTPS/OIDC/SSE/业务探针先 observe-only 建基线，再按候选故障与共享依赖故障分级；证书校验不得绕过。
- 迁移必须有 migration_policy_id 和机器可验证兼容性证据；无证据时不允许自动应用回滚；手工回滚仅限历史实际 deployed 且未撤销版本。
- 目标准入模型为机制指纹，ApprovedHeadSha 仅为迁移期补偿；临时凭据和配置目录清理失败必须形成告警收据。
- Manifest本体不包含自身Artifact ID/Digest，避免自引用；配置Artifact与Manifest Artifact分离，上传后
  的外部ID/Digest由指定Release Run与Artifact API元数据绑定。Deploy会下载两个原始ZIP并重新计算SHA-256，
  再校验解压内容、Manifest签名和配置文件哈希。
- RSA `RSASSA-PKCS1-v1_5-SHA256` 签名已作为强制Release/Deploy门禁；签名私钥只来自GitHub Secret，
  验证证书和Key ID来自受保护配置，缺失、轮换不一致或验证失败均失败关闭。
- 正式`apply=true`只允许Workflow `run_attempt=1`；重跑不得复用确认或request_id，必须重新生成预览/确认。
- 服务器固定脚本使用不可覆盖的`request-consumption`收据绑定预检和正式部署；阶段4夹具已同步该收据，
  防止直接触发或换Run重放同一request_id。

当前本地证据：`tests/test_ci_workflow.py`、`tests/test_production_config_bundle.py`、
`tests/test_production_deployment_stage4.py`组合测试`68 passed`，`dkt-cicd`离线验收为`133`个断言通过；
20个PowerShell脚本/模块解析和`git diff --check`通过。完整CI已从Push/PR完整触发和临时Docker构建切换为仅
`workflow_dispatch`，PR由无生产权限的`ci-pr.yml`提供轻量反馈。

下一入口按设计稿第12节：完成最终全套本地门禁与Skill安装副本哈希复验；由管理员安全配置三项
Manifest签名材料；在Runner空闲维护窗口安装并复验固定部署机制；之后才允许推送、真实CI/Release、
`apply=false`预检和用户新确认后的正式Deploy。任一新失败立即停止并回写本总方案，不得复用旧Commit、
旧Release或旧预检证据。
