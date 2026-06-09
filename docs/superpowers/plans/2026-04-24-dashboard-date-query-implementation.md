# 生产看板日期查询与本地持久化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为生产看板系统添加日期查询、视图切换和本地数据持久化功能

**Architecture:** 创建本地业务数据库，实现增量同步机制，添加前端视图切换功能，保持现有实时数据功能不变

**Tech Stack:** Django, MySQL, Redis, WebSocket, Chart.js, Tailwind CSS

---

## 文件结构

### 新建文件
- `iwork/local_models.py` - 本地业务数据模型
- `iwork/local_queries.py` - 本地数据库查询函数
- `iwork/sync.py` - 数据同步逻辑
- `iwork/api_views_local.py` - 本地数据相关API视图
- `tests/test_local_models.py` - 本地模型测试
- `tests/test_sync.py` - 同步逻辑测试
- `tests/test_api_views_local.py` - 本地API测试

### 修改文件
- `iwork/settings.py:70-94` - 添加本地数据库配置
- `iwork/database_router.py:1-34` - 更新数据库路由
- `iwork/models.py:1-60` - 添加本地模型
- `iwork/queries.py:1-136` - 添加本地查询函数
- `iwork/api_views.py:1-82` - 添加本地API视图
- `iwork/urls.py:1-24` - 添加新URL路由
- `iwork/templates/iwork/dashboard.html:1-337` - 添加前端UI
- `iwork/.env:1-18` - 添加本地数据库环境变量

---

## Task 1: 配置本地数据库环境

**Files:**
- Modify: `iwork/.env:1-18`
- Modify: `iwork/settings.py:70-94`

- [ ] **Step 1: 添加本地数据库环境变量**

在 `iwork/.env` 文件末尾添加：
```bash
# 本地业务数据库（读写）
LOCAL_DB_HOST=localhost
LOCAL_DB_PORT=3306
LOCAL_DB_NAME=iwork_local
LOCAL_DB_USER=iwork_local
LOCAL_DB_PASSWORD=Lpf12160
```

- [ ] **Step 2: 更新Django settings.py数据库配置**

在 `iwork/settings.py` 的 `DATABASES` 字典中添加 `'iwork_local'` 配置：
```python
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
    'iwork_local': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('LOCAL_DB_NAME'),
        'USER': env('LOCAL_DB_USER'),
        'PASSWORD': env('LOCAL_DB_PASSWORD'),
        'HOST': env('LOCAL_DB_HOST'),
        'PORT': env.int('LOCAL_DB_PORT', default=3306),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
}
```

- [ ] **Step 3: 验证配置**

运行以下命令验证配置：
```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 4: 提交更改**

```bash
git add iwork/.env iwork/settings.py
git commit -m "feat: 添加本地业务数据库配置"
```

---

## Task 2: 创建本地数据库和表结构

**Files:**
- Create: `scripts/create_local_db.py`

- [ ] **Step 1: 创建数据库创建脚本**

创建 `scripts/create_local_db.py` 文件：
```python
#!/usr/bin/env python
"""
创建本地业务数据库和表结构
"""
import os
import sys
import django
from django.conf import settings

# 添加项目路径到sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.settings')
django.setup()

def create_local_database():
    """创建本地数据库"""
    from django.db import connection
    
    db_name = settings.DATABASES['iwork_local']['NAME']
    db_user = settings.DATABASES['iwork_local']['USER']
    db_password = settings.DATABASES['iwork_local']['PASSWORD']
    
    # 连接到MySQL服务器（不指定数据库）
    with connection.cursor() as cursor:
        # 创建数据库
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print(f"数据库 {db_name} 创建成功")
        
        # 创建用户并授权
        cursor.execute(f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}'")
        cursor.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost'")
        cursor.execute("FLUSH PRIVILEGES")
        print(f"用户 {db_user} 创建并授权成功")

def create_local_table():
    """创建本地表结构"""
    from django.db import connection
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS `pytckreg3` (
        `TicketNo` VARCHAR(13) NOT NULL,
        `SeqNo` INT DEFAULT 0,
        `WrkOrder` VARCHAR(14) DEFAULT '',
        `BundleNo` INT DEFAULT 0,
        `StepNo` INT DEFAULT 0,
        `Qty` INT DEFAULT 0,
        `RegPerSysID` INT DEFAULT 0,
        `RegDate` DATETIME,
        `RegTime` DATETIME,
        `RFID` VARCHAR(10) DEFAULT '',
        `Flow` VARCHAR(40) DEFAULT '',
        `PO` VARCHAR(40) DEFAULT '',
        `TimeCost` INT DEFAULT 0,
        `SysSource` VARCHAR(3) DEFAULT '',
        `AccBundleNo` INT DEFAULT 0,
        `MtrType` VARCHAR(14) DEFAULT '',
        `Color` VARCHAR(35) DEFAULT '',
        `Sizx` VARCHAR(16) DEFAULT '',
        `SerialNum` VARCHAR(10) DEFAULT '',
        `StationID` VARCHAR(3) DEFAULT '',
        PRIMARY KEY (`TicketNo`),
        INDEX `idx_regdate` (`RegDate`),
        INDEX `idx_wrkorder` (`WrkOrder`),
        INDEX `idx_flow` (`Flow`),
        INDEX `idx_station` (`StationID`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    
    with connection.cursor() as cursor:
        cursor.execute(create_table_sql)
        print("表 pytckreg3 创建成功")

if __name__ == '__main__':
    try:
        create_local_database()
        create_local_table()
        print("本地数据库初始化完成")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
```

- [ ] **Step 2: 运行数据库创建脚本**

```bash
python scripts/create_local_db.py
```
预期输出：
```
数据库 iwork_local 创建成功
用户 iwork_local 创建并授权成功
表 pytckreg3 创建成功
本地数据库初始化完成
```

- [ ] **Step 3: 验证数据库创建**

```bash
mysql -u iwork_local -pLpf12160 -e "USE iwork_local; SHOW TABLES;"
```
预期输出：
```
+------------------------+
| Tables_in_iwork_local  |
+------------------------+
| pytckreg3              |
+------------------------+
```

- [ ] **Step 4: 提交更改**

```bash
git add scripts/create_local_db.py
git commit -m "feat: 添加本地数据库创建脚本"
```

---

## Task 3: 创建本地模型

**Files:**
- Create: `iwork/local_models.py`
- Modify: `iwork/models.py:1-60`

- [ ] **Step 1: 创建本地模型文件**

创建 `iwork/local_models.py` 文件：
```python
from django.db import models


class LocalPytckreg3(models.Model):
    """
    本地业务数据模型（可读写）
    映射到 iwork_local.pytckreg3 表
    """
    TicketNo = models.CharField('票号', max_length=13, primary_key=True)
    SeqNo = models.IntegerField('序号', default=0)
    WrkOrder = models.CharField('工单号', max_length=14, blank=True, default='')
    BundleNo = models.IntegerField('扎号', default=0)
    StepNo = models.IntegerField('工序号', default=0)
    Qty = models.IntegerField('数量', default=0)
    RegPerSysID = models.IntegerField('登记人系统ID', default=0)
    RegDate = models.DateTimeField('登记日期', null=True, blank=True)
    RegTime = models.DateTimeField('登记时间', null=True, blank=True)
    RFID = models.CharField('RFID', max_length=10, blank=True, default='')
    Flow = models.CharField('流程', max_length=40, blank=True, default='')
    PO = models.CharField('PO号', max_length=40, blank=True, default='')
    TimeCost = models.IntegerField('耗时', default=0)
    SysSource = models.CharField('系统来源', max_length=3, default='')
    AccBundleNo = models.IntegerField('累计扎号', default=0)
    MtrType = models.CharField('物料类型', max_length=14, blank=True, default='')
    Color = models.CharField('颜色', max_length=35, blank=True, default='')
    Sizx = models.CharField('尺码', max_length=16, blank=True, default='')
    SerialNum = models.CharField('序列号', max_length=10, blank=True, default='')
    StationID = models.CharField('工位ID', max_length=3, blank=True, default='')
    
    class Meta:
        app_label = 'iwork'
        db_table = 'pytckreg3'
        managed = False
        verbose_name = '本地打卡记录'
        verbose_name_plural = '本地打卡记录'
    
    def __str__(self) -> str:
        return self.TicketNo
```

- [ ] **Step 2: 更新models.py导入本地模型**

在 `iwork/models.py` 文件末尾添加：
```python
from iwork.local_models import LocalPytckreg3
```

- [ ] **Step 3: 验证模型**

```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 4: 提交更改**

```bash
git add iwork/local_models.py iwork/models.py
git commit -m "feat: 添加本地业务数据模型"
```

---

## Task 4: 更新数据库路由

**Files:**
- Modify: `iwork/database_router.py:1-34`

- [ ] **Step 1: 更新数据库路由**

修改 `iwork/database_router.py` 文件：
```python
class DatabaseRouter:
    """
    数据库路由器：
    - default: Django 系统权限库（读写）
    - iwork: 业务生产数据库（只读）
    - iwork_local: 本地业务数据库（读写）
    """
    
    iwork_app_labels = ['iwork']
    
    def db_for_read(self, model, **hints):
        """指定模型的读取数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            if model._meta.model_name == 'localpytckreg3':
                return 'iwork_local'
            return 'iwork'
        return 'default'
    
    def db_for_write(self, model, **hints):
        """指定模型的写入数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            if model._meta.model_name == 'localpytckreg3':
                return 'iwork_local'
            return None  # 远程数据库只读
        return 'default'
    
    def allow_relation(self, obj1, obj2, **hints):
        """判断两个对象是否允许关联"""
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """判断是否允许迁移"""
        if app_label in self.iwork_app_labels:
            if model_name == 'localpytckreg3':
                return db == 'iwork_local'
            return False
        return db == 'default'
```

- [ ] **Step 2: 验证路由配置**

```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 3: 提交更改**

```bash
git add iwork/database_router.py
git commit -m "feat: 更新数据库路由支持本地数据库"
```

---

## Task 5: 创建本地查询函数

**Files:**
- Create: `iwork/local_queries.py`

- [ ] **Step 1: 创建本地查询函数文件**

创建 `iwork/local_queries.py` 文件：
```python
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Avg

from iwork.local_models import LocalPytckreg3


def get_local_date_range(target: date) -> tuple:
    """获取指定日期的范围（开始时间、结束时间）"""
    start = timezone.make_aware(timezone.datetime.combine(target, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(target + timedelta(days=1), timezone.datetime.min.time()))
    return start, end


def get_local_records_queryset(target: date) -> object:
    """获取指定日期的 QuerySet（内部使用）"""
    start, end = get_local_date_range(target)
    return LocalPytckreg3.objects.using('iwork_local').filter(RegDate__gte=start, RegDate__lt=end)


def get_local_basic_stats(target: date) -> dict:
    """获取本地基础统计：工单数、总数量、平均耗时"""
    records = get_local_records_queryset(target)
    stats = records.aggregate(
        workorder_count=Count('WrkOrder', distinct=True),
        total_qty=Sum('Qty'),
        avg_time_cost=Avg('TimeCost')
    )
    return {
        'workorder_count': stats['workorder_count'] or 0,
        'total_qty': stats['total_qty'] or 0,
        'avg_time_cost': stats['avg_time_cost'],
    }


def get_local_hourly_stats(target: date) -> list:
    """获取本地按小时统计"""
    records = get_local_records_queryset(target)
    stats = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('hour')
        .annotate(qty=Sum('Qty'))
        .order_by('hour')
    )
    return [{'hour': s['hour'], 'qty': s['qty'] or 0} for s in stats]


def get_local_process_stats(target: date, limit: int = 10) -> list:
    """获取本地工序统计"""
    records = get_local_records_queryset(target)
    stats = list(
        records.values('StepNo')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'step': s['StepNo'], 'qty': s['qty'] or 0} for s in stats]


def get_local_flow_stats(target: date, limit: int = 10) -> list:
    """获取本地 Flow 统计"""
    records = get_local_records_queryset(target)
    stats = list(
        records.exclude(Flow='')
        .values('Flow')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'flow': s['Flow'], 'qty': s['qty'] or 0} for s in stats]


def get_local_station_stats(target: date, limit: int = 10) -> list:
    """获取本地工位统计"""
    records = get_local_records_queryset(target)
    stats = list(
        records.exclude(StationID='')
        .values('StationID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'station': s['StationID'], 'qty': s['qty'] or 0} for s in stats]


def get_local_worker_ranking(target: date, limit: int = 10) -> list:
    """获取本地员工排名"""
    records = get_local_records_queryset(target)
    stats = list(
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:limit]
    )
    return [{'name': str(s['RegPerSysID']), 'qty': s['qty'] or 0} for s in stats]


def get_local_workorders_list(target: date, limit: int = 20) -> list:
    """获取本地工单列表"""
    records = get_local_records_queryset(target)
    stats = list(
        records.values('WrkOrder')
        .annotate(total_qty=Sum('Qty'), step_count=Count('StepNo', distinct=True))
        .order_by('-total_qty')[:limit]
    )
    return [{'wrk_order': s['WrkOrder'], 'total_qty': s['total_qty'] or 0, 'step_count': s['step_count']} for s in stats]


def get_local_workorder_detail(wrk_order: str, target: date) -> dict:
    """获取本地工单详情"""
    start, end = get_local_date_range(target)
    records = LocalPytckreg3.objects.using('iwork_local').filter(
        WrkOrder=wrk_order,
        RegDate__gte=start,
        RegDate__lt=end
    )
    return {
        'wrk_order': wrk_order,
        'total_qty': records.aggregate(total=Sum('Qty'))['total'] or 0,
        'steps': list(
            records.values('StepNo')
            .annotate(qty=Sum('Qty'), count=Count('TicketNo'))
            .order_by('StepNo')
        ),
    }


def get_available_dates(mode: str = 'local') -> list:
    """
    获取可用的日期列表
    
    Args:
        mode: 'local' 或 'remote'
        
    Returns:
        list: 可用日期列表
    """
    if mode == 'local':
        # 从本地数据库获取有数据的日期
        dates = LocalPytckreg3.objects.using('iwork_local').dates(
            'RegDate', 'day', order='DESC'
        )
        return [date.date() for date in dates]
    else:
        # 从远程数据库获取所有日期（可能需要分页）
        from iwork.models import Pytckreg3
        dates = Pytckreg3.objects.using('iwork').dates(
            'RegDate', 'day', order='DESC'
        )
        return [date.date() for date in dates]
```

- [ ] **Step 2: 验证查询函数**

```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 3: 提交更改**

```bash
git add iwork/local_queries.py
git commit -m "feat: 添加本地数据库查询函数"
```

---

## Task 6: 创建数据同步逻辑

**Files:**
- Create: `iwork/sync.py`

- [ ] **Step 1: 创建同步逻辑文件**

创建 `iwork/sync.py` 文件：
```python
"""
数据同步模块
负责将远程数据库数据同步到本地数据库
"""
from datetime import date
from loguru import logger
from django.db import transaction

from iwork.models import Pytckreg3
from iwork.local_models import LocalPytckreg3


def has_changes(local_record, remote_record) -> bool:
    """
    检测记录是否有变更
    
    Args:
        local_record: 本地记录
        remote_record: 远程记录
        
    Returns:
        bool: 是否有变更
    """
    # 比较关键字段
    compare_fields = [
        'SeqNo', 'WrkOrder', 'BundleNo', 'StepNo', 'Qty',
        'RegPerSysID', 'RegDate', 'RegTime', 'RFID', 'Flow',
        'PO', 'TimeCost', 'SysSource', 'AccBundleNo', 'MtrType',
        'Color', 'Sizx', 'SerialNum', 'StationID'
    ]
    
    for field in compare_fields:
        local_value = getattr(local_record, field)
        remote_value = getattr(remote_record, field)
        
        # 处理None值
        if local_value is None and remote_value is None:
            continue
        if local_value is None or remote_value is None:
            return True
        
        # 比较值
        if local_value != remote_value:
            return True
    
    return False


def sync_date_data(target_date: date) -> dict:
    """
    同步指定日期的数据到本地数据库
    
    Args:
        target_date: 目标日期
        
    Returns:
        dict: 同步结果统计
    """
    logger.info(f"开始同步日期 {target_date} 的数据")
    
    # 1. 从远程数据库查询数据
    remote_records = Pytckreg3.objects.using('iwork').filter(
        RegDate__date=target_date
    )
    
    # 2. 从本地数据库查询现有数据
    local_records = {
        record.TicketNo: record 
        for record in LocalPytckreg3.objects.using('iwork_local').filter(
            RegDate__date=target_date
        )
    }
    
    # 3. 对比并更新
    stats = {
        'synced_count': 0,
        'updated_count': 0,
        'skipped_count': 0
    }
    
    with transaction.atomic():
        for record in remote_records:
            local_record = local_records.get(record.TicketNo)
            
            if local_record is None:
                # 新增记录
                LocalPytckreg3.objects.using('iwork_local').create(
                    TicketNo=record.TicketNo,
                    SeqNo=record.SeqNo,
                    WrkOrder=record.WrkOrder,
                    BundleNo=record.BundleNo,
                    StepNo=record.StepNo,
                    Qty=record.Qty,
                    RegPerSysID=record.RegPerSysID,
                    RegDate=record.RegDate,
                    RegTime=record.RegTime,
                    RFID=record.RFID,
                    Flow=record.Flow,
                    PO=record.PO,
                    TimeCost=record.TimeCost,
                    SysSource=record.SysSource,
                    AccBundleNo=record.AccBundleNo,
                    MtrType=record.MtrType,
                    Color=record.Color,
                    Sizx=record.Sizx,
                    SerialNum=record.SerialNum,
                    StationID=record.StationID,
                )
                stats['synced_count'] += 1
            elif has_changes(local_record, record):
                # 更新有变动的记录
                local_record.SeqNo = record.SeqNo
                local_record.WrkOrder = record.WrkOrder
                local_record.BundleNo = record.BundleNo
                local_record.StepNo = record.StepNo
                local_record.Qty = record.Qty
                local_record.RegPerSysID = record.RegPerSysID
                local_record.RegDate = record.RegDate
                local_record.RegTime = record.RegTime
                local_record.RFID = record.RFID
                local_record.Flow = record.Flow
                local_record.PO = record.PO
                local_record.TimeCost = record.TimeCost
                local_record.SysSource = record.SysSource
                local_record.AccBundleNo = record.AccBundleNo
                local_record.MtrType = record.MtrType
                local_record.Color = record.Color
                local_record.Sizx = record.Sizx
                local_record.SerialNum = record.SerialNum
                local_record.StationID = record.StationID
                local_record.save(using='iwork_local')
                stats['updated_count'] += 1
            else:
                # 跳过无变动的记录
                stats['skipped_count'] += 1
    
    logger.info(f"同步完成: 新增 {stats['synced_count']}, 更新 {stats['updated_count']}, 跳过 {stats['skipped_count']}")
    return stats
```

- [ ] **Step 2: 验证同步逻辑**

```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 3: 提交更改**

```bash
git add iwork/sync.py
git commit -m "feat: 添加数据同步逻辑"
```

---

## Task 7: 创建本地API视图

**Files:**
- Create: `iwork/api_views_local.py`
- Modify: `iwork/urls.py:1-24`

- [ ] **Step 1: 创建本地API视图文件**

创建 `iwork/api_views_local.py` 文件：
```python
"""
本地数据相关API视图
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import date
from loguru import logger

from iwork.local_queries import (
    get_local_basic_stats,
    get_local_hourly_stats,
    get_local_process_stats,
    get_local_flow_stats,
    get_local_station_stats,
    get_local_worker_ranking,
    get_local_workorders_list,
    get_available_dates,
)
from iwork.sync import sync_date_data
from iwork.queries import get_remote_stats


@api_view(['GET'])
def local_date_stats(request, target_date):
    """获取指定日期的统计数据"""
    try:
        date_obj = date.fromisoformat(target_date)
        mode = request.query_params.get('mode', 'local')
        
        if mode == 'local':
            # 从本地数据库查询
            stats = get_local_basic_stats(date_obj)
            hourly_stats = get_local_hourly_stats(date_obj)
            process_stats = get_local_process_stats(date_obj)
            flow_stats = get_local_flow_stats(date_obj)
            station_stats = get_local_station_stats(date_obj)
            worker_ranking = get_local_worker_ranking(date_obj)
            workorders = get_local_workorders_list(date_obj)
            
            return Response({
                'date': date_obj.isoformat(),
                'source': 'local',
                'stats': stats,
                'hourly_stats': hourly_stats,
                'process_stats': process_stats,
                'flow_stats': flow_stats,
                'station_stats': station_stats,
                'worker_ranking': worker_ranking,
                'workorders': workorders,
            }, status=status.HTTP_200_OK)
        else:
            # 从远程数据库查询
            stats = get_remote_stats(date_obj)
            return Response({
                'date': date_obj.isoformat(),
                'source': 'remote',
                'stats': stats,
            }, status=status.HTTP_200_OK)
            
    except Exception as e:
        logger.error(f'获取日期统计失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def available_dates(request):
    """获取可用的日期列表"""
    try:
        mode = request.query_params.get('mode', 'local')
        dates = get_available_dates(mode)
        
        return Response({
            'mode': mode,
            'dates': [d.isoformat() for d in dates],
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f'获取可用日期失败: {e}')
        return Response({'error': '获取数据失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def sync_date(request, target_date):
    """同步指定日期的数据到本地"""
    try:
        date_obj = date.fromisoformat(target_date)
        stats = sync_date_data(date_obj)
        
        return Response({
            'success': True,
            'message': '同步完成',
            'synced_count': stats['synced_count'],
            'updated_count': stats['updated_count'],
            'skipped_count': stats['skipped_count'],
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f'同步数据失败: {e}')
        return Response({'error': '同步失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
```

- [ ] **Step 2: 更新URL配置**

在 `iwork/urls.py` 文件中添加新的URL路由：
```python
from django.urls import path
from iwork import views, api_views, api_views_local

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    
    # 现有API
    path("api/dashboard/realtime/", api_views.realtime_stats, name="realtime-stats"),
    path("api/dashboard/hourly/", api_views.hourly_stats, name="hourly-stats"),
    path("api/dashboard/flow/<str:flow_name>/", api_views.flow_stats, name="flow-stats"),
    path("api/dashboard/workorders/", api_views.workorder_list, name="workorder-list"),
    path("api/dashboard/workorders/<str:wrk_order>/", api_views.workorder_detail, name="workorder-detail"),
    
    # 新增本地数据API
    path("api/dashboard/date/<str:target_date>/", api_views_local.local_date_stats, name="local-date-stats"),
    path("api/dashboard/dates/", api_views_local.available_dates, name="available-dates"),
    path("api/sync/<str:target_date>/", api_views_local.sync_date, name="sync-date"),
]
```

- [ ] **Step 3: 验证API视图**

```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 4: 提交更改**

```bash
git add iwork/api_views_local.py iwork/urls.py
git commit -m "feat: 添加本地数据API视图"
```

---

## Task 8: 更新前端UI

**Files:**
- Modify: `iwork/templates/iwork/dashboard.html:1-337`

- [ ] **Step 1: 更新前端HTML模板**

修改 `iwork/templates/iwork/dashboard.html` 文件，在header部分添加视图切换和日期选择器：

在 `<header>` 标签内的 `<div class="flex items-center gap-4">` 中添加：
```html
<!-- 视图切换导航栏 -->
<div class="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
    <button id="realtime-btn" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-md text-sm transition-colors font-medium">
        实时数据
    </button>
    <button id="history-btn" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-md text-sm transition-colors font-medium">
        历史数据
    </button>
</div>

<!-- 数据模式切换（历史数据视图） -->
<div id="mode-switcher" class="hidden flex bg-slate-800 rounded-lg p-1 border border-slate-700">
    <button id="local-mode-btn" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 rounded-md text-xs transition-colors font-medium">
        本地
    </button>
    <button id="remote-mode-btn" class="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded-md text-xs transition-colors font-medium">
        远程
    </button>
</div>

<!-- 日期选择器（历史数据视图显示） -->
<div id="date-picker-container" class="hidden flex items-center gap-2">
    <input type="date" id="date-picker" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
    <button id="sync-btn" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm transition-colors">
        同步数据
    </button>
</div>

<!-- 实时数据状态（实时数据视图显示） -->
<div id="realtime-status" class="flex items-center gap-2">
    <svg class="w-3 h-3" viewBox="0 0 12 12">
        <circle id="status-indicator" cx="6" cy="6" r="5" fill="#22c55e" class="status-pulse"/>
    </svg>
    <span id="connection-status" class="text-sm text-slate-400">已连接</span>
</div>
```

- [ ] **Step 2: 更新JavaScript逻辑**

在 `<script>` 标签中添加视图切换和日期选择逻辑：

```javascript
// 视图切换逻辑
const realtimeBtn = document.getElementById('realtime-btn');
const historyBtn = document.getElementById('history-btn');
const modeSwitcher = document.getElementById('mode-switcher');
const localModeBtn = document.getElementById('local-mode-btn');
const remoteModeBtn = document.getElementById('remote-mode-btn');
const datePickerContainer = document.getElementById('date-picker-container');
const realtimeStatus = document.getElementById('realtime-status');
const datePicker = document.getElementById('date-picker');
const syncBtn = document.getElementById('sync-btn');

let currentView = 'realtime';
let currentMode = 'local';

// 切换视图
function switchView(view) {
    currentView = view;
    if (view === 'realtime') {
        realtimeBtn.classList.remove('bg-slate-700', 'hover:bg-slate-600');
        realtimeBtn.classList.add('bg-blue-600', 'hover:bg-blue-500');
        historyBtn.classList.remove('bg-blue-600', 'hover:bg-blue-500');
        historyBtn.classList.add('bg-slate-700', 'hover:bg-slate-600');
        modeSwitcher.classList.add('hidden');
        datePickerContainer.classList.add('hidden');
        realtimeStatus.classList.remove('hidden');
        loadRealtimeData();
    } else {
        historyBtn.classList.remove('bg-slate-700', 'hover:bg-slate-600');
        historyBtn.classList.add('bg-blue-600', 'hover:bg-blue-500');
        realtimeBtn.classList.remove('bg-blue-600', 'hover:bg-blue-500');
        realtimeBtn.classList.add('bg-slate-700', 'hover:bg-slate-600');
        modeSwitcher.classList.remove('hidden');
        datePickerContainer.classList.remove('hidden');
        realtimeStatus.classList.add('hidden');
        loadAvailableDates();
        loadHistoryData();
    }
}

// 切换数据模式
function switchMode(mode) {
    currentMode = mode;
    if (mode === 'local') {
        localModeBtn.classList.remove('bg-slate-700', 'hover:bg-slate-600');
        localModeBtn.classList.add('bg-emerald-600', 'hover:bg-emerald-500');
        remoteModeBtn.classList.remove('bg-emerald-600', 'hover:bg-emerald-500');
        remoteModeBtn.classList.add('bg-slate-700', 'hover:bg-slate-600');
    } else {
        remoteModeBtn.classList.remove('bg-slate-700', 'hover:bg-slate-600');
        remoteModeBtn.classList.add('bg-emerald-600', 'hover:bg-emerald-500');
        localModeBtn.classList.remove('bg-emerald-600', 'hover:bg-emerald-500');
        localModeBtn.classList.add('bg-slate-700', 'hover:bg-slate-600');
    }
    loadAvailableDates();
    loadHistoryData();
}

// 加载可用日期
async function loadAvailableDates() {
    try {
        const response = await fetch(`/api/dashboard/dates/?mode=${currentMode}`);
        const data = await response.json();
        
        if (data.dates && data.dates.length > 0) {
            datePicker.value = data.dates[0];
            datePicker.max = data.dates[0];
        }
    } catch (error) {
        console.error('加载可用日期失败:', error);
    }
}

// 加载历史数据
async function loadHistoryData() {
    const selectedDate = datePicker.value;
    if (!selectedDate) return;
    
    try {
        const response = await fetch(`/api/dashboard/date/${selectedDate}/?mode=${currentMode}`);
        const data = await response.json();
        
        updateDashboard(data);
    } catch (error) {
        console.error('加载历史数据失败:', error);
    }
}

// 加载实时数据
async function loadRealtimeData() {
    try {
        const response = await fetch('/api/dashboard/realtime/');
        const data = await response.json();
        
        updateDashboard(data);
    } catch (error) {
        console.error('加载实时数据失败:', error);
    }
}

// 同步数据
async function syncData() {
    const selectedDate = datePicker.value;
    if (!selectedDate) return;
    
    try {
        syncBtn.disabled = true;
        syncBtn.textContent = '同步中...';
        
        const response = await fetch(`/api/sync/${selectedDate}/`, {
            method: 'POST',
        });
        const data = await response.json();
        
        if (data.success) {
            alert(`同步完成: 新增 ${data.synced_count}, 更新 ${data.updated_count}, 跳过 ${data.skipped_count}`);
            loadHistoryData();
        } else {
            alert('同步失败: ' + data.error);
        }
    } catch (error) {
        console.error('同步数据失败:', error);
        alert('同步失败');
    } finally {
        syncBtn.disabled = false;
        syncBtn.textContent = '同步数据';
    }
}

// 绑定事件
realtimeBtn.addEventListener('click', () => switchView('realtime'));
historyBtn.addEventListener('click', () => switchView('history'));
localModeBtn.addEventListener('click', () => switchMode('local'));
remoteModeBtn.addEventListener('click', () => switchMode('remote'));
datePicker.addEventListener('change', loadHistoryData);
syncBtn.addEventListener('click', syncData);

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initCharts();
    connectWebSocket();
    document.getElementById('pause-btn').addEventListener('click', togglePause);
    
    // 设置默认日期为今天
    const today = new Date().toISOString().split('T')[0];
    datePicker.value = today;
});
```

- [ ] **Step 3: 验证前端更新**

```bash
python manage.py check
```
预期输出：System check identified no issues (0 silenced)

- [ ] **Step 4: 提交更改**

```bash
git add iwork/templates/iwork/dashboard.html
git commit -m "feat: 更新前端UI支持视图切换和日期选择"
```

---

## Task 9: 编写单元测试

**Files:**
- Create: `tests/test_local_models.py`
- Create: `tests/test_sync.py`
- Create: `tests/test_api_views_local.py`

- [ ] **Step 1: 创建本地模型测试**

创建 `tests/test_local_models.py` 文件：
```python
"""
本地模型测试
"""
from django.test import TestCase
from iwork.local_models import LocalPytckreg3


class LocalPytckreg3Test(TestCase):
    """本地Pytckreg3模型测试"""
    
    def test_model_exists(self):
        """测试模型是否存在"""
        self.assertTrue(hasattr(LocalPytckreg3, 'TicketNo'))
        self.assertTrue(hasattr(LocalPytckreg3, 'Qty'))
    
    def test_model_str(self):
        """测试模型字符串表示"""
        record = LocalPytckreg3(TicketNo='TEST001')
        self.assertEqual(str(record), 'TEST001')
```

- [ ] **Step 2: 创建同步逻辑测试**

创建 `tests/test_sync.py` 文件：
```python
"""
同步逻辑测试
"""
from django.test import TestCase
from datetime import date
from iwork.sync import has_changes, sync_date_data


class HasChangesTest(TestCase):
    """数据变更检测测试"""
    
    def test_has_changes_same_record(self):
        """测试相同记录无变更"""
        class MockRecord:
            def __init__(self):
                self.SeqNo = 1
                self.Qty = 100
        
        local = MockRecord()
        remote = MockRecord()
        
        self.assertFalse(has_changes(local, remote))
    
    def test_has_changes_different_record(self):
        """测试不同记录有变更"""
        class MockRecord:
            def __init__(self, qty):
                self.SeqNo = 1
                self.Qty = qty
        
        local = MockRecord(100)
        remote = MockRecord(200)
        
        self.assertTrue(has_changes(local, remote))
```

- [ ] **Step 3: 创建API视图测试**

创建 `tests/test_api_views_local.py` 文件：
```python
"""
本地API视图测试
"""
from django.test import TestCase, Client
from django.urls import reverse
import json


class LocalDateStatsTest(TestCase):
    """本地日期统计API测试"""
    
    def setUp(self):
        self.client = Client()
    
    def test_local_date_stats_get(self):
        """测试获取本地日期统计"""
        response = self.client.get(
            reverse('local-date-stats', kwargs={'target_date': '2026-04-24'})
        )
        self.assertEqual(response.status_code, 200)
    
    def test_available_dates_get(self):
        """测试获取可用日期列表"""
        response = self.client.get(reverse('available-dates'))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('dates', data)
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_local_models.py tests/test_sync.py tests/test_api_views_local.py -v
```
预期输出：所有测试通过

- [ ] **Step 5: 提交更改**

```bash
git add tests/test_local_models.py tests/test_sync.py tests/test_api_views_local.py
git commit -m "test: 添加本地数据相关单元测试"
```

---

## Task 10: 集成测试和验证

**Files:**
- Modify: `tests/test_api_views.py:1-155`

- [ ] **Step 1: 运行现有测试确保无回归**

```bash
pytest tests/ -v
```
预期输出：所有现有测试通过

- [ ] **Step 2: 手动测试API端点**

启动开发服务器：
```bash
python manage.py runserver
```

测试API端点：
```bash
# 测试实时数据API
curl http://localhost:8000/api/dashboard/realtime/

# 测试本地日期统计API
curl http://localhost:8000/api/dashboard/date/2026-04-24/?mode=local

# 测试可用日期API
curl http://localhost:8000/api/dashboard/dates/?mode=local

# 测试同步API
curl -X POST http://localhost:8000/api/sync/2026-04-24/
```

- [ ] **Step 3: 测试前端功能**

在浏览器中访问 `http://localhost:8000/`，测试：
1. 视图切换功能
2. 数据模式切换功能
3. 日期选择功能
4. 同步按钮功能

- [ ] **Step 4: 性能测试**

测试大量数据下的性能表现：
```bash
# 测试本地查询性能
time curl http://localhost:8000/api/dashboard/date/2026-04-24/?mode=local

# 测试同步性能
time curl -X POST http://localhost:8000/api/sync/2026-04-24/
```

- [ ] **Step 5: 提交最终更改**

```bash
git add .
git commit -m "feat: 完成生产看板日期查询与本地持久化功能"
```

---

## 执行说明

**推荐执行方式：** 使用 `superpowers:subagent-driven-development` 技能执行此计划

**执行流程：**
1. 每个Task分派一个新子代理执行
2. 每个Task完成后进行代码审查
3. 确保所有测试通过后再进行下一个Task
4. 完成所有Task后进行集成测试

**注意事项：**
1. 确保MySQL服务已启动
2. 确保本地数据库用户已创建并授权
3. 在执行数据库相关操作前备份现有数据
4. 定期提交代码以便追踪进度