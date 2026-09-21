# 离线运行通道（不依赖 Git）与离线运行包

## 背景

新 Windows Server 需要以本地文件直接运行 iwork：不依赖 Git、不经过 GitHub Actions 与
GHCR 受控发布。用户已明确要求并把该通道的风险接受交由运维层面记录。

## 交付物

- `scripts/New-IworkOfflineBundle.ps1`
  - 从当前工作树生成 `dist/iwork-offline-<时间戳>.zip` 与 `MANIFEST.sha256`。
  - 失败关闭：运行必需文件缺失、安全扫描命中禁止项时不产出包。
  - 排除：`.git`、虚拟环境、缓存、日志、`dist`、`.github`、`.env`、
    `local_dev_settings.py`、`dkt-secrets.env`、`*.pem/*.key/*.db/*.sqlite` 等。
  - 保留 `logs/`、`sqlite/` 运行期挂载目录占位。
- 目标机运行入口：`deploy.ps1 -Environment production`（仅依赖 Docker Compose、
  `env/production.env` 与 `D:\DM\dkt-secrets.env`，不读取 Git）。

## 目标机步骤

1. 解压离线包（保持目录结构）。
2. 放置中央密钥 `D:\DM\dkt-secrets.env` 并限制权限。
3. 首次初始化设置 `$env:IWORK_RUN_MIGRATIONS='true'`。
4. 确认 `docker_dkt-net`、`mysql`、`iwork-redis`、`DKT_kc_nginx` 与远程 `payroll` 可达。
5. 运行 `.\deploy.ps1 -Environment production`，脚本以容器内 HTTP 200 作为完成条件。
6. 用 `MANIFEST.sha256` 与整包 SHA-256 校验拷贝完整性。

## 验证

- 新增 `tests/test_offline_bundle.py` 3 项测试：必需文件缺失失败关闭、敏感项排除、
  清单哈希与运行文件校验，全部通过。
- 实测产物：`dist/iwork-offline-20260921-103625.zip`（270 文件，
  `sha256:af9a031e75205da13f561b002941c8952c689ae9744404090983efbccfea66b4`）。
- 离线包解压后 `docker compose --env-file env/production.env --env-file <密钥> config --quiet`
  返回 0。
- 端到端实测（本机）：解压到独立目录后运行 `deploy.ps1 -Environment local -SecretsFile <密钥>`，
  成功构建 `iwork-iwork` 镜像、重建 `DKT_iwork` 并 `healthy`；容器内 HTTP 200，
  今日目标接口 200 且 `analysis.status=available`。
- `deploy.ps1` 固定 `--project-name iwork`，任意解压目录可接管同一组容器，
  不会因目录变化出现容器名冲突。

## 风险边界

- 绕过不可变镜像 Digest、生产预检、自动回滚、服务器准入与审计收据；
- 目标机需具备构建镜像的网络（Debian 快照源、PyPI 镜像）；
- 该通道不改变第 15 节仓库绑定，也不替代受控发布链路；风险与后续偏差由总方案
  第 16 节维护。
