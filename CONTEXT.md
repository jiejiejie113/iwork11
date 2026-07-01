---
name: iwork
description: 车间工效看板 — 实时生产数据仪表板，Django + SSE + Celery + Redis + MySQL
---

# iwork — 车间工效看板

## 项目目的
实时追踪服装生产车间工效数据，提供实时看板、历史查询、生产明细、数据同步功能。

## 领域术语

| 术语 | 英文 | 定义 |
|------|------|------|
| Flow | 流程/工序 | 生产流程类型，如裁剪、缝制、整烫等 |
| StepNo | 工序号 | 流程内的具体工序编号 |
| StationID | 工位 | 生产工位标识 |
| wrk_order | 工单 | 生产工单编号 |
| pytckreg3 | 生产记录表 | 核心生产数据表，记录每个工位的操作日志 |
| Target | 目标产量 | 每道工序的目标产出量 |
| Remote DB | 远程数据库 | 只读的生产数据库（default） |
| Local DB | 本地数据库 | 可写的本地数据库（iwork/iwork_local） |

## 部署上下文
- Portal 子路径: `/iwork/`
- 认证: Keycloak OIDC → oauth2-proxy → Remote-User header
- 容器: DKT_iwork (Docker), 端口 8000
- 网络: docker_dkt-net
