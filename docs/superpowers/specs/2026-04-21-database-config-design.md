# Django 双数据库配置设计文档

## 概述

为 iwork Django 项目配置双数据库连接：
- `default`: Django 系统权限库（本地，读写）
- `iwork`: 业务生产数据库（远程，只读）

> **注意**: Django 硬性要求必须有一个名为 `default` 的数据库别名，因此系统权限库使用 `default` 而非 `access`。

## 背景

项目需要实时读取外部业务数据库 `payroll` 中的生产流水线打卡记录表 `pytckreg3`，用于构建生产看板功能。同时 Django 需要本地数据库管理用户权限、会话等系统数据。

## 数据库架构

| 数据库别名 | 用途 | 服务器 | 权限 |
|-----------|------|--------|------|
| default | Django 系统权限 | localhost:3306 | 读写 |
| iwork | 业务生产数据 | 192.168.3.15:3306 | 只读 |

## 环境变量设计

### `.env` 文件结构

```
# Django 配置
DJANGO_SECRET_KEY=xxx
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Django 系统权限数据库（读写）
ACCESS_DB_HOST=localhost
ACCESS_DB_PORT=3306
ACCESS_DB_NAME=iwork_system
ACCESS_DB_USER=iwork_admin
ACCESS_DB_PASSWORD=xxx

# 业务数据库（只读）
IWORK_DB_HOST=192.168.3.15
IWORK_DB_PORT=3306
IWORK_DB_NAME=payroll
IWORK_DB_USER=data
IWORK_DB_PASSWORD=xxx
```

> **命名说明**: 环境变量使用 `ACCESS_DB_*` 和 `IWORK_DB_*` 前缀，便于区分。`ACCESS_DB_*` 对应 Django 的 `default` 数据库别名。

### `.env.example` 模板

为团队成员提供配置模板，不含实际密码。

## settings.py 配置

### 数据库连接

```python
import environ

env = environ.Env()
environ.Env.read_env(BASE_DIR / 'iwork' / '.env')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('ACCESS_DB_NAME'),
        'USER': env('ACCESS_DB_USER'),
        'PASSWORD': env('ACCESS_DB_PASSWORD'),
        'HOST': env('ACCESS_DB_HOST'),
        'PORT': env.int('ACCESS_DB_PORT', default=3306),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    },
    'iwork': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('IWORK_DB_NAME'),
        'USER': env('IWORK_DB_USER'),
        'PASSWORD': env('IWORK_DB_PASSWORD'),
        'HOST': env('IWORK_DB_HOST'),
        'PORT': env.int('IWORK_DB_PORT', default=3306),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
}
```

### 路由器配置

```python
DATABASE_ROUTERS = ['iwork.database_router.DatabaseRouter']
```

### 其他配置

```python
SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env.bool('DJANGO_DEBUG', default=False)
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
```

## 数据库路由器设计

### `iwork/database_router.py`

```python
class DatabaseRouter:
    """
    数据库路由器：
    - default: Django 系统权限库（读写）
    - iwork: 业务生产数据库（只读）
    """
    
    iwork_app_labels = ['iwork']
    
    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.iwork_app_labels:
            return 'iwork'
        return 'default'
    
    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.iwork_app_labels:
            return None  # 拒绝写入 iwork 库
        return 'default'
    
    def allow_relation(self, obj1, obj2, **hints):
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.iwork_app_labels:
            return False  # iwork 库禁止迁移
        return db == 'default'
```

## 只读权限保障

两层防护机制：

1. **MySQL 用户权限**（服务器端）
   ```sql
   CREATE USER 'data'@'%' IDENTIFIED BY 'your-password';
   GRANT SELECT ON payroll.* TO 'data'@'%';
   FLUSH PRIVILEGES;
   ```

2. **数据库路由器**（应用层）
   - `db_for_write` 返回 `None` 拒绝写入操作

## 文件结构

```
iwork/
├── .env                      # 环境变量文件
├── .env.example              # 环境变量模板
├── .gitignore                # 确保 .env 在忽略列表
├── database_router.py        # 数据库路由器
├── settings.py               # 数据库配置
└── __init__.py
```

## 依赖包

```
django-environ>=0.11.2
mysqlclient>=2.2.0
pytest>=8.0.0
```

## 业务数据表

- 数据库：`payroll`
- 核心表：`pytckreg3`（生产流水线打卡记录）

## 测试覆盖

路由器测试文件 `tests/test_database_router.py` 包含 8 个测试：
- 读取操作路由测试（iwork app → iwork, 其他 app → default）
- 写入操作路由测试（iwork app → None, 其他 app → default）
- 关联查询测试（同库允许，跨库禁止）
- 迁移权限测试（iwork app 禁止迁移）

## 后续扩展

本设计为后续看板功能（Redis 缓存 + WebSocket 实时推送）预留基础架构：
- 数据库路由器可扩展支持更多业务模型
- 环境变量命名结构清晰，便于添加 Redis 配置
- 分离权限库与业务库，支持按流水线/班组分组权限查询

## 实施状态

| 步骤 | 状态 |
|------|------|
| 创建 requirements.txt | ✅ 完成 |
| 创建 .env.example | ✅ 完成 |
| 创建 database_router.py | ✅ 完成 |
| 创建路由器测试 | ✅ 完成 |
| 修改 settings.py | ✅ 完成 |
| 创建 .env 文件 | ✅ 完成 |
| 执行数据库迁移 | ✅ 完成 |
| 配置远程 MySQL 只读用户 | 待手动操作 |