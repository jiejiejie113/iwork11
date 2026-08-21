# iwork GitHub Actions CI

## 当前范围

当前只建设持续集成，不包含生产部署：

- GitHub托管Runner运行Python 3.11测试、Ruff和Docker构建。
- pytest固定加载`iwork.test_settings`，三套数据库均为内存SQLite，缓存和Celery也使用进程内实现。
- Docker构建不加载`env/production.env`或`D:\DM\dkt-secrets.env`。
- 测试Job只删除可能被自动加载的仓库根`.env`，保留经过无密码契约检查的`env/local.env`和`env/production.env`；构建Job在Compose解析完成后删除全部`.env`，再创建镜像构建上下文。
- 不执行`docker compose up`、`deploy.ps1`、SSH、数据库迁移或服务器健康探测。
- 首轮不发布GHCR镜像，构建产物只存在于本次临时Runner中。

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

## 后续阶段

GHCR发布、生产Self-hosted Runner、部署审批和回滚工作流均不在本次范围。它们必须在生产密钥、Docker用户上下文及看门狗互斥机制完成专项验收后独立实施。
