# Agent Reuse Guide

## 部署入口

| 路径 | 调用场景 | 效果 |
|------|----------|------|
| `deploy.ps1` | 单独部署 iwork | 加载 `env/local.env` 或 `env/production.env` 与中央密钥，构建 `DKT_iwork`，重载 Nginx 并执行容器内 HTTP 检查 |
| `restart_services.ps1` | 仅需重启应用进程 | 重启 `DKT_iwork`，不操作共享 MySQL、Redis 或数据卷 |
| `stop_services.ps1` | 临时停止 iwork | 停止 `DKT_iwork`，保留共享基础设施 |
| `uninstall_services.ps1` | 清理旧 NSSM 部署 | 删除历史 `iwork-django`、`iwork-daphne`、Celery Windows 服务，不操作 Docker 数据 |
| `..\DTD_nginx\scripts\Rebuild-Local.ps1` | Portal 与 iwork 联合重建 | 推荐入口；从 DTD_nginx 根目录调用 `-Target iwork` 或 `-Target all` |

## 本地部署规则

- 本地工作区中的代码或配置修改允许在尚未提交、尚未推送时，直接部署到本地 Docker 进行验证。
- 本地部署不要求 Git 工作区干净；部署前应确认差异范围，避免把无关文件或敏感配置打入镜像。
- 本规则仅适用于 `local` 环境，不代表允许把未提交代码部署到服务器或生产环境。
- 服务器或生产部署继续以已审查、可追溯的 Git 提交为准，并遵守既有拉取、重建和回滚流程。

## 测试入口

- `pytest tests/ -q` 使用 `iwork.test_settings`，通过内存 SQLite、LocMem 和内存 Celery 运行，不连接生产数据库。
- `ruff check <本次涉及的 Python 文件>` 用于检查修改范围；全仓仍有历史 lint 债务。

## Agent 约束

- `sqlite/production_orders.db` 是人工传输的一次性导入源，不得提交。
- `DKT_iwork` 的 8000 端口只在 `docker_dkt-net` 内暴露，不得重新映射到宿主机。
- 真实密码只来自相邻工作区的 `dkt-secrets.env`，不得写入 `env/*.env`。
- 开发与部署分支统一为 `Keycloak`，不得继续在 `main` 开发或周期性合并 `main`。
- 不删除共享 MySQL、Redis、PostgreSQL 或 Keycloak 数据卷。
