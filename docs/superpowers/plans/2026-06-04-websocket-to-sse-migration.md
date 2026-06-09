# WebSocket → SSE 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将实时看板从 WebSocket（Django Channels）迁移到 SSE（Server-Sent Events），消除 Docker WSL2 下 Redis 异步连接超时问题。

**Architecture:** 删除 Django Channels 全套组件（consumers、routing、Channel Layer），新增 SSE 视图通过 `StreamingHttpResponse` 每 60s 从 Redis 同步读取缓存推送给前端。前端 `WebSocket` 替换为 `EventSource`。目标产量设置改为 HTTP POST。

**Tech Stack:** Django StreamingHttpResponse、EventSource API、Redis（Django cache 同步连接）

**设计文档:** `docs/开发文档/SSE迁移数据流设计.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `iwork/api_views.py` | 修改 | 新增 `dashboard_stream` SSE 视图 + `set_targets` HTTP 视图 |
| `iwork/urls.py` | 修改 | 新增 2 条路由 |
| `iwork/tasks.py` | 修改 | 删除 WebSocket group_send 推送代码 |
| `iwork/asgi.py` | 修改 | 删除 WebSocket 路由，简化为纯 HTTP |
| `iwork/settings.py` | 修改 | 删除 `CHANNEL_LAYERS` 和 `ASGI_APPLICATION` 配置 |
| `iwork/consumers.py` | 删除 | WebSocket 消费者 |
| `iwork/routing.py` | 删除 | WebSocket 路由 |
| `iwork/templates/iwork/dashboard.html` | 修改 | WebSocket → EventSource |
| `requirements.txt` | 修改 | 移除 channels、channels-redis |
| `tests/test_api_views.py` | 修改 | 新增 SSE 和 set_targets 测试 |
| `tests/test_consumers.py` | 删除 | WebSocket 测试 |
| `tests/test_tasks.py` | 修改 | 删除 WebSocket 推送相关测试断言 |

---

### Task 1: 新增 SSE 视图和 set_targets 视图

**Files:**
- Modify: `iwork/api_views.py`
- Test: `tests/test_api_views.py`

- [ ] **Step 1: 编写 SSE 视图测试**

在 `tests/test_api_views.py` 末尾新增：

```python
import time
from django.http import StreamingHttpResponse


class TestDashboardStream:
    """dashboard_stream SSE 视图测试"""

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.get_realtime_stats')
    def test_returns_event_stream_content_type(self, mock_stats, mock_cache):
        """SSE 视图返回 text/event-stream Content-Type"""
        from iwork.api_views import dashboard_stream

        mock_stats.return_value = {'total_qty': 100}
        mock_cache.get.return_value = []

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/')

        # 用 mock 替换 sleep 避免阻塞
        with patch('iwork.api_views.time.sleep', side_effect=InterruptedError):
            try:
                response = dashboard_stream(request)
            except InterruptedError:
                pass

        assert response['Content-Type'] == 'text/event-stream'
        assert response['Cache-Control'] == 'no-cache'

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.get_realtime_stats')
    def test_sse_yields_valid_json(self, mock_stats, mock_cache):
        """SSE 输出包含有效的 JSON 数据"""
        from iwork.api_views import dashboard_stream

        mock_stats.return_value = {'total_qty': 500, 'date': '2026-06-04'}
        mock_cache.get.side_effect = lambda key: {
            'stats:realtime:_process_list': [70, 69],
            'stats:detail:flow_overview': [{'flow': 'VCO-L5', 'qty': 200}],
        }.get(key, None)

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/')

        with patch('iwork.api_views.time.sleep', side_effect=InterruptedError):
            try:
                response = dashboard_stream(request)
            except InterruptedError:
                pass

        # 读取第一个 chunk
        chunks = list(response.streaming_content)
        assert len(chunks) >= 1

        first_chunk = chunks[0].decode('utf-8')
        assert first_chunk.startswith('data: ')
        assert first_chunk.endswith('\n\n')

        json_str = first_chunk[6:-2]  # 去掉 "data: " 和 "\n\n"
        data = json.loads(json_str)
        assert data['type'] == 'dashboard_update'
        assert 'timestamp' in data
        assert data['data']['total_qty'] == 500

    @patch('iwork.api_views.cache')
    @patch('iwork.api_views.get_realtime_stats')
    def test_sse_respects_stepno_filter(self, mock_stats, mock_cache):
        """SSE 视图支持 stepno 参数过滤"""
        from iwork.api_views import dashboard_stream

        mock_stats.return_value = {'total_qty': 300}
        mock_cache.get.return_value = []

        factory = APIRequestFactory()
        request = factory.get('/api/dashboard/stream/?stepno=69')

        with patch('iwork.api_views.time.sleep', side_effect=InterruptedError):
            try:
                response = dashboard_stream(request)
            except InterruptedError:
                pass

        mock_stats.assert_called_once_with(stepno_filter=[69])
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
pytest tests/test_api_views.py::TestDashboardStream -v
```

预期：FAIL（`dashboard_stream` 不存在）

- [ ] **Step 3: 实现 SSE 视图**

在 `iwork/api_views.py` 顶部新增 import：

```python
from datetime import datetime
from django.http import StreamingHttpResponse
```

在文件末尾新增：

```python
@api_view(['GET'])
def dashboard_stream(request):
    """
    SSE 实时推送流（每 60s 从 Redis 读缓存推送给客户端）

    支持参数：
        ?stepno=70    过滤工序号（可选）
    """
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

- [ ] **Step 4: 运行测试确认通过**

```powershell
pytest tests/test_api_views.py::TestDashboardStream -v
```

预期：3 个 PASS

- [ ] **Step 5: 编写 set_targets 视图测试**

在 `tests/test_api_views.py` 末尾新增：

```python
class TestSetTargets:
    """set_targets HTTP POST 视图测试"""

    @patch('iwork.api_views.cache')
    def test_set_targets_success(self, mock_cache):
        """POST 成功写入 Redis 并返回 200"""
        from iwork.api_views import set_targets

        mock_cache.set = MagicMock()

        factory = APIRequestFactory()
        request = factory.post(
            '/api/dashboard/set-targets/',
            data={'flow': 'VCO-L5', 'targets': {'1001': 100, '1002': 150}},
            format='json',
        )

        response = set_targets(request)
        assert response.status_code == 200
        assert response.data['status'] == 'ok'
        assert response.data['flow'] == 'VCO-L5'
        assert response.data['count'] == 2
        mock_cache.set.assert_called_once()

    @patch('iwork.api_views.cache')
    def test_set_targets_empty(self, mock_cache):
        """空 targets 也能正常处理"""
        from iwork.api_views import set_targets

        factory = APIRequestFactory()
        request = factory.post(
            '/api/dashboard/set-targets/',
            data={'flow': 'VCO-L5', 'targets': {}},
            format='json',
        )

        response = set_targets(request)
        assert response.status_code == 200
        assert response.data['count'] == 0
```

- [ ] **Step 6: 运行测试确认失败**

```powershell
pytest tests/test_api_views.py::TestSetTargets -v
```

预期：FAIL（`set_targets` 不存在）

- [ ] **Step 7: 实现 set_targets 视图**

在 `iwork/api_views.py` 末尾新增：

```python
@api_view(['POST'])
def set_targets(request):
    """
    设置目标产量（HTTP POST 替代原 WebSocket 消息）

    请求体：
        flow (str): Flow 名称
        targets (dict): {reg_per_sys_id: target_qty}
    """
    flow = request.data.get('flow', '')
    targets = request.data.get('targets', {})
    today = date.today().isoformat()

    key = f'targets:{today}:{flow}'
    cache.set(key, json.dumps(targets), timeout=_seconds_to_midnight())
    return Response({'status': 'ok', 'flow': flow, 'count': len(targets)})
```

需要在 `api_views.py` 顶部导入 `_seconds_to_midnight`：

```python
from iwork.statistics import get_realtime_stats, _seconds_to_midnight
```

- [ ] **Step 8: 运行测试确认通过**

```powershell
pytest tests/test_api_views.py::TestSetTargets -v
```

预期：2 个 PASS

- [ ] **Step 9: 运行全部 api_views 测试确认无回归**

```powershell
pytest tests/test_api_views.py -v
```

预期：全部 PASS

- [ ] **Step 10: 提交**

```powershell
git add iwork/api_views.py tests/test_api_views.py
git commit -m "[2026-06-04][FEAT] 新增 SSE 推送视图和目标产量设置 API"
```

---

### Task 2: 新增路由

**Files:**
- Modify: `iwork/urls.py`

- [ ] **Step 1: 添加 SSE 和 set_targets 路由**

在 `iwork/urls.py` 的 `urlpatterns` 中，在生产详情 API 之前新增：

```python
    # SSE 实时推送 + 目标产量设置
    path("api/dashboard/stream/", api_views.dashboard_stream, name="dashboard-stream"),
    path("api/dashboard/set-targets/", api_views.set_targets, name="set-targets"),
```

- [ ] **Step 2: 验证 Django 能正常启动**

```powershell
python manage.py check
```

预期：System check identified no issues

- [ ] **Step 3: 提交**

```powershell
git add iwork/urls.py
git commit -m "[2026-06-04][FEAT] 新增 SSE stream 和 set-targets 路由"
```

---

### Task 3: 简化 tasks.py — 删除 WebSocket 推送代码

**Files:**
- Modify: `iwork/tasks.py`
- Modify: `tests/test_tasks.py`

- [ ] **Step 1: 修改 tasks.py**

删除 `sync_dashboard_stats` 中 WebSocket 推送相关代码。修改后的函数：

```python
@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    task_time_limit=120,
    task_soft_time_limit=90,
)
def sync_dashboard_stats(self):
    """每 60s：批量构建所有工序数据 → 写入 Redis"""
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
            logger.warning('批量构建任务遇到瞬时故障，将重试 (attempt {}): {}', self.request.retries + 1, e)
            raise self.retry(exc=e)
        else:
            logger.error('批量构建任务失败（不可重试）: {}', e)
            raise
```

同时删除顶部不再需要的 import：

```python
# 删除这两行
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
```

- [ ] **Step 2: 更新 test_tasks.py**

删除所有 `@patch('iwork.tasks.get_channel_layer')` 装饰器和相关断言。删除 `mock_channel` 相关代码。删除 `test_task_pushes_stepno_70_by_default`、`test_task_fallback_to_all_when_70_missing`、`test_task_succeeds_when_channel_layer_none` 测试（这些测试 WebSocket 推送逻辑，不再适用）。

修改后的 `test_tasks.py`：

```python
import pytest
from unittest.mock import patch
from datetime import date


class TestSyncDashboardStats:
    """sync_dashboard_stats Celery 任务测试"""

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_success(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """任务成功执行：批量构建 → 缓存"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch = {
            70: {'total_qty': 500, 'date': date(2026, 5, 9)},
            'all': {'total_qty': 500, 'date': date(2026, 5, 9)},
        }
        mock_batch_fn.return_value = mock_batch
        mock_detail_batch.return_value = {}

        result = sync_dashboard_stats()

        mock_batch_fn.assert_called_once()
        mock_cache.assert_called_once_with(mock_batch)
        mock_detail_batch.assert_called_once()
        mock_detail_cache.assert_called_once_with({})
        assert result == 2

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_returns_batch_count(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """任务返回工序数量"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch = {
            70: {'total_qty': 500, 'date': date(2026, 5, 9)},
            69: {'total_qty': 300, 'date': date(2026, 5, 9)},
            68: {'total_qty': 200, 'date': date(2026, 5, 9)},
            'all': {'total_qty': 1000, 'date': date(2026, 5, 9)},
        }
        mock_batch_fn.return_value = mock_batch
        mock_detail_batch.return_value = {}

        result = sync_dashboard_stats()
        assert result == 4

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_retries_on_exception(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """batch 构建失败时触发重试"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch_fn.side_effect = Exception('DB down')

        with pytest.raises(Exception):
            sync_dashboard_stats()

    @patch('iwork.tasks.cache_detail_batch_to_redis')
    @patch('iwork.tasks.get_batch_detail_stats')
    @patch('iwork.tasks.cache_batch_to_redis')
    @patch('iwork.tasks.get_batch_stats')
    def test_task_calls_detail_batch_functions(self, mock_batch_fn, mock_cache, mock_detail_batch, mock_detail_cache):
        """sync_dashboard_stats 调用详情批量函数"""
        from iwork.tasks import sync_dashboard_stats

        mock_batch_fn.return_value = {70: {'total_qty': 500}, 'all': {'total_qty': 500}}
        mock_detail_batch.return_value = {'flow_overview': {}, 'flow_hourly': {}}

        sync_dashboard_stats()

        mock_detail_batch.assert_called_once()
        mock_detail_cache.assert_called_once_with(mock_detail_batch.return_value)
```

- [ ] **Step 3: 运行测试确认通过**

```powershell
pytest tests/test_tasks.py -v
```

预期：4 个 PASS

- [ ] **Step 4: 提交**

```powershell
git add iwork/tasks.py tests/test_tasks.py
git commit -m "[2026-06-04][REFACTOR] tasks.py 删除 WebSocket 推送代码"
```

---

### Task 4: 简化 asgi.py — 删除 WebSocket 路由

**Files:**
- Modify: `iwork/asgi.py`

- [ ] **Step 1: 重写 asgi.py**

```python
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "iwork.settings")

from django.core.asgi import get_asgi_application

# Channels/ASGI 进程接入统一日志
from iwork.logger_config import setup_logging
setup_logging('CHANNELS')

application = get_asgi_application()
```

- [ ] **Step 2: 验证 Django 能正常启动**

```powershell
python manage.py check
```

预期：System check identified no issues

- [ ] **Step 3: 提交**

```powershell
git add iwork/asgi.py
git commit -m "[2026-06-04][REFACTOR] asgi.py 删除 WebSocket 路由，简化为纯 HTTP"
```

---

### Task 5: 删除 settings.py 中 Channel Layer 配置

**Files:**
- Modify: `iwork/settings.py`

- [ ] **Step 1: 删除配置**

删除 `settings.py` 中以下配置块：

```python
# 删除这整块（约第 168-178 行）
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

- [ ] **Step 2: 验证 Django 能正常启动**

```powershell
python manage.py check
```

预期：System check identified no issues

- [ ] **Step 3: 提交**

```powershell
git add iwork/settings.py
git commit -m "[2026-06-04][REFACTOR] 删除 CHANNEL_LAYERS 和 ASGI_APPLICATION 配置"
```

---

### Task 6: 更新前端 — WebSocket 替换为 EventSource

**Files:**
- Modify: `iwork/templates/iwork/dashboard.html`

- [ ] **Step 1: 定位并替换 WebSocket 代码**

在 `dashboard.html` 中找到 WebSocket 相关代码块（约第 624-635 行），替换为：

```javascript
        // ---- SSE 实时推送 ----
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

                try {
                    const msg = JSON.parse(event.data);
                    // 更新实时数据
                    if (msg.data) {
                        Object.assign(realtimeData.value, msg.data);
                    }
                    if (msg.process_list) {
                        processList.value = msg.process_list;
                    }
                    if (msg.detail_overview) {
                        detailOverview.value = msg.detail_overview;
                    }
                    wsConnected.value = true;
                    wsStatus.value = '已连接';
                } catch (e) {
                    console.error('SSE 数据解析失败:', e);
                }
            };

            eventSource.onerror = () => {
                wsConnected.value = false;
                wsStatus.value = '连接断开，自动重连中...';
                // EventSource 浏览器自动重连，无需手动处理
            };
        }
```

- [ ] **Step 2: 替换生命周期钩子**

找到 `onMounted` 中调用 `connectWebSocket()` 的地方，替换为 `connectSSE()`：

```javascript
        onMounted(() => {
            if (currentView.value === 'realtime') {
                connectSSE();           // 原来是 connectWebSocket()
                loadRealtimeData();
                loadProcessList();
            } else {
                // 历史视图逻辑不变
            }
        });
```

找到 `onUnmounted` 中 `socket.close()` 的地方，替换为：

```javascript
        onUnmounted(() => {
            if (eventSource) eventSource.close();
            destroyAllCharts();
        });
```

- [ ] **Step 3: 替换 set_targets 发送方式**

找到通过 WebSocket 发送 `set_targets` 消息的代码，替换为 HTTP POST：

```javascript
        async function saveTargets(flow, targets) {
            try {
                const resp = await fetch('/api/dashboard/set-targets/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken'),
                    },
                    body: JSON.stringify({ flow, targets }),
                });
                if (resp.ok) {
                    const result = await resp.json();
                    console.log('目标产量已保存:', result);
                } else {
                    console.error('保存失败:', resp.status);
                }
            } catch (e) {
                console.error('保存失败:', e);
            }
        }
```

> 注：`getCookie` 函数如果不存在，需要新增：
> ```javascript
> function getCookie(name) {
>     const value = `; ${document.cookie}`;
>     const parts = value.split(`; ${name}=`);
>     if (parts.length === 2) return parts.pop().split(';').shift();
> }
> ```

- [ ] **Step 4: 手动验证**

启动开发服务器，打开实时看板页面，确认：
1. 页面正常加载
2. SSE 连接状态显示"已连接"
3. 数据每 60s 自动更新
4. 切换工序后数据正确更新
5. 浏览器控制台无错误

- [ ] **Step 5: 提交**

```powershell
git add iwork/templates/iwork/dashboard.html
git commit -m "[2026-06-04][FEAT] 前端 WebSocket 替换为 EventSource (SSE)"
```

---

### Task 7: 删除 WebSocket 相关文件和测试

**Files:**
- Delete: `iwork/consumers.py`
- Delete: `iwork/routing.py`
- Delete: `tests/test_consumers.py`

- [ ] **Step 1: 确认无其他文件引用 consumers.py 和 routing.py**

```powershell
# 检查 consumers.py 引用
Select-String -Path "iwork\*.py" -Pattern "consumers" | Where-Object { $_.Filename -ne "consumers.py" }

# 检查 routing.py 引用
Select-String -Path "iwork\*.py" -Pattern "routing" | Where-Object { $_.Filename -ne "routing.py" }
```

预期：无引用（asgi.py 中的引用已在 Task 4 删除）

- [ ] **Step 2: 删除文件**

```powershell
Remove-Item iwork\consumers.py
Remove-Item iwork\routing.py
Remove-Item tests\test_consumers.py
```

- [ ] **Step 3: 运行全部测试确认无回归**

```powershell
pytest tests/ -v
```

预期：全部 PASS（test_consumers.py 已删除，不会被执行）

- [ ] **Step 4: 提交**

```powershell
git add -A iwork/consumers.py iwork/routing.py tests/test_consumers.py
git commit -m "[2026-06-04][REFACTOR] 删除 consumers.py、routing.py 及其测试"
```

---

### Task 8: 更新依赖 — 移除 channels 和 channels-redis

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 从 requirements.txt 移除**

删除以下两行：

```
channels>=4.0.0
channels-redis>=4.0.0
```

- [ ] **Step 2: 验证 pip 安装正常**

```powershell
pip install -r requirements.txt --quiet
```

预期：无错误

- [ ] **Step 3: 验证 Django 启动正常**

```powershell
python manage.py check
```

预期：System check identified no issues

- [ ] **Step 4: 提交**

```powershell
git add requirements.txt
git commit -m "[2026-06-04][CHORE] 移除 channels 和 channels-redis 依赖"
```

---

### Task 9: 最终验证

- [ ] **Step 1: 运行全部测试**

```powershell
pytest tests/ -v
```

预期：全部 PASS

- [ ] **Step 2: 启动服务手动验证**

```powershell
# 启动 Redis
docker start redis-iwork

# 启动 Celery Worker
celery -A iwork worker -l info -P solo

# 启动 Celery Beat
celery -A iwork beat -l info

# 启动 Daphne
daphne -b 0.0.0.0 -p 8000 iwork.asgi:application
```

打开 `http://localhost:8000/`，确认：
1. 实时看板正常加载
2. SSE 连接状态显示"已连接"
3. 数据每 60s 自动更新
4. 无 WebSocket 相关错误
5. 浏览器 Network 面板中 `/api/dashboard/stream/` 请求状态为 `200`，Type 为 `eventsource`

- [ ] **Step 3: 最终提交（如有遗漏修复）**

```powershell
git add -A
git commit -m "[2026-06-04][FEAT] WebSocket → SSE 迁移完成"
```
