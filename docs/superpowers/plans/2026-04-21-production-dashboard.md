# 生产看板功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 Django Channels + Redis + Celery 的实时生产看板系统，实现产量统计、工单追踪、效率分析和在制品监控。

**Architecture:** 前端 Django 模板 + Tailwind CSS 通过 WebSocket 接收 Celery Beat 定时任务推送的统计数据，Redis 作为 Channel Layer 和缓存层，iwork app 只读访问远程 MySQL pytckreg3 表。

**Tech Stack:** Django 5.2, Django Channels 4.x, Celery 5.x, Redis, Chart.js, Tailwind CSS (CDN)

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|-----|------|
| `iwork/__init__.py` | Celery 应用初始化 |
| `iwork/apps.py` | Django app 配置 |
| `iwork/models.py` | Pytckreg3 只读模型 |
| `iwork/statistics.py` | 统计计算函数 |
| `iwork/tasks.py` | Celery 定时任务 |
| `iwork/celery.py` | Celery 配置 |
| `iwork/consumers.py` | WebSocket 消费者 |
| `iwork/routing.py` | WebSocket 路由 |
| `iwork/api_views.py` | REST API 视图 |
| `iwork/views.py` | 页面视图 |
| `iwork/urls.py` | app URL 配置 |
| `iwork/asgi.py` | ASGI 配置（更新） |
| `iwork/templates/iwork/dashboard.html` | 看板页面模板 |

### 修改文件

| 文件 | 变更 |
|-----|------|
| `iwork/settings.py` | 添加 Channels、Celery、Redis 配置 |
| `iwork/urls.py`（项目级） | 包含 iwork app URLs |
| `requirements.txt` | 添加新依赖 |

---

## Task 1: 安装依赖包

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 添加依赖到 requirements.txt**

在 `requirements.txt` 文件末尾添加以下内容：

```txt
# WebSocket 支持
channels>=4.0.0
channels-redis>=4.0.0

# 定时任务
celery>=5.3.0
django-celery-beat>=2.5.0

# Redis
redis>=5.0.0
django-redis>=5.4.0

# ASGI 服务器
daphne>=4.0.0
```

- [ ] **Step 2: 安装依赖**

运行：
```powershell
pip install -r requirements.txt
```

预期：所有包成功安装

- [ ] **Step 3: 验证安装**

运行：
```powershell
pip list | Select-String -Pattern "channels|celery|redis|daphne"
```

预期：显示 channels, celery, redis, daphne 版本号

- [ ] **Step 4: 提交**

```powershell
git add requirements.txt
git commit -m "[2026-04-21][CHORE] 添加生产看板依赖包"
```

---

## Task 2: 创建 iwork Django App

**Files:**
- Create: `iwork/__init__.py`
- Create: `iwork/apps.py`
- Modify: `iwork/settings.py`

- [ ] **Step 1: 创建 app 目录结构**

运行：
```powershell
python manage.py startapp iwork
```

预期：创建 `iwork/` 目录，包含 `__init__.py`, `apps.py`, `models.py`, `views.py` 等文件

- [ ] **Step 2: 配置 apps.py**

修改 `iwork/apps.py`，确保内容如下：

```python
from django.apps import AppConfig


class IworkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'iwork'
    verbose_name = '生产看板'
```

- [ ] **Step 3: 注册 app 到 settings.py**

在 `iwork/settings.py` 的 `INSTALLED_APPS` 列表中添加（放在最后）：

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "django_celery_beat",
    "iwork",
]
```

- [ ] **Step 4: 提交**

```powershell
git add iwork/__init__.py iwork/apps.py iwork/settings.py
git commit -m "[2026-04-21][FEAT] 创建 iwork Django app"
```

---

## Task 3: 创建 Pytckreg3 数据模型

**Files:**
- Create: `iwork/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 编写数据模型（匹配真实表结构和数据特性）**

创建 `iwork/models.py`：

```python
from django.db import models
from datetime import datetime


class Pytckreg3(models.Model):
    """
    生产打卡记录（只读模型）
    映射到 payroll.pytckreg3 表
    
    注意：
    - 原表有复合主键 (TicketNo, SysSource, SeqNo)
    - Django 不支持复合主键，使用 TicketNo 作为主键（唯一性足够）
    - RegDate 和 RegTime 表结构都是 datetime，但实际数据：
      - RegDate: 只存储年月日（如 2026-04-21 00:00:00）
      - RegTime: 只存储时分秒（Excel 日期序列号，如 1899-12-30 12:56:11）
    - 需要通过 full_datetime 属性组合获取完整时间戳
    """
    TicketNo = models.CharField(max_length=13, primary_key=True, verbose_name='票号')
    SeqNo = models.IntegerField(default=0, verbose_name='序号')
    WrkOrder = models.CharField(max_length=14, verbose_name='工单号')
    BundleNo = models.IntegerField(default=0, verbose_name='扎号')
    StepNo = models.IntegerField(default=0, verbose_name='工序号')
    Qty = models.IntegerField(default=0, verbose_name='产量')
    RegPerSysID = models.IntegerField(default=0, verbose_name='员工系统ID')
    RegDate = models.DateTimeField(null=True, verbose_name='登记日期（年月日）')
    RegTime = models.DateTimeField(null=True, verbose_name='登记时间（时分秒）')
    RFID = models.CharField(max_length=10, default='', verbose_name='办卡ID')
    Flow = models.CharField(max_length=40, default='', verbose_name='工艺组别')
    PO = models.CharField(max_length=40, default='', verbose_name='PO号')
    TimeCost = models.IntegerField(default=0, verbose_name='耗时')
    SysSource = models.CharField(max_length=3, default='', verbose_name='系统来源')
    AccBundleNo = models.IntegerField(default=0, verbose_name='累计扎号')
    MtrType = models.CharField(max_length=14, default='', verbose_name='物料类型')
    Color = models.CharField(max_length=35, default='', verbose_name='颜色')
    Sizx = models.CharField(max_length=16, default='', verbose_name='尺码')
    SerialNum = models.CharField(max_length=10, default='', verbose_name='序列号')
    StationID = models.CharField(max_length=3, default='', verbose_name='工站ID')

    class Meta:
        app_label = 'iwork'
        managed = False
        db_table = 'pytckreg3'
        verbose_name = '打卡记录'
        verbose_name_plural = '打卡记录'

    @property
    def full_datetime(self):
        """
        组合 RegDate（年月日）和 RegTime（时分秒）获取完整时间戳
        
        示例：
        - RegDate = 2026-04-21 00:00:00
        - RegTime = 1899-12-30 12:56:11
        - 返回 = 2026-04-21 12:56:11
        """
        if self.RegDate and self.RegTime:
            return datetime(
                self.RegDate.year,
                self.RegDate.month,
                self.RegDate.day,
                self.RegTime.hour,
                self.RegTime.minute,
                self.RegTime.second
            )
        return None

    def __str__(self):
        return f'{self.WrkOrder}-{self.StepNo}-{self.Qty}'
```

- [ ] **Step 2: 编写模型测试**

创建 `tests/test_models.py`：

```python
import pytest
from datetime import datetime
from iwork.models import Pytckreg3


class TestPytckreg3Model:
    """Pytckreg3 模型测试"""

    def test_model_meta_app_label(self):
        """测试 app_label 配置"""
        assert Pytckreg3._meta.app_label == 'iwork'

    def test_model_meta_managed_false(self):
        """测试 managed=False（禁止迁移）"""
        assert Pytckreg3._meta.managed is False

    def test_model_meta_db_table(self):
        """测试 db_table 配置"""
        assert Pytckreg3._meta.db_table == 'pytckreg3'

    def test_field_max_lengths(self):
        """测试字段最大长度（匹配真实表结构）"""
        ticket_no = Pytckreg3._meta.get_field('TicketNo')
        assert ticket_no.max_length == 13
        
        wrk_order = Pytckreg3._meta.get_field('WrkOrder')
        assert wrk_order.max_length == 14
        
        rfid = Pytckreg3._meta.get_field('RFID')
        assert rfid.max_length == 10
        
        flow = Pytckreg3._meta.get_field('Flow')
        assert flow.max_length == 40
        
        station_id = Pytckreg3._meta.get_field('StationID')
        assert station_id.max_length == 3

    def test_datetime_fields_type(self):
        """测试 RegDate 和 RegTime 都是 DateTimeField"""
        reg_date = Pytckreg3._meta.get_field('RegDate')
        reg_time = Pytckreg3._meta.get_field('RegTime')
        assert reg_date.__class__.__name__ == 'DateTimeField'
        assert reg_time.__class__.__name__ == 'DateTimeField'

    def test_full_datetime_property(self):
        """测试 full_datetime 组合年月日和时分秒"""
        # RegDate 只存年月日，RegTime 只存时分秒（Excel日期序列号）
        record = Pytckreg3(
            RegDate=datetime(2026, 4, 21, 0, 0, 0),  # 年月日
            RegTime=datetime(1899, 12, 30, 12, 56, 11)  # 时分秒（Excel格式）
        )
        expected = datetime(2026, 4, 21, 12, 56, 11)
        assert record.full_datetime == expected

    def test_full_datetime_none_values(self):
        """测试 RegDate 或 RegTime 为 None 时返回 None"""
        record1 = Pytckreg3(RegDate=None, RegTime=datetime(1899, 12, 30, 12, 0, 0))
        assert record1.full_datetime is None
        
        record2 = Pytckreg3(RegDate=datetime(2026, 4, 21), RegTime=None)
        assert record2.full_datetime is None
        
        record3 = Pytckreg3(RegDate=None, RegTime=None)
        assert record3.full_datetime is None

    def test_str_representation(self):
        """测试字符串表示"""
        record = Pytckreg3(
            WrkOrder='612110',
            StepNo=90,
            Qty=4
        )
        assert str(record) == '612110-90-4'
```

- [ ] **Step 3: 运行测试验证**

运行：
```powershell
pytest tests/test_models.py -v
```

预期：所有测试通过

- [ ] **Step 4: 提交**

```powershell
git add iwork/models.py tests/test_models.py
git commit -m "[2026-04-21][FEAT] 创建 Pytckreg3 只读数据模型"
```

---

## Task 4: 配置 Redis 和 Channels

**Files:**
- Modify: `iwork/settings.py`

- [ ] **Step 1: 添加 Channels 配置**

在 `iwork/settings.py` 文件末尾添加：

```python
# Channels 配置
ASGI_APPLICATION = 'iwork.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('127.0.0.1', 6379)],
        },
    },
}
```

- [ ] **Step 2: 添加 Redis 缓存配置**

在 `iwork/settings.py` 文件末尾添加：

```python
# Redis 缓存配置
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/0',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'iwork',
    }
}
```

- [ ] **Step 3: 添加 Celery 配置**

在 `iwork/settings.py` 文件末尾添加：

```python
# Celery 配置
CELERY_BROKER_URL = 'redis://127.0.0.1:6379/1'
CELERY_RESULT_BACKEND = 'redis://127.0.0.1:6379/2'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Shanghai'
```

- [ ] **Step 4: 提交**

```powershell
git add iwork/settings.py
git commit -m "[2026-04-21][FEAT] 配置 Redis、Channels 和 Celery"
```

---

## Task 5: 配置 Celery 应用

**Files:**
- Create: `iwork/celery.py`
- Modify: `iwork/__init__.py`

- [ ] **Step 1: 创建 celery.py**

创建 `iwork/celery.py`：

```python
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.settings')

app = Celery('iwork')
app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.beat_schedule = {
    'sync-dashboard-stats-every-60s': {
        'task': 'iwork.tasks.sync_dashboard_stats',
        'schedule': 60.0,
    },
}
```

- [ ] **Step 2: 初始化 Celery in __init__.py**

修改 `iwork/__init__.py`：

```python
from .celery import app as celery_app

__all__ = ('celery_app',)
```

- [ ] **Step 3: 验证 Celery 配置**

运行：
```powershell
python -c "from iwork import celery_app; print(celery_app.conf.beat_schedule)"
```

预期：输出包含 `sync-dashboard-stats-every-60s` 任务配置

- [ ] **Step 4: 提交**

```powershell
git add iwork/celery.py iwork/__init__.py
git commit -m "[2026-04-21][FEAT] 配置 Celery 应用和定时任务"
```

---

## Task 6: 创建统计计算模块

**Files:**
- Create: `iwork/statistics.py`
- Create: `tests/test_statistics.py`

- [ ] **Step 1: 创建 statistics.py**

创建 `iwork/statistics.py`：

```python
from datetime import date, datetime
from django.db.models import Sum, Count, Avg, F
from django.core.cache import cache
from iwork.models import Pytckreg3


def get_today_stats():
    """
    获取今日实时统计数据
    
    注意：
    - RegDate 是 datetime 类型，但实际只存储年月日（如 2026-04-21 00:00:00）
    - RegTime 是 datetime 类型，但实际只存储时分秒（如 1899-12-30 12:56:11）
    - 查询今日数据：使用 RegDate 的日期部分过滤
    - 每小时趋势：使用 HOUR() 提取 RegTime 中的小时数
    
    返回：今日总产量、工序统计、Flow统计、工站统计、员工排行、小时趋势
    """
    today = date.today()
    # RegDate 是 datetime 类型，只存年月日，用 date() 函数提取日期部分比较
    records = Pytckreg3.objects.using('iwork').filter(
        RegDate__year=today.year,
        RegDate__month=today.month,
        RegDate__day=today.day
    )
    
    total_qty = records.aggregate(total=Sum('Qty'))['total'] or 0
    
    step_stats = list(
        records.values('StepNo')
        .annotate(qty=Sum('Qty'), count=Count('TicketNo'))
        .order_by('-qty')[:10]
    )
    
    flow_stats = list(
        records.values('Flow')
        .annotate(qty=Sum('Qty'), avg_time=Avg('TimeCost'))
        .order_by('-qty')[:10]
    )
    
    station_stats = list(
        records.values('StationID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:10]
    )
    
    top_workers = list(
        records.values('RegPerSysID')
        .annotate(qty=Sum('Qty'))
        .order_by('-qty')[:10]
    )
    
    # RegTime 是 datetime 类型，只存时分秒，用 HOUR() 提取小时数
    hourly_trend = list(
        records.extra(select={'hour': 'HOUR(RegTime)'})
        .values('hour')
        .annotate(qty=Sum('Qty'))
        .order_by('hour')
    )
    
    return {
        'today_total': total_qty,
        'step_stats': step_stats,
        'flow_stats': flow_stats,
        'station_stats': station_stats,
        'top_workers': top_workers,
        'hourly_trend': hourly_trend,
    }


def get_realtime_stats():
    """
    从缓存获取实时统计，缓存不存在时计算并缓存
    """
    cache_key = 'dashboard:realtime'
    stats = cache.get(cache_key)
    
    if stats is None:
        stats = get_today_stats()
        cache.set(cache_key, stats, 60)
    
    return stats


def calculate_flow_efficiency(flow_stats):
    """
    计算 Flow 组效率指标
    efficiency = 1 - (avg_time / baseline_time)
    baseline_time 暂设为 10 秒
    """
    baseline_time = 10.0
    for stat in flow_stats:
        avg_time = stat.get('avg_time', 0) or 0
        efficiency = max(0, min(1, 1 - (avg_time / baseline_time)))
        stat['efficiency'] = round(efficiency, 2)
    return flow_stats
```

- [ ] **Step 2: 创建测试**

创建 `tests/test_statistics.py`：

```python
import pytest
from unittest.mock import Mock, patch
from iwork.statistics import calculate_flow_efficiency


class TestStatistics:
    """统计模块测试"""

    def test_calculate_flow_efficiency_normal(self):
        """测试正常效率计算"""
        flow_stats = [{'flow': 'IR-1IR-E', 'avg_time': 3, 'qty': 100}]
        result = calculate_flow_efficiency(flow_stats)
        assert result[0]['efficiency'] == 0.7

    def test_calculate_flow_efficiency_zero_time(self):
        """测试零耗时"""
        flow_stats = [{'flow': 'L06A-L06A', 'avg_time': 0, 'qty': 50}]
        result = calculate_flow_efficiency(flow_stats)
        assert result[0]['efficiency'] == 1.0

    def test_calculate_flow_efficiency_high_time(self):
        """测试高耗时（效率为0）"""
        flow_stats = [{'flow': 'PQC-1PQC-B', 'avg_time': 15, 'qty': 80}]
        result = calculate_flow_efficiency(flow_stats)
        assert result[0]['efficiency'] == 0.0

    def test_calculate_flow_efficiency_none_time(self):
        """测试 None 耗时"""
        flow_stats = [{'flow': 'TEST', 'avg_time': None, 'qty': 30}]
        result = calculate_flow_efficiency(flow_stats)
        assert result[0]['efficiency'] == 1.0
```

- [ ] **Step 3: 运行测试**

运行：
```powershell
pytest tests/test_statistics.py -v
```

预期：所有测试通过

- [ ] **Step 4: 提交**

```powershell
git add iwork/statistics.py tests/test_statistics.py
git commit -m "[2026-04-21][FEAT] 创建统计计算模块"
```

---

## Task 7: 创建 Celery 定时任务

**Files:**
- Create: `iwork/tasks.py`
- Create: `tests/test_tasks.py`

- [ ] **Step 1: 创建 tasks.py**

创建 `iwork/tasks.py`：

```python
from celery import shared_task
from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from datetime import datetime
from loguru import logger

from iwork.statistics import get_today_stats, calculate_flow_efficiency


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def sync_dashboard_stats(self):
    """
    同步看板统计数据任务
    每60秒执行一次：
    1. 查询今日数据
    2. 计算统计指标
    3. 更新Redis缓存
    4. 推送WebSocket消息
    """
    try:
        logger.info('开始同步看板统计数据')
        
        stats = get_today_stats()
        stats['flow_stats'] = calculate_flow_efficiency(stats['flow_stats'])
        
        cache.set('dashboard:realtime', stats, 60)
        cache.set('dashboard:last_sync', datetime.now().isoformat(), None)
        
        logger.success('统计数据已缓存，开始推送 WebSocket')
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'dashboard',
            {
                'type': 'dashboard_update',
                'timestamp': datetime.now().isoformat(),
                'data': stats,
            }
        )
        
        logger.success('WebSocket 推送完成')
        return stats
        
    except Exception as e:
        logger.error(f'同步任务失败: {e}')
        raise self.retry(exc=e)
```

- [ ] **Step 2: 创建任务测试**

创建 `tests/test_tasks.py`：

```python
import pytest
from unittest.mock import patch, Mock
from iwork.tasks import sync_dashboard_stats


class TestTasks:
    """Celery 任务测试"""

    @patch('iwork.tasks.get_today_stats')
    @patch('iwork.tasks.cache')
    @patch('iwork.tasks.get_channel_layer')
    def test_sync_dashboard_stats_success(
        self, mock_channel_layer, mock_cache, mock_get_stats
    ):
        """测试任务成功执行"""
        mock_get_stats.return_value = {
            'today_total': 100,
            'flow_stats': [{'avg_time': 3}],
            'step_stats': [],
            'station_stats': [],
            'top_workers': [],
            'hourly_trend': [],
        }
        
        mock_layer = Mock()
        mock_layer.group_send = Mock()
        mock_channel_layer.return_value = mock_layer
        
        result = sync_dashboard_stats()
        
        assert result['today_total'] == 100
        mock_cache.set.assert_called()
        mock_layer.group_send.assert_called_once()

    @patch('iwork.tasks.get_today_stats')
    def test_sync_dashboard_stats_retry_on_failure(self, mock_get_stats):
        """测试任务失败时重试"""
        mock_get_stats.side_effect = Exception('数据库连接失败')
        
        with pytest.raises(Exception):
            sync_dashboard_stats()
```

- [ ] **Step 3: 运行测试**

运行：
```powershell
pytest tests/test_tasks.py -v
```

预期：测试通过

- [ ] **Step 4: 提交**

```powershell
git add iwork/tasks.py tests/test_tasks.py
git commit -m "[2026-04-21][FEAT] 创建 Celery 定时任务 sync_dashboard_stats"
```

---

## Task 8: 配置 ASGI 和 WebSocket 路由

**Files:**
- Modify: `iwork/asgi.py`
- Create: `iwork/routing.py`

- [ ] **Step 1: 修改 asgi.py**

修改 `iwork/asgi.py`：

```python
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.settings')

django_asgi_app = get_asgi_application()

from iwork.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
```

- [ ] **Step 2: 创建 routing.py**

创建 `iwork/routing.py`：

```python
from django.urls import re_path
from iwork.consumers import DashboardConsumer

websocket_urlpatterns = [
    re_path(r'ws/dashboard/$', DashboardConsumer.as_asgi()),
]
```

- [ ] **Step 3: 提交**

```powershell
git add iwork/asgi.py iwork/routing.py
git commit -m "[2026-04-21][FEAT] 配置 ASGI 和 WebSocket 路由"
```

---

## Task 9: 创建 WebSocket 消费者

**Files:**
- Create: `iwork/consumers.py`
- Create: `tests/test_consumers.py`

- [ ] **Step 1: 创建 consumers.py**

创建 `iwork/consumers.py`：

```python
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from loguru import logger


class DashboardConsumer(AsyncWebsocketConsumer):
    """看板 WebSocket 消费者"""

    async def connect(self):
        """连接时加入 dashboard 组"""
        await self.channel_name
        await self.channel_layer.group_add('dashboard', self.channel_name)
        await self.accept()
        logger.info(f'WebSocket 连接建立: {self.channel_name}')

    async def disconnect(self, close_code):
        """断开时离开 dashboard 组"""
        await self.channel_layer.group_discard('dashboard', self.channel_name)
        logger.info(f'WebSocket 连接关闭: {close_code}')

    async def dashboard_update(self, event):
        """接收组消息并发送到客户端"""
        message = {
            'type': 'dashboard_update',
            'timestamp': event.get('timestamp'),
            'data': event.get('data'),
        }
        await self.send(text_data=json.dumps(message, ensure_ascii=False))
```

- [ ] **Step 2: 创建消费者测试**

创建 `tests/test_consumers.py`：

```python
import pytest
from channels.testing.websocket import WebsocketCommunicator
from iwork.asgi import application
from iwork.consumers import DashboardConsumer


class TestDashboardConsumer:
    """WebSocket 消费者测试"""

    @pytest.mark.asyncio
    async def test_connect(self):
        """测试 WebSocket 连接"""
        communicator = WebsocketCommunicator(
            DashboardConsumer.as_asgi(),
            'ws/dashboard/'
        )
        connected, _ = await communicator.connect()
        assert connected is True
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_dashboard_update_message(self):
        """测试消息推送"""
        communicator = WebsocketCommunicator(
            DashboardConsumer.as_asgi(),
            'ws/dashboard/'
        )
        await communicator.connect()
        
        await communicator.send_json_to({
            'type': 'dashboard_update',
            'data': {'today_total': 1000}
        })
```

- [ ] **Step 3: 提交**

```powershell
git add iwork/consumers.py tests/test_consumers.py
git commit -m "[2026-04-21][FEAT] 创建 WebSocket 消费者 DashboardConsumer"
```

---

## Task 10: 创建 REST API 视图

**Files:**
- Create: `iwork/api_views.py`
- Create: `tests/test_api_views.py`

- [ ] **Step 1: 创建 api_views.py**

创建 `iwork/api_views.py`：

```python
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from datetime import date
from loguru import logger

from iwork.models import Pytckreg3
from iwork.statistics import get_today_stats, get_realtime_stats


@api_view(['GET'])
def realtime_stats(request):
    """获取实时统计数据"""
    try:
        stats = get_realtime_stats()
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取实时统计失败: {e}')
        return Response(
            {'error': '获取数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def hourly_stats(request):
    """获取按小时统计数据"""
    target_date = request.query_params.get('date', date.today().isoformat())
    cache_key = f'dashboard:hourly:{target_date}'
    
    stats = cache.get(cache_key)
    if stats is None:
        try:
            target = date.fromisoformat(target_date)
            records = Pytckreg3.objects.using('iwork').filter(RegDate=target)
            stats = list(
                records.extra(select={'hour': 'HOUR(RegTime)'})
                .values('hour')
                .annotate(qty=Sum('Qty'))
                .order_by('hour')
            )
            cache.set(cache_key, stats, 86400)
        except Exception as e:
            logger.error(f'获取小时统计失败: {e}')
            return Response(
                {'error': '获取数据失败'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    return Response(stats, status=status.HTTP_200_OK)


@api_view(['GET'])
def flow_stats(request, flow_name):
    """获取指定 Flow 组统计数据"""
    today = date.today()
    try:
        records = Pytckreg3.objects.using('iwork').filter(
            RegDate=today,
            Flow=flow_name
        )
        stats = {
            'flow': flow_name,
            'total_qty': records.aggregate(total=Sum('Qty'))['total'] or 0,
            'worker_count': records.values('RegPerSysID').distinct().count(),
        }
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取 Flow 统计失败: {e}')
        return Response(
            {'error': '获取数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def workorder_list(request):
    """获取工单列表"""
    today = date.today()
    try:
        records = Pytckreg3.objects.using('iwork').filter(RegDate=today)
        workorders = list(
            records.values('WrkOrder')
            .annotate(total_qty=Sum('Qty'), step_count=Count('StepNo', distinct=True))
            .order_by('-total_qty')[:50]
        )
        return Response(workorders, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取工单列表失败: {e}')
        return Response(
            {'error': '获取数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def workorder_detail(request, wrk_order):
    """获取工单详情"""
    try:
        records = Pytckreg3.objects.using('iwork').filter(WrkOrder=wrk_order)
        detail = {
            'wrk_order': wrk_order,
            'total_qty': records.aggregate(total=Sum('Qty'))['total'] or 0,
            'steps': list(
                records.values('StepNo')
                .annotate(qty=Sum('Qty'), count=Count('TicketNo'))
                .order_by('StepNo')
            ),
        }
        return Response(detail, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'获取工单详情失败: {e}')
        return Response(
            {'error': '获取数据失败'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
```

- [ ] **Step 2: 添加 djangorestframework 依赖**

在 `requirements.txt` 添加：

```txt
# REST API
djangorestframework>=3.15.0
```

运行：
```powershell
pip install djangorestframework
```

在 `settings.py` INSTALLED_APPS 添加 `'rest_framework'`

- [ ] **Step 3: 创建 API 测试**

创建 `tests/test_api_views.py`：

```python
import pytest
from unittest.mock import patch, Mock


class TestApiViews:
    """API 视图测试"""

    @patch('iwork.api_views.get_realtime_stats')
    def test_realtime_stats_success(self, mock_get_stats):
        """测试实时统计 API"""
        from iwork.api_views import realtime_stats
        from rest_framework.test import APIRequestFactory
        
        mock_get_stats.return_value = {'today_total': 1000}
        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/realtime/')
        
        response = realtime_stats(request)
        assert response.status_code == 200
        assert response.data['today_total'] == 1000
```

- [ ] **Step 4: 运行测试**

运行：
```powershell
pytest tests/test_api_views.py -v
```

预期：测试通过

- [ ] **Step 5: 提交**

```powershell
pip install djangorestframework
git add iwork/api_views.py tests/test_api_views.py requirements.txt iwork/settings.py
git commit -m "[2026-04-21][FEAT] 创建 REST API 视图"
```

---

## Task 11: 创建看板页面视图和模板

**Files:**
- Modify: `iwork/views.py`
- Create: `iwork/templates/iwork/dashboard.html`

- [ ] **Step 1: 创建页面视图**

修改 `iwork/views.py`：

```python
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from iwork.statistics import get_realtime_stats


@require_http_methods(['GET'])
def dashboard(request):
    """看板主页面"""
    stats = get_realtime_stats()
    context = {
        'stats': stats,
        'page_title': '生产看板',
    }
    return render(request, 'iwork/dashboard.html', context)
```

- [ ] **Step 2: 创建模板目录**

运行：
```powershell
New-Item -ItemType Directory -Path "iwork\templates\iwork" -Force
```

- [ ] **Step 3: 创建看板模板**

创建 `iwork/templates/iwork/dashboard.html`：

```html
{% load static %}
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }} - iwork</title>
    
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    
    <!-- Inter Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    
    <style>
        body { font-family: 'Inter', system-ui, sans-serif; }
        .tabular-nums { font-variant-numeric: tabular-nums; }
    </style>
</head>
<body class="min-h-screen bg-slate-900 px-4 sm:px-6 lg:px-8 py-6">
    
    <!-- Header -->
    <header class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-bold text-white">{{ page_title }}</h1>
        <div class="flex items-center gap-4">
            <div class="flex items-center gap-2">
                <svg id="ws-status" class="w-3 h-3" viewBox="0 0 12 12">
                    <circle cx="6" cy="6" r="5" fill="#22C55E"/>
                </svg>
                <span id="ws-status-text" class="text-sm text-slate-400">已连接</span>
            </div>
            <button id="pause-btn" 
                    class="px-3 py-1 bg-slate-700 text-slate-200 rounded cursor-pointer transition-colors duration-200 hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-orange-500"
                    aria-label="暂停实时更新">
                暂停
            </button>
            <span id="last-update" class="text-sm text-slate-500 tabular-nums"></span>
        </div>
    </header>
    
    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div class="text-slate-400 text-sm">今日总产量</div>
            <div class="text-3xl font-bold text-white tabular-nums mt-2" id="today-total">
                {{ stats.today_total|default:0 }}
            </div>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div class="text-slate-400 text-sm">活跃工站数</div>
            <div class="text-3xl font-bold text-white tabular-nums mt-2" id="station-count">
                {{ stats.station_stats|length|default:0 }}
            </div>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div class="text-slate-400 text-sm">Flow组数</div>
            <div class="text-3xl font-bold text-white tabular-nums mt-2" id="flow-count">
                {{ stats.flow_stats|length|default:0 }}
            </div>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div class="text-slate-400 text-sm">工序数</div>
            <div class="text-3xl font-bold text-white tabular-nums mt-2" id="step-count">
                {{ stats.step_stats|length|default:0 }}
            </div>
        </div>
    </div>
    
    <!-- 图表区域 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <h2 class="text-lg font-semibold text-white mb-4">工序产量分布</h2>
            <canvas id="step-chart" height="200"></canvas>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <h2 class="text-lg font-semibold text-white mb-4">每小时产量趋势</h2>
            <canvas id="hourly-chart" height="200"></canvas>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <h2 class="text-lg font-semibold text-white mb-4">Flow组效率</h2>
            <canvas id="flow-chart" height="200"></canvas>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <h2 class="text-lg font-semibold text-white mb-4">工站产量分布</h2>
            <canvas id="station-chart" height="200"></canvas>
        </div>
    </div>
    
    <!-- 数据表格 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <h2 class="text-lg font-semibold text-white mb-4">员工产出排行 TOP 10</h2>
            <table class="w-full text-sm text-slate-300">
                <thead>
                    <tr class="text-slate-400 border-b border-slate-700">
                        <th class="text-left py-2">员工ID</th>
                        <th class="text-right py-2">产量</th>
                    </tr>
                </thead>
                <tbody id="workers-table">
                    {% for worker in stats.top_workers %}
                    <tr class="border-b border-slate-700/50">
                        <td class="py-2">{{ worker.RegPerSysID }}</td>
                        <td class="text-right py-2 tabular-nums font-semibold">{{ worker.qty }}</td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="2" class="py-4 text-center text-slate-500">暂无数据</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <h2 class="text-lg font-semibold text-white mb-4">Flow组统计</h2>
            <table class="w-full text-sm text-slate-300">
                <thead>
                    <tr class="text-slate-400 border-b border-slate-700">
                        <th class="text-left py-2">Flow组</th>
                        <th class="text-right py-2">产量</th>
                        <th class="text-right py-2">效率</th>
                    </tr>
                </thead>
                <tbody id="flow-table">
                    {% for flow in stats.flow_stats %}
                    <tr class="border-b border-slate-700/50">
                        <td class="py-2">{{ flow.flow }}</td>
                        <td class="text-right py-2 tabular-nums font-semibold">{{ flow.qty }}</td>
                        <td class="text-right py-2">
                            <span class="px-2 py-1 rounded {% if flow.efficiency >= 0.8 %}bg-green-900 text-green-400{% elif flow.efficiency >= 0.5 %}bg-yellow-900 text-yellow-400{% else %}bg-red-900 text-red-400{% endif %}">
                                {{ flow.efficiency|floatformat:0 }}%
                            </span>
                        </td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="3" class="py-4 text-center text-slate-500">暂无数据</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- WebSocket 脚本 -->
    <script>
        let ws;
        let paused = false;
        const charts = {};
        
        // 初始化图表
        function initCharts() {
            const stepCtx = document.getElementById('step-chart').getContext('2d');
            charts.step = new Chart(stepCtx, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: '产量',
                        data: [],
                        backgroundColor: '#0080FF',
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { color: '#334155' }, ticks: { color: '#94A3B8' } },
                        y: { grid: { color: '#334155' }, ticks: { color: '#94A3B8' } }
                    }
                }
            });
            
            const hourlyCtx = document.getElementById('hourly-chart').getContext('2d');
            charts.hourly = new Chart(hourlyCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: '产量',
                        data: [],
                        borderColor: '#0080FF',
                        backgroundColor: 'rgba(0, 128, 255, 0.2)',
                        fill: true,
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { color: '#334155' }, ticks: { color: '#94A3B8' } },
                        y: { grid: { color: '#334155' }, ticks: { color: '#94A3B8' } }
                    }
                }
            });
        }
        
        // WebSocket 连接
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/dashboard/`);
            
            ws.onopen = () => updateStatus('connected');
            ws.onmessage = (event) => {
                if (!paused) {
                    const data = JSON.parse(event.data);
                    updateDashboard(data);
                }
            };
            ws.onclose = () => {
                updateStatus('disconnected');
                setTimeout(connectWebSocket, 5000);
            };
            ws.onerror = () => updateStatus('error');
        }
        
        // 更新状态指示
        function updateStatus(status) {
            const indicator = document.getElementById('ws-status');
            const text = document.getElementById('ws-status-text');
            const colors = { connected: '#22C55E', disconnected: '#EF4444', error: '#F97316' };
            indicator.querySelector('circle').setAttribute('fill', colors[status] || '#64748B');
            text.textContent = { connected: '已连接', disconnected: '已断开', error: '错误' }[status] || '未知';
        }
        
        // 更新看板数据
        function updateDashboard(data) {
            document.getElementById('today-total').textContent = data.data.today_total || 0;
            document.getElementById('station-count').textContent = data.data.station_stats?.length || 0;
            document.getElementById('flow-count').textContent = data.data.flow_stats?.length || 0;
            document.getElementById('step-count').textContent = data.data.step_stats?.length || 0;
            document.getElementById('last-update').textContent = data.timestamp;
            
            // 更新图表
            if (charts.step && data.data.step_stats) {
                charts.step.data.labels = data.data.step_stats.map(s => `工序 ${s.StepNo}`);
                charts.step.data.datasets[0].data = data.data.step_stats.map(s => s.qty);
                charts.step.update();
            }
            
            if (charts.hourly && data.data.hourly_trend) {
                charts.hourly.data.labels = data.data.hourly_trend.map(h => `${h.hour}时`);
                charts.hourly.data.datasets[0].data = data.data.hourly_trend.map(h => h.qty);
                charts.hourly.update();
            }
        }
        
        // 暂停按钮
        document.getElementById('pause-btn').addEventListener('click', function() {
            paused = !paused;
            this.textContent = paused ? '恢复' : '暂停';
            this.classList.toggle('bg-orange-600', paused);
        });
        
        // 初始化
        initCharts();
        connectWebSocket();
    </script>
</body>
</html>
```

- [ ] **Step 4: 提交**

```powershell
git add iwork/views.py iwork/templates/iwork/dashboard.html
git commit -m "[2026-04-21][FEAT] 创建看板页面视图和模板"
```

---

## Task 12: 配置 URL 路由

**Files:**
- Create: `iwork/urls.py`
- Modify: `iwork/urls.py`（项目级）

- [ ] **Step 1: 创建 iwork app urls.py**

创建 `iwork/urls.py`：

```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from iwork.views import dashboard
from iwork.api_views import (
    realtime_stats,
    hourly_stats,
    flow_stats,
    workorder_list,
    workorder_detail,
)

urlpatterns = [
    # 页面路由
    path('dashboard/', dashboard, name='dashboard'),
    
    # API 路由
    path('api/dashboard/realtime/', realtime_stats, name='api-realtime'),
    path('api/dashboard/hourly/', hourly_stats, name='api-hourly'),
    path('api/dashboard/flow/<str:flow_name>/', flow_stats, name='api-flow'),
    path('api/workorders/', workorder_list, name='api-workorder-list'),
    path('api/workorders/<str:wrk_order>/', workorder_detail, name='api-workorder-detail'),
]
```

- [ ] **Step 2: 修改项目级 urls.py**

修改 `iwork/urls.py`（项目根目录）：

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('iwork.urls')),
]
```

- [ ] **Step 3: 提交**

```powershell
git add iwork/urls.py
git commit -m "[2026-04-21][FEAT] 配置 URL 路由"
```

---

## Task 13: 验证和启动服务

**Files:**
- None（验证步骤）

- [ ] **Step 1: 确保 Redis 服务运行**

运行：
```powershell
redis-cli ping
```

预期：返回 `PONG`

如果 Redis 未安装，运行：
```powershell
# Windows 下载 Redis: https://github.com/microsoftarchive/redis/releases
# 或使用 WSL/Docker
```

- [ ] **Step 2: 启动 Celery Worker 和 Beat**

运行（需要两个终端）：

终端1 - Celery Worker：
```powershell
celery -A iwork worker -l info
```

终端2 - Celery Beat：
```powershell
celery -A iwork beat -l info
```

- [ ] **Step 3: 启动 Daphne ASGI 服务器**

运行：
```powershell
daphne -b 0.0.0.0 -p 8000 iwork.asgi:application
```

- [ ] **Step 4: 访问看板页面**

浏览器打开：
```
http://localhost:8000/dashboard/
```

预期：
- 页面加载成功
- WebSocket 连接状态显示绿色
- 每60秒数据自动更新

- [ ] **Step 5: 运行完整测试**

运行：
```powershell
pytest tests/ -v
```

预期：所有测试通过

---

## 验收检查

- [ ] `pip install -r requirements.txt` 成功
- [ ] `pytest tests/ -v` 全部通过
- [ ] Redis 服务正常运行
- [ ] Celery Worker 和 Beat 启动成功
- [ ] Daphne ASGI 服务器启动成功
- [ ] 看板页面 `http://localhost:8000/dashboard/` 可访问
- [ ] WebSocket 连接状态显示绿色
- [ ] 每60秒数据自动更新

---

## 启动命令汇总

```powershell
# 1. 启动 Redis（如果未运行）
redis-server

# 2. 启动 Celery Worker
celery -A iwork worker -l info

# 3. 启动 Celery Beat
celery -A iwork beat -l info

# 4. 启动 ASGI 服务器
daphne -b 0.0.0.0 -p 8000 iwork.asgi:application

# 访问看板
# http://localhost:8000/dashboard/
```