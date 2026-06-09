# SSE 迁移数据流设计

> 将实时看板从 WebSocket（Django Channels）迁移到 SSE（Server-Sent Events）

## 一、整体架构变更

### 变更前

```
Celery Beat (60s)
    → get_batch_stats() → cache_batch_to_redis()
    → Channel Layer (Redis 异步) → WebSocket 推送
    → 前端 WebSocket 接收
```

### 变更后

```
Celery Beat (60s)
    → get_batch_stats() → cache_batch_to_redis()        ← 这部分不变
    → (去掉 Channel Layer 推送)

前端 EventSource → GET /api/dashboard/stream/
    → Django StreamingHttpResponse
    → 循环：cache.get() 读 Redis → yield JSON → sleep 60s
```

### 被删除的组件

| 文件/配置 | 说明 |
|-----------|------|
| `iwork/consumers.py` | WebSocket 消费者，整个文件删除 |
| `iwork/routing.py` | WebSocket 路由，整个文件删除 |
| `CHANNEL_LAYERS` 配置 | `settings.py` 中删除 |
| `tasks.py` 中 WebSocket 推送代码 | 删除 `group_send` 相关的 6 行 |
| `asgi.py` 中 WebSocket 路由 | 简化为纯 HTTP ASGI |
| 依赖 `channels`、`channels-redis` | 从 `requirements.txt` 移除 |

### 新增的组件

| 文件 | 说明 |
|------|------|
| `iwork/api_views.py` 新增 `dashboard_stream()` | SSE 视图，约 40 行 |
| `iwork/urls.py` 新增路由 | `api/dashboard/stream/` |
| `dashboard.html` 前端改动 | `WebSocket` → `EventSource`，约 15 行 |

---

## 二、实时看板页面加载流程

```
用户浏览器
    │
    │  1. 打开 http://localhost:8000/dashboard/
    ▼
Django 视图 (views.py)
    │
    │  2. 返回 dashboard.html（纯 HTML/CSS/JS）
    ▼
浏览器 JavaScript
    │
    │  3. 页面加载完成，onMounted 触发
    │
    ├─► 4a. loadRealtimeData()  ← 首次 HTTP GET，立刻拿到数据渲染页面
    │       → GET /api/dashboard/realtime?stepno=70
    │       → api_views.realtime_stats()
    │       → cache.get('stats:realtime:70')  ← 读 Redis 缓存
    │       → 返回 JSON → 渲染图表
    │
    └─► 4b. connectSSE()       ← 建立 SSE 长连接，等待后续推送
            → EventSource('/api/dashboard/stream/')
            → 进入 SSE 连接
```

---

## 三、SSE 连接生命周期

```
浏览器 EventSource
    │
    │  GET /api/dashboard/stream/
    │  Accept: text/event-stream
    ▼
Daphne (ASGI Server)
    │
    │  接收 HTTP 请求，交给 Django 处理
    ▼
api_views.dashboard_stream()    ← 新增的 SSE 视图
    │
    │  def dashboard_stream(request):
    │      def event_stream():
    │          while True:
    │              # ① 从 Redis 读缓存（同步连接，已验证正常）
    │              stats = cache.get('stats:realtime:70')
    │              process_list = cache.get('stats:realtime:_process_list')
    │              detail = cache.get('stats:detail:flow_overview')
    │
    │              # ② 组装数据
    │              data = {
    │                  'type': 'dashboard_update',
    │                  'timestamp': now().isoformat(),
    │                  'data': stats,
    │                  'process_list': process_list,
    │                  'detail': detail,
    │              }
    │
    │              # ③ 推送给浏览器
    │              yield f"data: {json.dumps(data)}\n\n"
    │
    │              # ④ 等 60s（期间连接保持，浏览器可随时断开）
    │              time.sleep(60)
    │
    │      return StreamingHttpResponse(
    │          event_stream(),
    │          content_type='text/event-stream'
    │      )
    ▼
浏览器收到 SSE 消息
    │
    │  EventSource.onmessage 触发
    │  解析 JSON → 更新 Vue 响应式数据 → 图表自动刷新
    ▼
用户看到看板数据更新（无闪烁，无页面重载）
```

---

## 四、用户设置目标产量流程

```
用户在前端输入目标产量 → 点击保存
    │
    │  HTTP POST（不再是 WebSocket 消息）
    ▼
POST /api/dashboard/set-targets/
    │
    │  body: { "flow": "xxx", "targets": {...} }
    ▼
api_views.set_targets()         ← 新增的 HTTP 视图
    │
    │  1. 写入 Redis
    │     cache.set('targets:{date}:{flow}', targets, ttl)
    │
    │  2. 返回 JSON 成功响应
    ▼
前端收到 200 OK → 提示"保存成功"
    │
    │  其他用户：下一次 SSE 推送（最多 60s 后）
    │  自动拿到更新后的目标产量
    ▼
```

---

## 五、用户切换工序流程

```
用户点击切换工序（如从 70 切到 69）
    │
    │  1. 前端关闭当前 SSE，用新参数重连
    ▼
旧 EventSource.close()
    │
    │  2. 新建 EventSource
    ▼
EventSource('/api/dashboard/stream/?stepno=69')
    │
    │  后端根据 stepno 参数读不同的 Redis key
    │  cache.get('stats:realtime:69')
    ▼
返回工序 69 的数据 → 前端渲染
```

---

## 六、用户离开实时页面流程

```
用户切换到历史视图 / 关闭页面
    │
    │  onUnmounted 触发
    ▼
EventSource.close()
    │
    │  浏览器发送 HTTP 关闭信号
    ▼
Daphne 检测到客户端断开
    │
    │  dashboard_stream() 中的循环抛出异常
    │  或 StreamingHttpResponse 自动终止
    ▼
后端线程释放，连接关闭
```

---

## 七、Celery 定时任务（不变）

```
Celery Beat (每 60s)
    │
    │  sync_dashboard_stats()
    │  这部分逻辑完全不变
    ▼
get_batch_stats()               ← 6 线程并行查远程 DB
    │
    ▼
cache_batch_to_redis()          ← 写入 Redis（同步连接）
    │
    │  stats:realtime:{stepno}  ← SSE 视图从这里读
    │  stats:detail:*           ← SSE 视图从这里读
    ▼
完成（不再需要 group_send 推送）
```

---

## 八、SSE vs WebSocket 对比

| 维度 | WebSocket（变更前） | SSE（变更后） |
|------|---------------------|---------------|
| 连接方式 | 全双工持久连接 | 单向持久连接（服务端→客户端） |
| 客户端发消息 | 通过 WebSocket 发送 | 普通 HTTP POST |
| 断线重连 | 手动实现（setTimeout 3s） | 浏览器原生自动重连 |
| 服务端依赖 | Daphne + Channels + channels-redis + Redis 异步连接 | Daphne + Redis 同步连接（Django cache） |
| 已知问题 | Docker WSL2 下 Redis 异步连接超时 | 无（同步连接已验证正常） |
| 推送延迟 | 数据库写入后即时推送 | 最多 60s（与 Celery 采集周期一致，用户无感知） |

---

## 九、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 推送方式 | 定时推送（60s） | 数据源采集周期就是 60s，事件驱动增加复杂度但无体验提升 |
| set_targets | HTTP POST | 低频操作，60s 延迟可接受 |
| SSE 生命周期 | 仅实时页面保持 | 历史视图不需要实时数据 |
| 迁移方式 | 完全替换，删除 WebSocket 代码 | 干净利落，减少依赖 |

---

## 十、后端变更清单

### 10.1 新增 SSE 视图（`api_views.py`）

```python
@api_view(['GET'])
def dashboard_stream(request):
    """SSE 实时推送流（每 60s 从 Redis 读缓存推送给客户端）"""
    stepno_filter = _parse_stepno(request)

    def event_stream():
        while True:
            stats = get_realtime_stats(stepno_filter=stepno_filter)
            process_list = cache.get('stats:realtime:_process_list') or []
            detail_overview = cache.get('stats:detail:flow_overview') or []

            data = {
                'type': 'dashboard_update',
                'timestamp': datetime.now().isoformat(),
                'data': stats,
                'process_list': process_list,
                'detail_overview': detail_overview,
            }
            yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            time.sleep(60)

    return StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
```

### 10.2 新增目标产量设置视图（`api_views.py`）

```python
@api_view(['POST'])
def set_targets(request):
    """设置目标产量（HTTP POST 替代原 WebSocket 消息）"""
    flow = request.data.get('flow', '')
    targets = request.data.get('targets', {})
    today = date.today().isoformat()

    key = f'targets:{today}:{flow}'
    cache.set(key, json.dumps(targets), timeout=_seconds_to_midnight())
    return Response({'status': 'ok', 'flow': flow, 'count': len(targets)})
```

### 10.3 `tasks.py` 简化

删除 `group_send` 相关代码，只保留数据构建和缓存写入：

```python
@shared_task(bind=True, ...)
def sync_dashboard_stats(self):
    try:
        logger.info('开始批量构建看板统计数据')
        batch = get_batch_stats()
        cache_batch_to_redis(batch)

        detail_batch = get_batch_detail_stats()
        cache_detail_batch_to_redis(detail_batch)

        logger.success('统计数据已缓存（{} 个工序）', len(batch))
        return len(batch)
    except Exception as e:
        if _is_retryable(e):
            raise self.retry(exc=e)
        else:
            raise
```

### 10.4 `asgi.py` 简化

删除 WebSocket 路由，简化为纯 HTTP ASGI：

```python
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "iwork.settings")

from django.core.asgi import get_asgi_application

from iwork.logger_config import setup_logging
setup_logging('CHANNELS')

application = get_asgi_application()
```

### 10.5 `settings.py` 删除配置

```python
# 删除 CHANNEL_LAYERS 整块配置
# 删除 ASGI_APPLICATION 配置行
```

### 10.6 路由新增（`urls.py`）

```python
path('api/dashboard/stream/', api_views.dashboard_stream, name='dashboard_stream'),
path('api/dashboard/set-targets/', api_views.set_targets, name='set_targets'),
```

---

## 十一、前端变更清单（`dashboard.html`）

### 11.1 删除 WebSocket 相关代码

- 删除 `let socket = null;`
- 删除 `function connectWebSocket() { ... }` 整个函数
- 删除 `onUnmounted` 中 `socket.close()` 相关
- 删除 `wsConnected` / `wsStatus` 中 WebSocket 状态逻辑（或改为 SSE 状态）

### 11.2 新增 SSE 相关代码

```javascript
let eventSource = null;

function connectSSE() {
    const stepno = currentStepno.value || '';
    const url = stepno
        ? `/api/dashboard/stream/?stepno=${stepno}`
        : '/api/dashboard/stream/';

    eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
        if (isPaused.value) return;
        if (currentView.value !== 'realtime') return;

        const msg = JSON.parse(event.data);
        realtimeData.value = msg.data;
        processList.value = msg.process_list || [];
        detailOverview.value = msg.detail_overview || [];

        wsConnected.value = true;
        wsStatus.value = '已连接';
    };

    eventSource.onerror = () => {
        wsConnected.value = false;
        wsStatus.value = '连接断开，自动重连中...';
        // EventSource 自动重连，无需手动处理
    };
}

function switchStepno(stepno) {
    if (eventSource) eventSource.close();
    currentStepno.value = stepno;
    connectSSE();
}
```

### 11.3 生命周期钩子

```javascript
onMounted(() => {
    if (currentView.value === 'realtime') {
        connectSSE();
        loadRealtimeData();  // 首次立即加载
        loadProcessList();
    }
});

onUnmounted(() => {
    if (eventSource) eventSource.close();
    destroyAllCharts();
});
```

### 11.4 set_targets 改为 HTTP POST

```javascript
async function saveTargets(flow, targets) {
    const resp = await fetch('/api/dashboard/set-targets/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ flow, targets }),
    });
    if (resp.ok) {
        alert('保存成功');
    }
}
```

---

## 十二、依赖与清理

### 12.1 `requirements.txt` 变更

```diff
- channels>=4.0.0
- channels-redis>=4.0.0
# 保留以下
# redis>=5.0.0
# django-redis>=5.4.0
# daphne>=4.0.0
```

### 12.2 文件删除清单

| 文件 | 操作 |
|------|------|
| `iwork/consumers.py` | 删除 |
| `iwork/routing.py` | 删除 |

---

## 十三、错误处理

| 场景 | 处理方式 |
|------|----------|
| Redis 不可用 | SSE 视图中 `cache.get()` 返回 None，推送空数据 + 错误标记，前端显示"数据暂不可用" |
| 浏览器断开连接 | Daphne 自动检测，`StreamingHttpResponse` 终止，后端释放资源 |
| EventSource 断线 | 浏览器原生自动重连（默认间隔 3s），前端 `onerror` 更新状态提示 |
| Celery 任务失败 | `tasks.py` 保留重试逻辑（max_retries=3），SSE 读到的仍是上一次缓存数据 |
