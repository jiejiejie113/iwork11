# 生产看板功能设计文档

## 概述

为 iwork 项目添加生产看板功能，实现实时产量统计、工单进度追踪、产线效率分析和在制品监控。采用 Django Channels + Redis + Celery Beat 技术方案，通过 WebSocket 实现数据实时推送。

## 业务背景

### 数据源

- **数据库**: MySQL 5.6 (iwork 别名，只读)
- **表名**: `payroll.pytckreg3`
- **访问方式**: 只读查询，无法操作外部数据库

### 表结构

| 字段 | 类型 | 说明 |
|-----|------|-----|
| TicketNo | VARCHAR(50) | 主键 |
| SeqNo | INT | 序号 |
| WrkOrder | VARCHAR(20) | 工单号 |
| BundleNo | VARCHAR(20) | 扎号 |
| StepNo | INT | 工序号 |
| Qty | INT | 产量 |
| RegPerSysID | VARCHAR(20) | 员工系统ID |
| RegDate | DATE | 登记日期 |
| RegTime | TIME | 登记时间 |
| RFID | VARCHAR(20) | 办卡ID |
| Flow | VARCHAR(20) | 工艺组别 |
| TimeCost | INT | 耗时 |
| SysSource | VARCHAR(10) | 系统来源 |
| SerialNum | VARCHAR(20) | 序列号 |
| StationID | VARCHAR(10) | 工站ID |

### 关键字段说明

- `Flow`: 工艺组别，用于员工分组
- `StepNo`: 工序号，区分不同生产环节
- `Qty`: 当前工序生产数量
- `RegDate` + `RegTime`: 组合为精确到秒的时间戳
- 忽略字段: `AccBundleNo`, `MtrType`, `Color`, `Sizx`, `PO`, `SeqNo`

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端看板 (Django模板+HTMX)                │
│                    ↕ WebSocket 连接 (Django Channels)           │
└─────────────────────────────────────────────────────────────────┘
                              ↓ 推送统计数据
┌─────────────────────────────────────────────────────────────────┐
│                   Django Channels (ASGI)                        │
│           Channel Layer (Redis) + WebSocket Consumer             │
└─────────────────────────────────────────────────────────────────┘
                              ↑ 发送消息
┌─────────────────────────────────────────────────────────────────┐
│               Celery Beat (60秒定时任务)                         │
│       1. 查询 pytckreg3 最新数据 (增量查询)                      │
│       2. 计算统计指标 → Redis 缓存                               │
│       3. 通过 Channel Layer 推送到前端                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓ 查询
┌─────────────────────────────────────────────────────────────────┐
│            MySQL 5.6 (iwork数据库 - 只读)                        │
│                   payroll.pytckreg3 表                           │
└─────────────────────────────────────────────────────────────────┘
```

### 组件职责

| 组件 | 职责 |
|-----|------|
| **Django (WSGI)** | 处理 HTTP 请求，渲染看板页面 |
| **Django Channels (ASGI)** | 处理 WebSocket 连接，管理 Channel Layer |
| **Redis** | Channel Layer 通信 + 统计数据缓存 |
| **Celery Beat** | 60秒定时任务，增量查询 + 推送 |

## 数据模型

### Pytckreg3 模型

```python
# iwork/models.py
from django.db import models
from datetime import datetime


class Pytckreg3(models.Model):
    """
    生产打卡记录（只读模型）
    映射到 payroll.pytckreg3 表
    
    注意：
    - 原表有复合主键 (TicketNo, SysSource, SeqNo)
    - Django 不支持复合主键，使用 TicketNo 作为主键
    - RegDate 和 RegTime 表结构都是 datetime，但实际数据：
      - RegDate: 只存储年月日（如 2026-04-21 00:00:00）
      - RegTime: 只存储时分秒（Excel 日期序列号，如 1899-12-30 12:56:11）
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

    @property
    def full_datetime(self):
        """
        组合 RegDate（年月日）和 RegTime（时分秒）获取完整时间戳
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
```

### Redis 缓存结构

| Key | 类型 | TTL | 说明 |
|-----|------|-----|------|
| `iwork:dashboard:realtime` | Hash | 60s | 实时统计数据 |
| `iwork:dashboard:hourly:{date}:{hour}` | Hash | 1d | 按小时统计 |
| `iwork:dashboard:daily:{date}` | Hash | 30d | 按天统计 |
| `iwork:last_sync_time` | String | 永久 | 最后同步时间戳 |

## 统计指标

### 实时产量统计

| 指标 | 计算方式 | 用途 |
|-----|---------|------|
| 今日总产量 | `SUM(Qty) WHERE RegDate = TODAY` | 顶部卡片 |
| 各工序产量 | `GROUP BY StepNo, SUM(Qty)` | 工序图表 |
| 各工站产量 | `GROUP BY StationID, SUM(Qty)` | 工站图表 |
| 各Flow组产量 | `GROUP BY Flow, SUM(Qty)` | 效率对比 |

### 工单进度追踪

| 指标 | 计算方式 | 用途 |
|-----|---------|------|
| 工单明细 | `WHERE WrkOrder = ?` | 工单详情页 |
| 工单工序分布 | `GROUP BY WrkOrder, StepNo` | 进度追踪 |

### 产线效率分析

| 指标 | 计算方式 | 用途 |
|-----|---------|------|
| 每小时产量趋势 | `GROUP BY HOUR(RegTime)` | 趋势图表 |
| 员工产出排行 | `GROUP BY RegPerSysID, SUM(Qty)` | 排行榜 |
| Flow组效率 | `GROUP BY Flow, AVG(TimeCost)` | 效率对比 |

### 在制品监控

| 指标 | 计算方式 | 用途 |
|-----|---------|------|
| 在制工序分布 | `GROUP BY StepNo, COUNT(DISTINCT WrkOrder)` | 在制监控 |

## API 设计

### REST API

| 端点 | 方法 | 参数 | 用途 |
|-----|------|-----|------|
| `/api/dashboard/realtime/` | GET | - | 实时统计 |
| `/api/dashboard/hourly/` | GET | `date` | 按小时统计 |
| `/api/dashboard/flow/<flow>/` | GET | - | Flow组数据 |
| `/api/workorders/` | GET | `status`, `page` | 工单列表 |
| `/api/workorders/<id>/` | GET | - | 工单详情 |

### WebSocket

**连接地址**: `ws://localhost:8000/ws/dashboard/`

**推送消息格式**:
```json
{
    "type": "dashboard_update",
    "timestamp": "2026-04-21T14:30:00",
    "data": {
        "today_total": 12580,
        "step_stats": [
            {"step": 26, "qty": 3200, "count": 450},
            {"step": 87, "qty": 4100, "count": 580}
        ],
        "flow_stats": [
            {"flow": "IR-1IR-E", "qty": 5600, "efficiency": 0.92},
            {"flow": "L06A-L06A", "qty": 4300, "efficiency": 0.88}
        ],
        "hourly_trend": [
            {"hour": 8, "qty": 1200},
            {"hour": 9, "qty": 1800}
        ],
        "top_workers": [
            {"id": "7034", "qty": 850},
            {"id": "10044", "qty": 720}
        ],
        "station_stats": [
            {"station": "96", "qty": 2100},
            {"station": "97", "qty": 1900}
        ]
    }
}
```

## 前端页面

### 设计系统（ui-ux-pro-max）

#### 风格定位
- **产品类型**: 实时监控仪表盘（IoT/Analytics Dashboard）
- **UI风格**: Dark Mode + Data-Dense（深色背景、数据密集）
- **适用场景**: 长时间监控、工厂生产环境、低光环境
- **性能**: ⚡ Excellent | **无障碍**: ✓ WCAG AAA

#### 色彩系统（工业风格）

| 角色 | Hex | CSS变量 | 用途 |
|-----|-----|---------|------|
| Primary | `#64748B` | `bg-primary` | 工业灰（主背景、卡片） |
| Secondary | `#94A3B8` | `bg-secondary` | 次要元素、边框 |
| CTA/Alert | `#F97316` | `bg-alert` | 安全橙（告警、重要指标） |
| Background | `#F8FAFC` | `bg-base` | 基础背景（深色模式用 `#0F172A`） |
| Text | `#334155` | `text-base` | 正文文字 |
| Success | `#22C55E` | `bg-success` | 正常状态/产量增长 |
| Danger | `#EF4444` | `bg-danger` | 异常/产量下降 |

#### 字体系统

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* 字体配置 */
font-family: 'Inter', system-ui, sans-serif;
/* 标题: font-weight: 600-700 */
/* 正文: font-weight: 400-500 */
/* 数字指标: font-weight: 700, tabular-nums */
```

#### 图表类型选择

| 数据类型 | 推荐图表 | 颜色指导 | 交互 |
|---------|---------|---------|------|
| 实时产量 | **Streaming Area Chart** | 当前: `#00FF00`, 历史: 20% opacity | 暂停按钮 ✓ |
| 每小时趋势 | **Line Chart** | 主色: `#0080FF`, 多系列区分色 | Hover + Zoom |
| 工序对比 | **Grouped Bar Chart** | 每工序独立颜色 | Hover tooltip |
| Flow组效率 | **Radar/Spider Chart** | 单组: `#0080FF` 20% fill | Toggle切换 |

### 页面结构

```
/dashboard/              → 主看板页面
├── Header（固定顶部）
│   ├── Logo + 标题
│   ├── WebSocket状态指示灯（绿/红/灰）
│   ├── 暂停/恢复按钮（实时数据控制）
│   └── 时间显示（最后更新时间）
├── 顶部统计卡片（4列网格）
│   ├── 今日总产量（大数字 + 趋势箭头）
│   ├── 活跃工站数（实时计数）
│   ├── 在制工单数（进度条）
│   └── 平均效率（百分比）
├── 图表区域（2×2网格）
│   ├── 工序产量柱状图（Grouped Bar）
│   ├── Flow组效率雷达图（Radar）
│   ├── 每小时趋势线图（Streaming Area）
│   └── 工站产量分布（Bar）
└── 数据表格区域
    ├── 实时打卡记录（最新10条，滚动）
    └── 员工产出排行（TOP 10）
```

### Tailwind CSS 实现

#### 响应式布局

```html
<!-- 主容器 -->
<div class="min-h-screen bg-slate-900 px-4 sm:px-6 lg:px-8">
  
  <!-- 顶部卡片网格 -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
    <!-- 今日产量卡片 -->
    <div class="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <div class="text-slate-400 text-sm">今日总产量</div>
      <div class="text-2xl font-bold text-white tabular-nums">
        {{ today_total }}
      </div>
      <div class="flex items-center text-sm mt-1">
        <!-- 趋势箭头 -->
        <span class="text-green-500">↑ 12%</span>
      </div>
    </div>
    <!-- 其他卡片... -->
  </div>
  
  <!-- 图表网格 -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
    <!-- 工序产量图表 -->
    <div class="bg-slate-800 rounded-lg p-4">
      <canvas id="stepChart"></canvas>
    </div>
    <!-- 其他图表... -->
  </div>
</div>
```

#### 关键样式规则

| 规则 | 正确做法 | 错误做法 |
|-----|---------|---------|
| 深色模式卡片 | `bg-slate-800` + `border-slate-700` | `bg-white/10`（太透明） |
| 数字指标 | `font-bold tabular-nums` | 普通字体（数字宽度不一致） |
| 交互元素 | `cursor-pointer` + `transition-colors duration-200` | 无hover反馈 |
| 状态指示灯 | SVG 圆形 + 颜色变化 | emoji ⚡ 🔴 |
| 图表加载 | 骨架屏 `animate-pulse` | 空白等待 |

### WebSocket 前端实现

```javascript
// 连接管理
let ws;
let paused = false;

function connectWebSocket() {
  ws = new WebSocket('ws://localhost:8000/ws/dashboard/');
  
  ws.onopen = () => updateStatus('connected');
  ws.onmessage = (event) => {
    if (!paused) {
      const data = JSON.parse(event.data);
      updateDashboard(data);
    }
  };
  ws.onclose = () => {
    updateStatus('disconnected');
    setTimeout(connectWebSocket, 5000); // 自动重连
  };
}

// 暂停/恢复控制（无障碍要求）
document.getElementById('pauseBtn').addEventListener('click', () => {
  paused = !paused;
  updatePauseButton(paused);
});

// 检查 prefers-reduced-motion
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
```

### 技术选型

| 技术 | 选择 | 理由 |
|-----|------|------|
| 模板引擎 | Django Templates | 单一代码库，AI友好 |
| CSS框架 | **Tailwind CSS** (CDN) | 响应式、原子化、无需构建 |
| 图表库 | **Chart.js** (CDN) | 轻量、支持实时更新 |
| 实时通信 | WebSocket (原生JS) | 无需额外库 |
| 图标 | **Heroicons** (SVG) | 无障碍、不使用emoji |

### CDN 引入

```html
<!-- Tailwind CSS -->
<script src="https://cdn.tailwindcss.com"></script>

<!-- Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<!-- Heroicons (inline SVG) -->
<!-- 直接在模板中使用 SVG 代码 -->
```

### 无障碍要求

| 要求 | 实现 |
|-----|------|
| 图表颜色盲友好 | 添加 pattern overlays |
| 实时数据暂停 | 提供暂停按钮（防止闪烁） |
| 状态通知 | aria-live 区域更新 |
| 键盘导航 | focus-visible 状态 |
| 减少动画 | 检查 prefers-reduced-motion |

### 预发布检查清单

- [ ] 无 emoji 作为图标（使用 SVG: Heroicons）
- [ ] 所有可点击元素添加 `cursor-pointer`
- [ ] Hover 状态平滑过渡（150-300ms）
- [ ] 深色模式文字对比度 4.5:1 以上
- [ ] 键盘导航 focus 状态可见
- [ ] 响应式测试：375px, 768px, 1024px, 1440px
- [ ] 实时图表提供暂停按钮
- [ ] `prefers-reduced-motion` 媒体查询支持

## 定时任务

### Celery Beat 配置

```python
# iwork/celery.py
from celery import Celery
from celery.schedules import crontab

app = Celery('iwork')
app.conf.beat_schedule = {
    'sync-dashboard-stats': {
        'task': 'iwork.tasks.sync_dashboard_stats',
        'schedule': 60.0,  # 每60秒
    },
}
```

### 任务逻辑

```python
# iwork/tasks.py
from celery import shared_task
from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from datetime import datetime, timedelta
from iwork.models import Pytckreg3

@shared_task
def sync_dashboard_stats():
    """
    同步看板统计数据
    1. 读取上次同步时间
    2. 增量查询新数据
    3. 计算统计指标
    4. 更新Redis缓存
    5. 推送WebSocket消息
    """
    last_sync = cache.get('iwork:last_sync_time')
    
    # 增量查询
    queryset = Pytckreg3.objects.using('iwork')
    if last_sync:
        # 根据RegDate和RegTime组合过滤
        queryset = queryset.filter(
            RegDate__gte=last_sync.date()
        ) | queryset.filter(
            RegDate=last_sync.date(),
            RegTime__gt=last_sync.time()
        )
    
    # 计算统计
    stats = calculate_statistics(queryset)
    
    # 更新缓存
    cache.set('iwork:dashboard:realtime', stats, 60)
    cache.set('iwork:last_sync_time', datetime.now(), None)
    
    # WebSocket推送
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'dashboard',
        {
            'type': 'dashboard_update',
            'data': stats
        }
    )
```

## 项目结构

```
iwork/
├── __init__.py
├── asgi.py              # ASGI配置（Channels）
├── celery.py            # Celery配置
├── routing.py           # WebSocket路由
├── settings.py          # Django配置
├── urls.py              # HTTP路由
├── consumers.py         # WebSocket消费者
├── database_router.py   # 数据库路由器
├── models.py            # 数据模型
├── views.py             # HTTP视图
├── api_views.py         # API视图
├── tasks.py             # Celery任务
├── statistics.py        # 统计计算模块
└── templates/
    └── iwork/
        └── dashboard.html
```

## 依赖包

```txt
# 新增依赖
channels>=4.0.0          # WebSocket支持
channels-redis>=4.0.0    # Redis Channel Layer
celery>=5.3.0            # 定时任务
redis>=5.0.0             # Redis客户端
django-redis>=5.4.0      # Django Redis缓存
daphne>=4.0.0            # ASGI服务器
```

## 配置变更

### settings.py 新增配置

```python
# Channels
ASGI_APPLICATION = 'iwork.asgi.application'
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('127.0.0.1', 6379)],
        },
    },
}

# Celery
CELERY_BROKER_URL = 'redis://127.0.0.1:6379/1'
CELERY_RESULT_BACKEND = 'redis://127.0.0.1:6379/2'
CELERY_BEAT_SCHEDULE = {
    'sync-dashboard-stats': {
        'task': 'iwork.tasks.sync_dashboard_stats',
        'schedule': 60.0,
    },
}

# Redis Cache
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/0',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# INSTALLED_APPS
INSTALLED_APPS = [
    # ...
    'channels',
    'django_celery_beat',
    'iwork',
]
```

## 扩展性设计

### 已支持的扩展

| 扩展方向 | 实现方式 |
|---------|---------|
| 新统计指标 | 在 `statistics.py` 添加计算函数 |
| 新看板页面 | 复用 Consumer，添加新路由和模板 |
| 告警通知 | 同一 Channel Layer 推送告警消息 |
| 多房间订阅 | Channels Group 机制支持按 Flow/工站分组 |
| 历史分析 | Redis 缓存结构预留了按时间维度的 Key |

### Phase 2 扩展规划

```
├── 告警系统：产量异常、积压预警
├── 权限控制：不同角色看不同看板
├── 数据导出：Excel/PDF报表
├── 移动端适配：响应式看板
└── 多语言支持
```

## 成功标准

1. **功能完整性**
   - 看板页面正常显示四个核心指标
   - WebSocket 连接稳定，每60秒收到推送
   - API 端点返回正确数据

2. **性能指标**
   - 首页加载 < 2秒
   - 定时任务执行 < 5秒
   - Redis 缓存命中率 > 90%

3. **稳定性**
   - WebSocket 断线自动重连
   - Celery Beat 任务失败自动重试
   - 数据库连接异常时优雅降级

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| 外部数据库连接超时 | 定时任务失败 | 设置查询超时，捕获异常，记录日志 |
| Redis 不可用 | 推送失败 | 降级为 HTTP 轮询模式 |
| 数据量过大 | 查询慢 | 增量查询，索引优化，分页 |
| WebSocket 连接数过多 | 内存溢出 | 限制连接数，心跳检测 |