# ADR 005: Keycloak 是唯一开发分支

> 日期：2026-07-09 | 更新：2026-07-14 | 状态：已采纳

## 背景

iwork 曾同时在 `main` 和 `Keycloak` 开发，导致功能和部署配置分散。2026-07-13 已将当时 `origin/main` 的新增提交合并到 `Keycloak`，其中包括 `Pydefstp`、`Pywrkstp` 和界面更新。此后两个分支已有共同历史，不应再用“无共同祖先”描述现状。

## 决策

`Keycloak` 是唯一开发和部署分支。`origin/HEAD` 必须指向 `origin/Keycloak`。

- 新功能、修复和文档只提交到 `Keycloak`；
- `main` 仅作为历史兼容分支，不直接开发；
- 不再周期性把 `main` 合并到 `Keycloak`；
- 若旧流程误把提交推到 `main`，先审查提交范围，再用 cherry-pick 或一次性合并取回，并立即停止该流程。

## 验证

```powershell
git symbolic-ref --short refs/remotes/origin/HEAD
# 期望：origin/Keycloak

git status --short --branch
# 期望：Keycloak...origin/Keycloak
```

## 影响

- CI、部署脚本和服务器工作区均检出 `Keycloak`；
- 远程默认分支保持 `Keycloak`；
- `main` 不作为“更新更快”的来源，避免再次形成双主线。
