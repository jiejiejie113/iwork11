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

截至2026-08-21，基础纯CI已经完成。按整个CI/CD交付范围估算，总体约完成30%；纯CI子项目完成100%。

| 阶段 | 名称 | 当前状态 | 关键结果 |
|---:|---|---|---|
| 0 | 基线与纯CI | 已完成 | 两仓库GitHub托管Runner流水线已跑绿 |
| 1 | 生产Runner与Docker身份验证 | 未开始 | 服务器尚未安装Runner |
| 2 | GHCR不可变镜像发布 | 未开始 | 当前临时镜像不上传 |
| 3 | 生产Self-hosted Runner安装 | 未开始 | 需依赖阶段1结论 |
| 4 | iwork受控部署与回滚 | 未开始 | 不允许提前自动部署 |
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

| 仓库 | 初始CI提交 | 首轮修复提交 | 当前远程HEAD |
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

阶段状态：未开始。

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

阶段状态：未开始。

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

阶段状态：未开始。

## 8. 阶段4——iwork受控部署与自动回滚

### 8.1 工作流输入

- 镜像Digest，必填。
- 目标环境，当前只能是`production`。
- 是否执行数据库迁移，默认按既有发布规范处理。
- 变更说明或关联Commit。

不允许把任意Shell命令作为输入。

### 8.2 部署步骤

1. GitHub Environment审批。
2. 校验镜像Digest和对应CI、release运行状态。
3. 获取服务器级全局部署锁。
4. 检查看门狗、Docker周重启和已有维护标记。
5. 记录当前镜像Digest、Compose解析结果、容器ID、健康状态和重启次数。
6. 创建有过期时间的维护标记。
7. 拉取指定GHCR镜像Digest。
8. 执行`docker compose config --quiet`。
9. 只更新：

   - `DKT_iwork`
   - `DKT_iwork_alert_worker`

10. 禁止重建或删除MySQL、Redis、PostgreSQL、Keycloak和共享卷。
11. 执行容器健康检查、Django检查、API、页面认证、SSE和Alert Worker验收。
12. 成功后记录新Digest并释放维护标记和锁。
13. 失败时恢复旧Digest、重新启动旧容器并复验。

### 8.3 验收标准

- 部署只影响iwork两个应用容器。
- 失败能自动恢复到部署前Digest。
- SSE自动重连且无持续403或503。
- 数据库、Redis和历史数据不重建。
- 看门狗不会在合法维护窗口内误恢复。
- Actions摘要包含新旧Digest、耗时和验收结果。

阶段状态：未开始。

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

下一步只执行阶段1：生产Runner与Docker用户身份可行性验证。

阶段1完成前禁止：

- 注册永久Runner服务。
- 发布或部署GHCR生产镜像。
- 修改Docker Desktop服务启动方式。
- 使用SYSTEM直接执行Docker部署。
- 清理Portal服务器工作区。
- 建设可直接修改生产环境的Workflow。

阶段1执行完成后，Agent必须先更新本文档，再决定是否进入阶段2。
