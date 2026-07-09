# ADR 005 — Keycloak 分支替代 main 成为主开发分支

> 日期：2026-07-09 | 状态：已采纳

---

## 背景

iwork 仓库存在两个独立的历史线：
- `main` 分支：根提交 `6403414`（2026-04-21，"项目初始化"），211 次提交，最后活跃 2026-06-08
- `Keycloak` 分支：根提交 `47c80b2`（2026-06-09，"iwork 生产看板 初始提交"），100+ 次提交，持续活跃至今

两者无共同祖先（`git merge-base` 为空），`git merge` 会报 `fatal: refusing to merge unrelated histories`。两个分支共享几乎相同的文件结构（43+ 个同名 Python 文件），但 Keycloak 分支的代码规模是 main 的 4~10 倍，包含看板、产品视图拖拽、热力图、工单目标管理、产量看板等所有功能。

## 决策

**Keycloak 分支作为唯一的开发分支，废弃 main。**

## 原因

1. **Keycloak 是 main 的完整超集**：所有 main 中的功能均已包含在 Keycloak 分支中，且 Keycloak 在之上持续开发了一个月（42 次未推送提交）。
2. **合并不可行**：`git merge --allow-unrelated-histories` 会导致几乎每个共有文件冲突（无三路合并基础），手工解决成本等同于重写项目。
3. **Keycloak 实际上是 v2 重写**：取 main 代码为基础，从零重建 git 历史（`--orphan`），统一了认证架构（Keycloak OIDC → TrustedProxyMiddleware），是一次有意的架构升级。

## 影响

- GitHub 默认分支需从 `main` 切换到 `Keycloak`
- 旧 `main`、`export-gui`、`feat/order-judge-workflow`、`server` 分支已清理
- 未来所有开发基于 `Keycloak` 分支
- 旧 `main` 保留至 GitHub 默认分支切换完成后删除
