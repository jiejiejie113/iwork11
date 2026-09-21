# Django 生产环境迁移设计方案

> 日期：2026-05-29
> 状态：已确认
> 目标：将 iwork Django 项目从开发环境迁移至 Windows Server 生产环境

---

## 一、需求摘要

| 维度 | 决定 |
|------|------|
| 目标环境 | Windows Server |
| 中间件 | Docker Desktop（Redis + MySQL） |
| 远程业务库 | 可直连 `192.168.3.15`（同内网） |
| 本地业务库 | 仅迁移表结构，数据由 Celery 定时同步 |
| Django 系统库 | 结构 + 数据完整迁移 |
| 反向代理 | Nginx 已存在，独立提供配置文件 |
| 日志监控 | 保持 Loguru 文件日志方案 |
| 部署方式 | PowerShell 脚本化部署（NSSM 注册服务） |

---

## 二、架构拓扑

```
                    ┌─────────────────────────────────────────────┐
                    │           Windows Server (目标服务器)          │
                    │                                              │
  Internet ────►   │  ┌──────┐     ┌───────────────────────────┐  │
                    │  │Nginx │────►│  Daphne :8000 (ASGI)      │  │
                    │  │:80   │     │  ├─ HTTP: Django views    │  │
                    │  │:443  │     │  └─ WS: Channels consumer │  │
                    │  └──────┘     └───────────┬───────────────┘  │
                    │                           │                   │
                    │              ┌────────────┼────────────┐     │
                    │              │            │            │     │
                    │         ┌────▼───┐  ┌────▼───┐  ┌────▼───┐ │
                    │         │ Celery │  │ Celery │  │ 日志文件 │ │
                    │         │ Worker │  │  Beat  │  │ /logs   │ │
                    │         └───┬────┘  └────────┘  └────────┘ │
                    │             │                                │
                    │    ┌────────┼────────────────────┐          │
                    │    │        │     Docker Desktop  │          │
                    │    │  ┌─────▼──┐ ┌─────────────┐ │          │
                    │    │  │ Redis  │ │   MySQL      │ │          │
                    │    │  │ :6379  │ │   :3306      │ │          │
                    │    │  └────────┘ └──────┬───────┘ │          │
                    │    └────────────────────┼─────────┘          │
                    │                        │                     │
                    └────────────────────────┼─────────────────────┘
                                             │
                                    ┌────────▼────────┐
                                    │ 192.168.3.15:3306│
                                    │ 远程业务库 (只读) │
                                    │ payroll.pytckreg3│
                                    └──────────────────┘
```

### 组件说明

| 组件 | 进程 | 端口 | 说明 |
|------|------|------|------|
| Nginx | 系统服务 | 80/443 | 反向代理 + 静态文件 + SSL |
| Daphne | iwork-daphne | 8000 | ASGI 服务器（HTTP + WebSocket） |
| Celery Worker | iwork-celery-worker | - | 异步任务执行 |
| Celery Beat | iwork-celery-beat | - | 定时任务调度（每 60s） |
| Redis | Docker 容器 | 6379 (127.0.0.1) | 缓存 + Channels 层 + Celery Broker |
| MySQL | Docker 容器 | 3306 (127.0.0.1) | Django 系统库 + 本地业务同步库 |

---

## 三、数据库迁移策略

### 数据库清单

| 别名 | 库名 | 权限 | 迁移内容 | 方式 |
|------|------|------|---------|------|
| `default` | iwork_system | RW | 结构 + 全量数据 | mysqldump → 导入 |
| `iwork` | payroll | RO (远程) | 不迁移 | 网络直连 |
| `iwork_local` | iwork_local | RW | 仅表结构 | SQL 建表脚本 |

### 迁移步骤

```powershell
# === 旧服务器操作 ===
# 导出系统库
mysqldump -h localhost -u root -p \
  --routines --triggers --single-transaction \
  --default-character-set=utf8mb4 \
  iwork_system > system_db_dump.sql

# === 新服务器操作 ===
# 1. Docker MySQL 启动后导入
docker exec -i mysql-iwork mysql -u root -p${MYSQL_ROOT_PASSWORD} iwork_system < system_db_dump.sql

# 2. 确保 migrations 已应用
python manage.py migrate --database=default

# 3. 创建本地业务库表结构
python scripts/create_local_db.py
```

### 数据同步机制

- Celery Beat 每 60s 触发 `sync_dashboard_stats` 任务
- 任务从远程库（192.168.3.15）读取数据，构建统计指标
- 统计结果缓存到 Redis，同时推送到 WebSocket
- 历史数据通过 `/api/history/sync/<date>/` 手动触发同步到 `iwork_local`

---

## 四、文件部署

### 迁移文件清单

| 类别 | 路径 | 说明 |
|------|------|------|
| Django 项目 | `iwork/` (整个目录) | Python 代码、模板、URL 配置 |
| 入口脚本 | `manage.py` | Django CLI |
| 依赖清单 | `requirements.txt` | pip 依赖 |
| 测试代码 | `tests/` | 16 个测试文件 |
| 工具脚本 | `scripts/` | 辅助脚本 |
| 文档 | `docs/` | 开发文档 |
| 部署配置 | `docker-compose.yml` (新建) | Docker 容器编排 |
| 部署配置 | `mysql-init/01-create-databases.sql` (新建) | 数据库初始化 |
| 部署脚本 | `deploy.ps1` (新建) | 一键部署/升级 |
| 部署脚本 | `stop_services.ps1` (新建) | 停止服务 |
| 部署脚本 | `restart_services.ps1` (新建) | 重启服务 |
| 部署脚本 | `uninstall_services.ps1` (新建) | 卸载服务 |
| Nginx 配置 | `iwork.conf` (新建) | 反向代理配置模板 |

### 排除文件

| 路径 | 原因 |
|------|------|
| `.venv/` | 服务器重建 |
| `__pycache__/` | 自动生成 |
| `.env` | 不要提交，服务器手动创建 |
| `logs/` | 运行时生成 |
| `celerybeat-schedule.*` | 运行时文件 |
| `.claude/`, `.superpowers/` | IDE 辅助 |

---

## 五、Docker Compose 配置

### docker-compose.yml

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: redis-iwork
    restart: unless-stopped
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  mysql:
    image: mysql:8.0
    container_name: mysql-iwork
    restart: unless-stopped
    ports:
      - "127.0.0.1:3306:3306"
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}  # 需在项目根目录创建 .env 文件声明此变量
    volumes:
      - mysql_data:/var/lib/mysql
      - ./mysql-init:/docker-entrypoint-initdb.d
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci

volumes:
  redis_data:
  mysql_data:
```

### mysql-init/01-create-databases.sql

```sql
CREATE DATABASE IF NOT EXISTS iwork_system
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS iwork_local
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'iwork_admin'@'%'
  IDENTIFIED BY '<更换为应用数据库密码>';

GRANT ALL PRIVILEGES ON iwork_system.* TO 'iwork_admin'@'%';
GRANT ALL PRIVILEGES ON iwork_local.* TO 'iwork_admin'@'%';
FLUSH PRIVILEGES;
```

---

## 六、服务管理

### Windows 服务注册（NSSM）

| 服务名 | 可执行文件 | 参数 | 崩溃策略 |
|--------|-----------|------|---------|
| `iwork-daphne` | `.venv\Scripts\daphne.exe` | `-b 0.0.0.0 -p 8000 iwork.asgi:application` | 自动启动 |
| `iwork-celery-worker` | `.venv\Scripts\celery.exe` | `-A iwork worker -l info -P solo` | 自动重启 |
| `iwork-celery-beat` | `.venv\Scripts\celery.exe` | `-A iwork beat -l info` | 自动重启 |

### 运维命令

```powershell
# 状态查看
.\deploy.ps1 -Status

# 首次完整部署
.\deploy.ps1

# 升级更新
.\deploy.ps1 -Upgrade

# 仅重注册服务
.\deploy.ps1 -ServiceOnly

# 停止/重启/卸载
.\stop_services.ps1
.\restart_services.ps1
.\uninstall_services.ps1
```

---

## 七、Nginx 配置

### 接口路由规则

所有 `/` 请求通过 Nginx 反向代理到 `127.0.0.1:8000`（Daphne），配置要点：

1. `/static/` → Nginx 直接返回静态文件（`alias D:/iwork/staticfiles/`）
2. `/ws/` → WebSocket 升级转发（超时 3600s）
3. 其他所有路径 → HTTP 转发（超时 60s，禁用缓冲）

完整配置见交付物 `iwork.conf`。

---

## 八、迁移执行流程

### 前置条件

```powershell
# 1. Python 3.11
python --version

# 2. Docker Desktop 运行中
docker ps

# 3. Git
git --version

# 4. 网络连通
ping 192.168.3.15
telnet 192.168.3.15 3306

# 5. Nginx
nginx -v
```

### 执行顺序

```
准备阶段（旧服务器）
├── [1] 导出 Django 系统库 → system_db_dump.sql
├── [2] 确认 .env 需变更项（密码/密钥）
└── [3] 备份项目目录（保险）

部署阶段（新服务器）
├── [4] 安装 Python 3.11 + Docker Desktop
├── [5] Git clone 项目代码
├── [6] 创建 .env（基于 .env.example，更新生产值）
├── [7] 创建 mysql-init/01-create-databases.sql
├── [8] docker compose up -d
├── [9] 导入系统库 → mysql < system_db_dump.sql
├── [10] 运行 deploy.ps1
├── [11] 安装 Nginx 配置
└── [12] nginx -s reload

验证阶段
├── [13] python manage.py check --deploy
├── [14] curl http://localhost/ → 200
├── [15] 逐个 API 验证
├── [16] WebSocket 连接验证
├── [17] Celery 定时任务验证
└── [18] 浏览器完整验收
```

### 验证清单

| # | 检查项 | 预期 | 命令 |
|---|--------|------|------|
| 1 | Docker 容器 | 2 个 Up | `docker compose ps` |
| 2 | Windows 服务 | 3 个 Running | `Get-Service iwork-*` |
| 3 | 系统库 | 用户可登录 /admin/ | 浏览器 |
| 4 | 远程库 | 实时数据显示 | 访问首页 |
| 5 | WebSocket | 数据自动刷新 | DevTools WS 面板 |
| 6 | Celery | 每 60s 日志输出 | 查看 logs/ |
| 7 | 本地同步 | pytckreg3 有数据 | SQL 查询 |
| 8 | Nginx 静态 | /static/ 直接响应 | 检查 X-Served-By |

---

## 九、回滚方案

| 失败场景 | 回滚操作 | 预计停机 |
|----------|---------|---------|
| 依赖安装失败 | 修复依赖，重跑 `deploy.ps1` | 0 |
| 数据库迁移失败 | 重新导入旧 dump | ~5 min |
| 服务启动失败 | 查看日志修复 | ~3 min |
| 功能异常 | `git checkout` 上一版本 → `deploy.ps1 -Upgrade` | ~2 min |
| 完全回退 | 卸载服务 → 停 Docker → 清目录 → 重部署旧版本 | ~15 min |

### 数据保护

- MySQL volume `mysql_data` 独立于容器生命周期
- `docker compose down` 不删除数据卷
- `.env` 文件升级时不会被覆盖

---

## 十、日志运维

### 日志文件结构

```
logs/
├── all_YYYY-MM-DD.log           # 所有组件综合（7 天保留）
├── error_YYYY-MM-DD.log         # 错误日志（30 天保留）
├── daphne_stdout.log            # Daphne 控制台输出
├── daphne_stderr.log            # Daphne 错误
├── celery_worker_stdout.log     # Worker 控制台输出
├── celery_worker_stderr.log     # Worker 错误
├── celery_beat_stdout.log       # Beat 控制台输出
└── celery_beat_stderr.log       # Beat 错误
```

### 常用命令

```powershell
# 实时查看综合日志
Get-Content logs\all_$(Get-Date -Format 'yyyy-MM-dd').log -Tail 50 -Wait

# 只看错误
Get-Content logs\error_$(Get-Date -Format 'yyyy-MM-dd').log -Tail 20 -Wait

# 清理 30 天前的日志
Get-ChildItem logs\*.log | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item

# Docker 中间件日志
docker compose logs --tail=100
```

---

## 十一、交付物清单

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `docker-compose.yml` | 新建 | Redis + MySQL 编排 |
| 2 | `mysql-init/01-create-databases.sql` | 新建 | 数据库初始化 SQL |
| 3 | `deploy.ps1` | 新建 | 一键部署/升级脚本 |
| 4 | `stop_services.ps1` | 新建 | 停止所有服务 |
| 5 | `restart_services.ps1` | 新建 | 重启所有服务 |
| 6 | `uninstall_services.ps1` | 新建 | 卸载 Windows 服务 |
| 7 | `iwork.conf` | 新建 | Nginx 反向代理配置模板 |
| 8 | `docs/部署文档/PCI-API接口清单.md` | 新建 | 完整 API 接口文档 |
| 9 | `docs/部署文档/PCI-迁移操作手册.md` | 新建 | 逐步骤迁移详细手册 |
| 10 | `docs/superpowers/specs/2026-05-29-django-production-migration-design.md` | 新建 | 本设计文档 |

### 服务器上手动操作项

| # | 操作 | 说明 |
|---|------|------|
| 1 | 创建 `iwork/.env` | 从模板复制，填写生产密钥和密码 |
| 2 | 配置 Nginx | 将 `iwork.conf` 放入配置目录并 reload |
