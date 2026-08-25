# iwork GitHub Actions CI/CD

## 阶段0纯CI基线

本节记录阶段0只建设持续集成时的安全基线。当前GHCR、生产Self-hosted Runner和阶段4受控部署的实际进度，以[GitHub Actions、生产Runner与受控部署完整实施方案](2026-08-21-GitHub-Actions-CICD完整实施方案.md)为唯一基线；阶段4已经完成修复版生产切换和自动验收，正在执行一次性受控回滚演练。

- GitHub托管Runner运行Python 3.11测试、Ruff和Docker构建。
- pytest固定加载`iwork.test_settings`，三套数据库均为内存SQLite，缓存和Celery也使用进程内实现。
- Docker构建不加载`env/production.env`或`D:\DM\dkt-secrets.env`。
- 测试Job只删除可能被自动加载的仓库根`.env`，保留经过无密码契约检查的`env/local.env`和`env/production.env`；构建Job在Compose解析完成后删除全部`.env`，再创建镜像构建上下文。
- 不执行`docker compose up`、`deploy.ps1`、SSH、数据库迁移或服务器健康探测。
- 阶段0首轮不发布GHCR镜像，构建产物只存在于本次临时Runner中。

## 触发方式

- Push到`Keycloak`。
- 面向`Keycloak`的Pull Request。
- GitHub Actions页面手工触发`iwork CI`。

同一分支的新运行会取消尚未完成的旧运行，避免浪费托管Runner时间。

## 本地等价检查

```powershell
chcp 65001
python -m pip install -r requirements.txt -r requirements-ci.txt
python -m ruff check --no-cache --ignore E402,W292 iwork
python manage.py makemigrations --check --dry-run --settings=iwork.test_settings
python -m pytest tests/ -q
```

Docker配置与构建需要三个仅供解析的占位变量，禁止填写生产值：

```powershell
$env:IWORK_DJANGO_SECRET_KEY = 'ci-only-django-secret'
$env:IWORK_APP_DB_PASSWORD = 'ci-only-app-password'
$env:IWORK_DB_PASSWORD = 'ci-only-read-password'
docker compose --env-file env/local.env config --quiet
docker build --pull --tag ci-iwork:local .
```

## 当前阶段4受控部署边界

- `.github/workflows/deploy-iwork.yml`只允许手工触发，默认`apply=false`只拉取并校验指定Digest，不切换运行容器；镜像缓存会增加候选镜像，因此不是严格的零写入检查。生产Runner不checkout、不build，也不运行仓库工作区里的`deploy.ps1`。
- 部署只接受当前批准提交的完整GHCR Digest和匹配的OCI revision，并再次查询同一Commit的纯CI与GHCR发布成功记录；随后同时切换`DKT_iwork`与`DKT_iwork_alert_worker`。候选失败时使用部署前本地镜像ID回滚。
- 当前GitHub套餐不能配置Environment Required Reviewer或`Keycloak`分支保护，`production-iwork` Environment不能视为审批。生产服务器准入钩子必须固定人工批准的完整Commit SHA、Workflow路径、actor、仓库和分支，并固定校验服务器部署脚本SHA-256。
- 每批准新的部署Workflow提交，都必须在Runner空闲时重新安装服务器准入策略。未经该步骤的新提交即使已推送，也应被生产Runner拒绝。
- 旧的、已删除或当前不可拉取的GHCR Digest不得作为部署输入；阶段2旧iwork镜像缺少当前生产SSE修复，明确禁止重新部署。
- `run_migrations`默认关闭；开启时必须完成数据库兼容性审查和备份。自动回滚只恢复应用镜像，不自动覆盖生产数据库。
- `rollback_drill`默认关闭；只有`apply=true`、`run_migrations=false`且确认词严格为`ROLLBACK DRILL IWORK ONCE`时才允许执行。服务器使用不可覆盖的一次性记录拒绝重复演练，成功、失败或中断后都不会自动重试。
- 修复版生产预检、真实容器切换和自动验收已经完成。用户于2026-08-25明确豁免真实账号浏览器验收；一次性受控回滚演练形成真实`rolled_back / RollbackSucceeded=true`证据前，阶段4仍不得标记为完成。
