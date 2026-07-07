# production_orders 生产工单数据表

## 概述

将 SQLite 中的生产工单数据导入 MySQL `iwork_local` 库，通过 Django ORM 统一管理。

## 数据源

**SQLite 文件：** `iwork/sqlite/production_orders.db`

| 属性 | 值 |
|------|-----|
| 源表名 | `orders` |
| 记录数 | 29,043 |
| 唯一工单号 | 28,677 |
| 唯一款号 | 28,845 |

**源表字段：**

| 原字段 | 类型 | 说明 |
|--------|------|------|
| `order` | TEXT | 工单号（可重复，同一工单可关联多个部门） |
| `order/dept` | TEXT | 工单/部门 |
| `Style No` | TEXT | 款号 |
| `Product Name` | TEXT | 产品名称 |
| `款式` | TEXT | 款式描述 |

## 目标 MySQL 表

**数据库：** `iwork_local`  
**表名：** `production_orders`  
**引擎：** InnoDB  
**字符集：** utf8mb4

### 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INT AUTO_INCREMENT | 主键 |
| `order_no` | VARCHAR(50) NOT NULL | 工单号 |
| `order_dept` | VARCHAR(50) DEFAULT '' | 工单/部门 |
| `style_no` | VARCHAR(50) DEFAULT '' | 款号 |
| `product_name` | VARCHAR(200) DEFAULT '' | 产品名称 |
| `style_desc` | VARCHAR(200) DEFAULT '' | 款式描述 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

### 索引

| 索引名 | 类型 | 字段 |
|--------|------|------|
| `idx_po_unique_record` | UNIQUE | (order_no, order_dept, style_no, product_name, style_desc) |
| `idx_po_order_no` | INDEX | order_no |
| `idx_po_style_no` | INDEX | style_no |
| `idx_po_order_dept` | INDEX | order_dept |

## Django 模型

```python
from iwork.local_models import ProductionOrder

# 查询示例
orders = ProductionOrder.objects.filter(order_no='689771/3931')
styles = ProductionOrder.objects.filter(style_no='CU3988')
```

模型定义：`iwork/local_models.py:67` → `class ProductionOrder`
数据库路由：`iwork/database_router.py:11` → `local_models` 集合

## 数据导入

### 首次导入

```bash
# 在 Docker 容器内执行
docker exec DKT_iwork python manage.py import_production_orders
```

### 重新导入（数据更新后）

```bash
# 幂等操作，重复数据自动跳过
docker exec DKT_iwork python manage.py import_production_orders
```

如果源 SQLite 文件有更新，先将新文件复制到容器：

```bash
docker cp iwork/sqlite/production_orders.db DKT_iwork:/app/sqlite/production_orders.db
docker exec DKT_iwork python manage.py import_production_orders
```

### 导入命令说明

- **命令：** `python manage.py import_production_orders`
- **位置：** `iwork/management/commands/import_production_orders.py`
- **批处理大小：** 1000 条/批
- **幂等性：** 重复执行不会产生重复数据（`ignore_conflicts=True`）
- **进度显示：** 每 5000 条输出一次进度

## 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `iwork/local_models.py` | 新增 `ProductionOrder` 模型 |
| `iwork/database_router.py` | `local_models` 添加 `'productionorder'` |
| `iwork/management/commands/import_production_orders.py` | 新建导入命令 |
| `iwork/migrations/0003_productionorder.py` | 自动生成的迁移文件 |
