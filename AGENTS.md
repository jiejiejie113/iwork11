# Agent Reuse Guide

## 部署入口

| 路径 | 调用场景 | 效果 |
|------|----------|------|
| `deploy.ps1` | 单独部署 iwork | 加载 `env/local.env` 或 `env/production.env` 与中央密钥，构建 `DKT_iwork`，重载 Nginx 并执行容器内 HTTP 检查 |
| `.github/workflows/deploy-iwork.yml` | 生产GHCR受控部署 | 仅在固定生产Runner上调用已安装且哈希固定的部署脚本；预检默认只读，显式确认后同时切换`DKT_iwork`与`DKT_iwork_alert_worker`并在失败时自动回滚 |
| `scripts/Invoke-IworkProductionDeployment.ps1` | 生产部署深层模块 | 负责Digest/revision复验、共享锁、备份、Compose覆盖、双容器健康验收和自动回滚；必须由`Install-IworkProductionDeployment.ps1`安装到服务器固定目录，禁止从Runner工作区直接调用 |
| `restart_services.ps1` | 仅需重启应用进程 | 重启 `DKT_iwork`，不操作共享 MySQL、Redis 或数据卷 |
| `stop_services.ps1` | 临时停止 iwork | 停止 `DKT_iwork`，保留共享基础设施 |
| `uninstall_services.ps1` | 清理旧 NSSM 部署 | 删除历史 `iwork-django`、`iwork-daphne`、Celery Windows 服务，不操作 Docker 数据 |
| `..\DTD_nginx\scripts\Rebuild-Local.ps1` | Portal 与 iwork 联合重建 | 推荐入口；从 DTD_nginx 根目录调用 `-Target iwork` 或 `-Target all` |

阶段4当前只完成代码和隔离测试；未完成生产基线记录、固定提交准入安装和真实预检前，部署Workflow不得替换生产容器或声称已完成生产回滚验收。`apply=false`仍会把指定Digest拉入Docker镜像缓存，但不会重建、重启或替换运行容器。

## 本地部署规则

- 本地代码或配置修改完成并通过相应测试后，默认必须按提交规范提交 Git，再重建本地 Docker 应用并验证接口；用户明确要求暂不提交、暂不部署或仅修改代码时除外。
- 开发过程中允许将尚未提交、尚未推送的修改部署到本地 Docker 做中间验证，但不能替代完成修改后的 Git 提交和最终重建验收。
- 本地部署前应确认差异范围，避免把无关文件或敏感配置打入镜像；未经用户明确要求，不自动推送远程。
- 本规则仅适用于 `local` 环境，不代表允许把未提交代码部署到服务器或生产环境。
- 服务器或生产部署必须以已审查、可追溯的 Git 提交所生成的不可变配置包和镜像为准；生产配置不得直接从服务器 Git 工作区读取或作为部署输入。服务器 Git 工作区仅用于受控运维上下文，不能替代配置包。

## 测试入口

- `pytest tests/ -q` 使用 `iwork.test_settings`，通过内存 SQLite、LocMem 和内存 Celery 运行，不连接生产数据库。
- `ruff check <本次涉及的 Python 文件>` 用于检查修改范围；全仓仍有历史 lint 债务。

## Agent 约束

- `sqlite/production_orders.db` 是人工传输的一次性导入源，不得提交。
- `DKT_iwork` 的 8000 端口只在 `docker_dkt-net` 内暴露，不得重新映射到宿主机。
- 真实密码只来自相邻工作区的 `dkt-secrets.env`，不得写入 `env/*.env`。
- 开发与部署分支统一为 `Keycloak`，不得继续在 `main` 开发或周期性合并 `main`。
- 不删除共享 MySQL、Redis、PostgreSQL 或 Keycloak 数据卷。

## CI/CD长期方案维护

- GitHub Actions、GHCR、生产Self-hosted Runner、自动部署、回滚或`dkt-cicd` Skill相关开发，必须以`docs/2026-08-21-GitHub-Actions-CICD完整实施方案.md`为唯一进度基线。
- 生产受控链路当前绑定：仓库`jiejiejie113/iwork11`、分支`Keycloak`、actor`jiejiejie113`、镜像`ghcr.io/jiejiejie113/iwork11`、Portal跨仓库协调`jiejiejie113/DTD_nginx`（2026-09-21自`GuChenkano`迁移，依据见总方案第15节）。
- 离线运行通道（用户明确要求、不依赖Git）：`scripts/New-IworkOfflineBundle.ps1`生成`dist/PCI-iwork-offline-<时间戳>.zip`，目标机解压后用`deploy.ps1 -Environment production`运行；该通道绕过受控发布的Digest/预检/回滚/准入，风险边界与验收证据由总方案第16节维护，修改该通道必须同步更新第16节。
- 每完成一个实施阶段，Agent必须在同一阶段提交中同步更新该文档，至少记录：阶段状态、完成日期、实际提交、Actions运行链接、测试与验收证据、发现的问题、方案偏差及下一阶段入口。
- 阶段只在全部验收条件有实际证据时标记为“已完成”；部分完成必须逐项列出未完成内容，禁止仅因代码已提交而标记完成。
- 发生阻断、回滚或设计调整时也必须更新该文档，不得让代码状态与方案进度脱节。
- 在该文档所有阶段标记为“已完成”前，后续Agent必须延续维护；不得另建重复的CI/CD总方案替代本文件。
- 当前GitHub套餐无法启用Environment Required Reviewer和`Keycloak`分支保护；不得把Workflow的`environment`声明视为有效审批。生产准入必须固定人工批准的完整Commit SHA、Workflow路径、actor、仓库、分支和服务器部署脚本SHA-256。
- 每批准一个新的部署Workflow提交，都必须在Runner空闲时更新服务器准入策略；旧的、已删除或当前不可拉取的GHCR Digest不得作为生产部署输入。
- 生产发布必须使用同一批准Commit绑定的不可变配置包和镜像Digest；配置包Digest、镜像Digest与Commit必须逐项成对核验并写入Workflow摘要、部署状态和锁事件。配置包不得包含生产密码，生产密钥仍只来自服务器中央密钥文件。
- 生产配置包必须由受控发布流程生成并按完整Digest引用，部署Workflow不得从服务器 Git 工作区读取 `env/production.env` 作为候选配置；服务器只接受已核验的配置包并在切换前后记录其Digest。
- `scripts/New-IworkProductionConfigBundle.ps1` 是配置包唯一生成入口；包只包含清单、Compose和生产环境文件，配置文本统一为严格UTF-8、LF、无BOM，`config_digest`必须是完整的`sha256:`加64位小写十六进制值。
- 每次用户请求生成唯一`request_id`，并贯穿Skill、CI/Release/Deploy Run、Digest解析、部署锁、状态收据和回滚收据；Actions的`GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT`只作为平台Run标识，不能替代或复用`request_id`。
- 只有部署机制本身（安装器、Runner准入Hook、固定部署脚本、协调协议、部署Workflow或Runner smoke契约）变化时，才必须重新安装生产准入策略。迁移期可以暂时保留`ApprovedHeadSha`作为旧Hook的补偿门禁，但不得因此跳过不可变配置包、镜像/配置/Commit绑定或`request_id`核验；迁移完成后应切换到机制指纹准入。
- `dkt-cicd` Skill的Git版本源固定为`tools/skills/dkt-cicd`，`%USERPROFILE%\.agents\skills\dkt-cicd`仅是安装副本。修改Skill后必须运行`scripts/Install-DktCicdSkill.ps1`并验证逐文件SHA-256一致，禁止只改用户目录而不提交版本源。
