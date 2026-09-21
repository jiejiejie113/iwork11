# 交付文档与离线包统一加 PCI- 前缀

## 范围（按"不影响系统运行"筛选）

已核对：`docs/` 路径不被 `iwork/` 运行时、Dockerfile/Compose、`.github`、`scripts/`、
`tests/` 引用（`.dockerignore` 还将 `docs`、`sqlite` 排除出镜像），因此重命名文档
不影响系统运行。

命名规则：`PCI-` + 原文件名。

| 分组 | 数量 | 示例 |
|------|------|------|
| 根目录业务文档 | 2 | `PCI-PYTCKREG3表索引结构.json`、`PCI-看板框架&前后端数据映射.md` |
| `docs/开发文档/` | 6 | `PCI-iwork规范手册.md` |
| `docs/部署文档/` | 5 | `PCI-docker-deployment.md` |
| `docs/` 根级活文档 | 2 | `PCI-CI-CD.md`、`PCI-architecture_flowchart.html` |
| 离线包命名 | 1 | `dist/PCI-iwork-offline-<时间戳>.zip` |

## 保持原名（历史资料与运行契约）

- 历史文档：`docs/changelogs/**`、`docs/adr/**`、`docs/superpowers/**`、
  `docs/2026-08-21/28/31-*`CICD方案与Owner-ACL规范、`docs/docker-sync-2026-07-09.md`。
- 运行与部署：`iwork/**`、`Dockerfile`、`docker-compose*.yml`、`requirements*`、
  `manage.py`、`start.sh`/`entrypoint.sh`、`deploy.ps1` 等。
- 契约与工具：`AGENTS.md`、`CLAUDE.md`、`CONTEXT.md`、`README.md`、`.github/**`、
  `scripts/**`、`tests/**`、`tools/skills/**`、`env/**`。

## 引用同步

- `README.md`（11 处链接 + 目录树）、`CLAUDE.md`（1 处）、
  `docs/2026-08-21-...md`（2 处）、`docs/adr/004`（2 处）、
  `docs/changelogs/2026-09-16-...md`（3 处）、`docs/superpowers/` 4 篇（7 处）。
- 全仓链接校验：Markdown/HTML 链接目标解析 0 处失效。

## 验证

- `pytest tests/ -q` 全量通过；`tests/test_offline_bundle.py` 已断言
  `PCI-iwork-offline-*.zip` 命名。
- 离线包 `dist/PCI-iwork-offline-20260921-112742.zip`：270 项清单与压缩包条目
  逐文件哈希一致（无缺失、无多余），MANIFEST 使用正斜杠。
- 旧路径/旧文件名在跟踪文件内容中零残留；容器未重建（文件不在镜像内）。

## 说明

- 首次执行曾出现 `PCI-PCI-` 双重前缀，已定位为"完整路径替换后又命中裸文件名替换"，
  修复为先替换链接裸文件名（带 `(?<!PCI-)` 幂等保护）再替换完整路径，并全仓复核为零。
