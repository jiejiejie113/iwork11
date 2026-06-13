# iwork - 生产看板系统

基于 Django 5.2 的生产流水线实时看板系统，支持双数据库架构、SSE 实时推送和历史数据回溯。

## 功能特性

- 🔌 **双数据库架构**: Django 系统库 + 业务生产库分离
- 🔒 **只读安全**: 业务数据库只读访问，防止误操作
- 📊 **实时看板**: SSE 实时推送生产数据，每60秒自动刷新
- 🔄 **数据核对**: 生产流水线打卡记录核对功能
- 🎯 **目标管理**: 员工日产量目标设定与达标追踪
- ⏰ **定时任务**: Celery Beat 定时同步统计数据到 Redis 缓存

## 技术栈

- Python 3.11.6
- Django 5.2
- Uvicorn (ASGI 服务器，SSE 推送)
- Celery + Celery Beat (定时任务)
- Redis (缓存层，SSE 数据源)
- MySQL 8.0+
- django-environ（环境变量管理）
- Django REST Framework (API)

## 项目结构

```
iwork/
├── docs/                          # 文档目录
│   ├── 开发文档/                   # 开发规范与 API 文档
│   └── 部署文档/                   # 部署运维文档
├── iwork/                         # Django 项目配置
│   ├── .env                       # 环境变量（需创建）
│   ├── .env.example               # 环境变量模板
│   ├── database_router.py         # 数据库路由器
│   ├── settings.py                # Django 配置
│   ├── urls.py                    # URL 路由
│   ├── history_urls.py            # 历史数据路由
│   ├── asgi.py                    # ASGI 配置
│   ├── celery.py                  # Celery 配置
│   ├── api_views.py               # REST API 视图
│   ├── queries.py                 # 业务查询（远程库）
│   ├── local_queries.py           # 业务查询（本地库）
│   ├── statistics.py              # 数据聚合统计
│   └── forms.py                   # 表单定义
├── templates/
│   └── iwork/
│       ├── dashboard.html         # 实时/历史看板页面
│       ├── production_detail.html # 生产详情页面
│       └── _header.html           # 共用导航栏
├── tests/                         # 测试目录
│   ├── test_api_views.py          # API 测试
│   ├── test_database_router.py    # 路由器测试
│   ├── test_models.py             # 模型测试
│   ├── test_statistics.py         # 统计测试
│   ├── test_tasks.py              # Celery 任务测试
│   └── __init__.py
├── manage.py                      # Django 管理脚本
├── requirements.txt               # 依赖包清单
└── README.md                      # 项目说明
```

## 数据库架构

| 数据库别名  | 用途          | 位置         | 权限 |
| ----------- | ------------- | ------------ | ---- |
| `default` | Django 系统库 | localhost    | 读写 |
| `iwork`   | 业务生产库    | 192.168.3.15 | 只读 |

### 业务数据表

- 数据库: `payroll`
- 核心表: `pytckreg3` (生产流水线打卡记录)

#### 字段说明

| 字段        | 类型        | 说明                                                                       |
| ----------- | ----------- | -------------------------------------------------------------------------- |
| TicketNo    | VARCHAR(13) | 票号（主键）                                                               |
| SeqNo       | INT         | 序号                                                                       |
| WrkOrder    | VARCHAR(14) | 工单号                                                                     |
| BundleNo    | INT         | 扎号                                                                       |
| StepNo      | INT         | 工序号                                                                     |
| Qty         | INT         | 数量                                                                       |
| RegPerSysID | INT         | 登记人系统ID                                                               |
| RegDate     | DATETIME    | **登记日期**（格式: `21/4/2026 00:00:00`，时间部分为 00:00:00）    |
| RegTime     | DATETIME    | **登记时间**（格式: `30/12/1899 16:25:53`，日期部分为 1899-12-30） |
| RFID        | VARCHAR(10) | RFID                                                                       |
| Flow        | VARCHAR(40) | 流程                                                                       |
| PO          | VARCHAR(40) | PO号                                                                       |
| TimeCost    | INT         | 耗时                                                                       |
| SysSource   | VARCHAR(3)  | 系统来源                                                                   |
| AccBundleNo | INT         | 累计扎号                                                                   |
| MtrType     | VARCHAR(14) | 物料类型                                                                   |
| Color       | VARCHAR(35) | 颜色                                                                       |
| Sizx        | VARCHAR(16) | 尺码                                                                       |
| SerialNum   | VARCHAR(10) | 序列号                                                                     |
| StationID   | VARCHAR(3)  | 工位ID                                                                     |

> **注意**: `RegDate` 和 `RegTime` 是分离存储的日期和时间字段。`RegDate` 只包含日期，`RegTime` 只包含时间。完整时间戳需要组合这两个字段。

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/GuChenkano/iwork.git
cd iwork
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 复制模板
copy iwork\.env.example iwork\.env

# 编辑 .env 文件，填写实际密码
```

`.env` 文件需要配置：

```
# Django 配置
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Django 系统权限数据库（读写）
ACCESS_DB_HOST=localhost
ACCESS_DB_PORT=3306
ACCESS_DB_NAME=iwork_system
ACCESS_DB_USER=iwork_admin
ACCESS_DB_PASSWORD=your-password

# 业务数据库（只读）
IWORK_DB_HOST=192.168.3.15
IWORK_DB_PORT=3306
IWORK_DB_NAME=payroll
IWORK_DB_USER=data
IWORK_DB_PASSWORD=your-password
```

### 4. 创建本地数据库

```sql
CREATE DATABASE iwork_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'iwork_admin'@'localhost' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON iwork_system.* TO 'iwork_admin'@'localhost';
FLUSH PRIVILEGES;
```

### 5. 执行迁移

```bash
python manage.py migrate
```

### 6. 运行开发服务器

```bash
python manage.py runserver
```

访问 http://localhost:8000

## 生产看板启动指南

### 前置条件

1. **安装 Redis**（Windows 可使用 Memurai 或 WSL）

   ```bash
   # WSL Ubuntu
   sudo apt install redis-server
   sudo service redis-server start

   # 或使用 Memurai (Windows)
   # https://www.memurai.com/
   ```
2. **确认 Redis 运行**

   ```bash
   redis-cli ping
   # 应返回 PONG
   ```

### 启动顺序

**必须按以下顺序启动所有服务：**

#### 1. 启动 Redis

```bash
redis-server
# 或 Windows 服务模式
net start redis
```

#### 2. 启动 Celery Worker（消费者）

```bash
celery -A iwork worker -l info -P eventlet
# 或使用 gevent
celery -A iwork worker -l info -P gevent
```

#### 3. 启动 Celery Beat（定时调度）

```bash
celery -A iwork beat -l info
```

#### 4. 启动 Uvicorn（ASGI 服务器，含 SSE 推送）

```bash
uvicorn iwork.asgi:application --host 0.0.0.0 --port 8000
```

### 访问看板

- **看板地址**: http://localhost:8000/
- **历史看板**: http://localhost:8000/history/
- **生产详情**: http://localhost:8000/production/detail-data/
- **SSE 推送端点**: http://localhost:8000/api/dashboard/stream/

### API 接口

| 接口 | 方法 | 说明 |
| ---- | ---- | ---- |
| `/api/dashboard/realtime/` | GET | 实时统计数据 |
| `/api/dashboard/hourly/` | GET | 每小时产量趋势 |
| `/api/dashboard/processes/` | GET | 可用工序列表 |
| `/api/dashboard/flow/<flow>/` | GET | 指定 Flow 汇总 |
| `/api/dashboard/workorders/` | GET | 工单分页列表 |
| `/api/dashboard/stream/` | GET | SSE 实时推送 |
| `/api/dashboard/set-targets/` | POST | 设定员工日目标 |
| `/api/dashboard/monthly-trend/` | GET | 月产量趋势 |
| `/api/dashboard/process-compare/` | GET | 工序产量对比 |
| `/api/dashboard/heatmap/` | GET | 时段热力图 |
| `/api/dashboard/station-ranking/` | GET | 工站产量排行 |
| `/api/dashboard/detail/flows/` | GET | 生产线概览 |
| `/api/dashboard/detail/flow/<flow>/` | GET | 生产线员工明细 |
| `/api/dashboard/detail/stepno/<stepno>/` | GET | 工序员工明细 |
| `/api/history/date/<date>/` | GET | 历史日期数据 |
| `/api/history/sync/<date>/` | POST | 远程数据同步 |

### 定时任务

Celery Beat 配置：

| 任务名 | 间隔 | 说明 |
| ------ | ---- | ---- |
| `sync-dashboard-stats-every-60s` | 60秒 | 同步看板统计数据到 Redis 缓存（SSE 数据源） |
| `sync-production-detail-stats-every-60s` | 60秒 | 同步生产详情统计数据到 Redis 缓存 |

### 一键启动脚本（PowerShell）

创建 `start_dashboard.ps1`：

```powershell
# 启动 Redis
Start-Process redis-server

# 启动 Celery Worker
Start-Process powershell -ArgumentList "-NoExit", "-Command", "celery -A iwork worker -l info -P eventlet"

# 启动 Celery Beat
Start-Process powershell -ArgumentList "-NoExit", "-Command", "celery -A iwork beat -l info"

# 启动 Uvicorn（ASGI + SSE 推送）
uvicorn iwork.asgi:application --host 0.0.0.0 --port 8000
```

## 数据库路由器

项目使用数据库路由器自动分发数据库操作：

- **iwork app** 的模型 → `iwork` 数据库（只读）
- **其他 app** 的模型 → `default` 数据库（读写）

### 使用示例

```python
# 在 iwork app 中定义业务模型
class ProductionRecord(models.Model):
    # 自动路由到 iwork 数据库
    employee_id = models.CharField(max_length=50)
    timestamp = models.DateTimeField()
    quantity = models.IntegerField()
  
    class Meta:
        app_label = 'iwork'
        db_table = 'pytckreg3'
```

## 测试

```bash
pytest tests/ -v
```

## 安全特性

1. **环境变量隔离**: `.env` 文件不提交到 Git
2. **只读权限**: 业务数据库通过路由器 + MySQL 用户权限双重保护
3. **密钥管理**: Django SECRET_KEY 从环境变量读取

## 数据导出脚本

### pytckreg3 数据导出

导出 `pytckreg3` 表数据到 CSV 文件：

```powershell
# 默认导出今日数据
python scripts/export_pytckreg3.py

# 指定日期
python scripts/export_pytckreg3.py --date 2026-04-21

# 指定日期和输出路径
python scripts/export_pytckreg3.py --date 2026-04-21 --output D:\data.csv
```

**参数说明**：

| 参数         | 说明                       | 默认值                                   |
| ------------ | -------------------------- | ---------------------------------------- |
| `--date`   | 导出日期，格式: YYYY-MM-DD | 今日                                     |
| `--output` | 输出文件路径               | C:\Users\lipengfei\Desktop\pytckreg3.csv |

## 后续开发计划

- [X] 创建 iwork app 业务模型
- [X] 实现 Redis 缓存层
- [X] 实现 SSE 实时推送（WebSocket → SSE 迁移完成）
- [X] 创建生产看板前端页面
- [X] 实现历史数据查询
- [X] 实现生产详情模块（生产线/工序概览 → 员工明细）
- [X] 实现目标产量管理与效率追踪
- [ ] 添加用户权限分组（按流水线/班组）
- [ ] 添加看板数据导出功能

## 文档

- [开发规范手册](docs/开发文档/iwork规范手册.md)
- [API 接口文档](docs/开发文档/API接口文档.md)
- [API 接口清单](docs/部署文档/API接口清单.md)
- [Docker 部署指南](docs/部署文档/docker-deployment.md)
- [SSE 迁移数据流设计](docs/开发文档/SSE迁移数据流设计.md)

## 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m '[FEAT] 添加某功能'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 提交规范

```
[YYYY-MM-DD][TYPE] 描述

TYPE:
- [FEAT] 新功能
- [FIX] 修复
- [DOCS] 文档更新
- [REFACTOR] 重构
- [TEST] 测试
- [CHORE] 构建/工具变更
```

## 许可证

MIT License

## 作者

GuChenkano
