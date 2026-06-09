# Django 双数据库配置实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 配置 Django 双数据库连接，实现系统权限库与业务只读库分离

**Architecture:** 使用 django-environ 管理环境变量，数据库路由器自动分发读写操作，access 库处理 Django 系统表，iwork 库只读访问业务数据

**Tech Stack:** Django 5.2, django-environ, mysqlclient, MySQL

---

## 文件结构

```
D:\DM\Python代码\Seamus\iwork\
├── requirements.txt              # 新建 - 依赖包
├── iwork/
│   ├── .env.example              # 新建 - 环境变量模板
│   ├── .env                      # 新建 - 环境变量（用户填写）
│   ├── database_router.py        # 新建 - 数据库路由器
│   └── settings.py               # 修改 - 数据库配置
└── tests/
    └── test_database_router.py   # 新建 - 路由器测试
```

---

### Task 1: 创建 requirements.txt

**Files:**
- Create: `D:\DM\Python代码\Seamus\iwork\requirements.txt`

- [ ] **Step 1: 创建 requirements.txt 文件**

```python
# Django 核心
Django>=5.2

# 环境变量管理
django-environ>=0.11.2

# MySQL 驱动
mysqlclient>=2.2.0

# 数据处理
pandas>=2.0.0
numpy>=1.24.0
openpyxl>=3.1.0

# 日志管理
loguru>=0.7.0
```

- [ ] **Step 2: 验证文件创建**

Run: `type requirements.txt`
Expected: 显示上述内容

- [ ] **Step 3: 提交**

```bash
git add requirements.txt
git commit -m "[2026-04-21][CHORE] 添加项目依赖包清单"
```

---

### Task 2: 创建 .env.example 模板

**Files:**
- Create: `D:\DM\Python代码\Seamus\iwork\iwork\.env.example`

- [ ] **Step 1: 创建 .env.example 文件**

```
# Django 配置
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Django 系统权限数据库（读写）
ACCESS_DB_HOST=localhost
ACCESS_DB_PORT=3306
ACCESS_DB_NAME=iwork_system
ACCESS_DB_USER=iwork_admin
ACCESS_DB_PASSWORD=your-password-here

# 业务数据库（只读，外部服务器）
IWORK_DB_HOST=192.168.3.15
IWORK_DB_PORT=3306
IWORK_DB_NAME=payroll
IWORK_DB_USER=iwork_readonly
IWORK_DB_PASSWORD=your-password-here
```

- [ ] **Step 2: 验证文件创建**

Run: `type iwork\.env.example`
Expected: 显示上述内容

- [ ] **Step 3: 提交**

```bash
git add iwork/.env.example
git commit -m "[2026-04-21][DOCS] 添加环境变量配置模板"
```

---

### Task 3: 创建数据库路由器

**Files:**
- Create: `D:\DM\Python代码\Seamus\iwork\iwork\database_router.py`
- Create: `D:\DM\Python代码\Seamus\iwork\tests\test_database_router.py`

- [ ] **Step 1: 创建测试目录**

Run: `mkdir tests`

- [ ] **Step 2: 编写路由器测试**

```python
# tests/test_database_router.py
import pytest
from unittest.mock import Mock
from iwork.database_router import DatabaseRouter


class TestDatabaseRouter:
    """数据库路由器测试"""

    def setup_method(self):
        self.router = DatabaseRouter()

    def test_db_for_read_iwork_app_returns_iwork(self):
        """测试 iwork app 读取操作返回 iwork 数据库"""
        model = Mock()
        model._meta.app_label = 'iwork'
        result = self.router.db_for_read(model)
        assert result == 'iwork'

    def test_db_for_read_other_app_returns_access(self):
        """测试其他 app 读取操作返回 access 数据库"""
        model = Mock()
        model._meta.app_label = 'auth'
        result = self.router.db_for_read(model)
        assert result == 'access'

    def test_db_for_write_iwork_app_returns_none(self):
        """测试 iwork app 写入操作被拒绝"""
        model = Mock()
        model._meta.app_label = 'iwork'
        result = self.router.db_for_write(model)
        assert result is None

    def test_db_for_write_other_app_returns_access(self):
        """测试其他 app 写入操作返回 access 数据库"""
        model = Mock()
        model._meta.app_label = 'auth'
        result = self.router.db_for_write(model)
        assert result == 'access'

    def test_allow_relation_same_db_returns_true(self):
        """测试同一数据库的关联查询允许"""
        obj1 = Mock()
        obj1._state.db = 'access'
        obj2 = Mock()
        obj2._state.db = 'access'
        result = self.router.allow_relation(obj1, obj2)
        assert result is True

    def test_allow_relation_different_db_returns_false(self):
        """测试不同数据库的关联查询禁止"""
        obj1 = Mock()
        obj1._state.db = 'access'
        obj2 = Mock()
        obj2._state.db = 'iwork'
        result = self.router.allow_relation(obj1, obj2)
        assert result is False

    def test_allow_migrate_iwork_app_returns_false(self):
        """测试 iwork app 禁止迁移"""
        result = self.router.allow_migrate('iwork', 'iwork')
        assert result is False

    def test_allow_migrate_other_app_returns_true_for_access(self):
        """测试其他 app 迁移到 access"""
        result = self.router.allow_migrate('access', 'auth')
        assert result is True
```

- [ ] **Step 3: 编写数据库路由器实现**

```python
# iwork/database_router.py
class DatabaseRouter:
    """
    数据库路由器：
    - access: Django 系统权限库（读写）
    - iwork: 业务生产数据库（只读）
    """

    iwork_app_labels = ['iwork']

    def db_for_read(self, model, **hints):
        """指定模型的读取数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            return 'iwork'
        return 'access'

    def db_for_write(self, model, **hints):
        """指定模型的写入数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            return None
        return 'access'

    def allow_relation(self, obj1, obj2, **hints):
        """判断两个对象是否允许关联"""
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None

    def allow_migrate(self, db, app_label, model_name=None):
        """判断是否允许迁移"""
        if app_label in self.iwork_app_labels:
            return False
        return db == 'access'
```

- [ ] **Step 4: 运行测试验证**

Run: `pytest tests/test_database_router.py -v`
Expected: 8 tests passed

- [ ] **Step 5: 提交**

```bash
git add tests/ iwork/database_router.py
git commit -m "[2026-04-21][FEAT] 添加数据库路由器及测试"
```

---

### Task 4: 修改 settings.py

**Files:**
- Modify: `D:\DM\Python代码\Seamus\iwork\iwork\settings.py`

- [ ] **Step 1: 修改 settings.py 文件头部导入**

将原文件第 13-16 行替换为：

```python
from pathlib import Path
import environ

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')
```

- [ ] **Step 2: 修改 SECRET_KEY、DEBUG、ALLOWED_HOSTS 配置**

将原文件第 22-28 行替换为：

```python
SECRET_KEY = env('DJANGO_SECRET_KEY')

DEBUG = env.bool('DJANGO_DEBUG', default=False)

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
```

- [ ] **Step 3: 替换 DATABASES 配置**

将原文件第 75-80 行替换为：

```python
DATABASES = {
    'access': {
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

DATABASE_ROUTERS = ['iwork.database_router.DatabaseRouter']
```

- [ ] **Step 4: 验证配置语法**

Run: `python -c "from iwork import settings; print('配置加载成功')"`
Expected: 无报错，输出"配置加载成功"

注意：此时需要 .env 文件存在，可先用 .env.example 复制测试

- [ ] **Step 5: 提交**

```bash
git add iwork/settings.py
git commit -m "[2026-04-21][FEAT] 配置双数据库连接和环境变量"
```

---

### Task 5: 创建 .env 文件并验证

**Files:**
- Create: `D:\DM\Python代码\Seamus\iwork\iwork\.env`

- [ ] **Step 1: 复制模板创建 .env**

Run: `copy iwork\.env.example iwork\.env`

- [ ] **Step 2: 提示用户填写实际值**

用户需手动编辑 `iwork\.env`，填写：
- DJANGO_SECRET_KEY: Django 密钥
- ACCESS_DB_PASSWORD: 本地数据库密码
- IWORK_DB_PASSWORD: 业务数据库密码

- [ ] **Step 3: 验证 Django 配置**

Run: `python manage.py check --deploy`
Expected: 无严重错误警告

注意：此步骤需要数据库实际连接，用户需确保数据库已创建

---

### Task 6: 配置 MySQL 只读用户（用户手动操作）

**Files:**
- 无文件变更，MySQL 服务器端操作

- [ ] **Step 1: 创建只读用户**

在 MySQL 服务器 192.168.3.15 上执行：

```sql
CREATE USER 'iwork_readonly'@'%' IDENTIFIED BY 'your-password';
GRANT SELECT ON payroll.* TO 'iwork_readonly'@'%';
FLUSH PRIVILEGES;
```

- [ ] **Step 2: 验证只读权限**

```sql
SHOW GRANTS FOR 'iwork_readonly'@'%';
```

Expected: 仅显示 SELECT 权限

---

## 自检清单

### 规格覆盖

| 规格要求 | 任务覆盖 |
|---------|---------|
| 创建 .env.example | Task 2 |
| 创建 .env | Task 5 |
| 创建 database_router.py | Task 3 |
| 修改 settings.py | Task 4 |
| 创建 requirements.txt | Task 1 |
| MySQL 只读用户 | Task 6 |

### 无占位符

- 所有代码块包含完整实现
- 所有命令包含具体路径
- 无 TBD、TODO 等占位符

### 类型一致性

- DatabaseRouter 类在 Task 3 定义，settings.py 中引用路径一致
- 环境变量命名：ACCESS_DB_* 和 IWORK_DB_* 在所有文件中一致