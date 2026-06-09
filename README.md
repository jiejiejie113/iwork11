# iwork - 生产看板系统

基于 Django 5.2 的生产流水线实时看板系统，支持多数据库连接和实时数据展示。

## 功能特性

- 🔌 **双数据库架构**: Django 系统库 + 业务生产库分离
- 🔒 **只读安全**: 业务数据库只读访问，防止误操作
- 📊 **实时看板**: WebSocket 实时推送生产数据
- 🔄 **数据核对**: 生产流水线打卡记录核对功能
- ⏰ **定时任务**: Celery Beat 定时同步统计数据

## 技术栈

- Python 3.14
- Django 5.2
- Django Channels (WebSocket)
- Celery + Celery Beat (定时任务)
- Daphne (ASGI 服务器)
- Redis (消息队列/缓存)
- MySQL 8.0+
- django-environ（环境变量管理）

## 项目结构

```
iwork/
├── docs/                          # 文档目录
│   └── superpowers/
│       ├── specs/                 # 设计文档
│       └── plans/                 # 实施计划
├── iwork/                         # Django 项目配置
│   ├── .env                       # 环境变量（需创建）
│   ├── .env.example               # 环境变量模板
│   ├── database_router.py         # 数据库路由器
│   ├── settings.py                # Django 配置
│   ├── urls.py                    # URL 路由
│   ├── asgi.py                    # ASGI 配置
│   ├── celery.py                  # Celery 配置
│   └── routing.py                 # WebSocket 路由
├── src/                           # 源代码
│   └── reconcile_data/            # 数据核对模块
├── templates/
│   └── iwork/
│       └── dashboard.html         # 看板页面模板
├── tests/                         # 测试目录
│   ├── test_api_views.py          # API 测试
│   ├── test_consumers.py          # WebSocket 测试
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

#### 4. 启动 Daphne（ASGI 服务器）

```bash
daphne -b 0.0.0.0 -p 8000 iwork.asgi:application
```

### 访问看板

- **看板地址**: http://localhost:8000/dashboard/
- **WebSocket 端点**: ws://localhost:8000/ws/dashboard/

### API 接口

| 接口                      | 方法 | 说明         |
| ------------------------- | ---- | ------------ |
| `/api/stats/realtime/`  | GET  | 实时统计数据 |
| `/api/stats/hourly/`    | GET  | 小时统计     |
| `/api/stats/flow/`      | GET  | 流水线效率   |
| `/api/workorders/`      | GET  | 工单列表     |
| `/api/workorders/{id}/` | GET  | 工单详情     |

### 定时任务

Celery Beat 配置：

| 任务名                             | 间隔 | 说明             |
| ---------------------------------- | ---- | ---------------- |
| `sync-dashboard-stats-every-60s` | 60秒 | 同步看板统计数据 |

### 一键启动脚本（PowerShell）

创建 `start_dashboard.ps1`：

```powershell
# 启动 Redis
Start-Process redis-server

# 启动 Celery Worker
Start-Process powershell -ArgumentList "-NoExit", "-Command", "celery -A iwork worker -l info -P eventlet"

# 启动 Celery Beat
Start-Process powershell -ArgumentList "-NoExit", "-Command", "celery -A iwork beat -l info"

# 启动 Daphne
daphne -b 0.0.0.0 -p 8000 iwork.asgi:application
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
- [X] 实现 WebSocket 实时推送
- [X] 创建生产看板前端页面
- [ ] 添加用户权限分组（按流水线/班组）
- [ ] 添加看板数据导出功能
- [ ] 实现历史数据查询

## 文档

- [数据库配置设计文档](docs/superpowers/specs/2026-04-21-database-config-design.md)
- [数据库配置实施计划](docs/superpowers/plans/2026-04-21-database-config.md)

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
