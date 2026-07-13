# Docker 同步差异报告

**日期**: 2026-07-09
**来源分支**: Keycloak (合并至 main)
**提交范围**: `e3a2926` → `bed62c8` (35 commits)
**本地 commit**: `bed62c8`

## Nginx 配置

Status: 一致 (7 个文件逐一对比，0 处差异)

## iwork 代码差异

Docker 镜像落后于本地最新代码，差异集中在**产量看板模块**。

### 缺失文件 (Docker 中不存在)

| 文件 | 行数 | 说明 |
|------|------|------|
| `iwork/templates/iwork/kanban.html` | 620 | 产量看板前端页面 |
| `tests/test_kanban_api.py` | 127 | 看板 API 测试 |
| `tests/test_kanban_queries.py` | 354 | 看板查询测试 |

### 代码增量

| 文件 | Docker 行数 | 本地行数 | 增量 |
|------|------------|----------|------|
| `iwork/queries.py` | 708 | 958 | +250 |
| `iwork/local_queries.py` | 644 | 799 | +155 |
| `iwork/api_views.py` | 571 | 722 | +151 |
| `iwork/views.py` | 67 | 77 | +10 |
| `iwork/urls.py` | 57 | 63 | +6 |
| `iwork/settings.py` | 222 | 226 | +4 |

### 新增功能

- 产量看板统计汇总 API (`GET /api/kanban/stats/`)
- 产量看板排行榜 API (`GET /api/kanban/ranking/`)
- 产量看板级联筛选 API (`GET /api/kanban/filter-options/`)
- 产量看板页面 (`/kanban/`)
- 挂衣线开关 (`show_all_flows` 参数)
- 排行榜多款号合并修复
- 看板级联筛选修复

### 构建配置

- Dockerfile: `D:\DM\iwork\Dockerfile`
- docker-compose: `D:\DM\iwork\docker-compose.yml`
- 容器名: `DKT_iwork`
- 网络: `docker_dkt-net`
- 依赖: `requirements.txt` (新增 openpyxl 等)

## 更新步骤

```powershell
# 构建并重建 iwork 容器
docker compose -f D:\DM\iwork\docker-compose.yml -p dkt-iwork up -d --build

# 验证
docker ps --filter name=DKT_iwork
```

## 其他容器状态

| 容器 | 状态 | 备注 |
|------|------|------|
| DKT_kc_nginx | 已同步 | Nginx 配置无差异 |
| DKT_kc_portal | 待检查 | 独立 Django 项目 |
| DKT_fabric | 待检查 | — |
| DKT_pattern | 待检查 | — |
| DKT_dsm | 待检查 | — |
