# ADR 001: 使用 SSE 替代 WebSocket

> 日期：2026-06 | 状态：已实施，2026-07-14 复核

## 决策

实时看板使用 Server-Sent Events（SSE）单向推送，不再使用 Django Channels 或 WebSocket。目标产量等客户端写操作使用普通 HTTP POST。

## 原因

- 当前业务只需要服务器向浏览器推送统计结果；
- SSE 基于 HTTP，浏览器原生支持自动重连；
- Nginx 只需关闭代理缓冲并设置足够的读取超时；
- 删除 Channels、channels-redis、消费者和 WebSocket 路由后，部署与故障面更小。

## 当前实现

- Uvicorn 运行 Django ASGI 应用；
- `api_views.dashboard_stream()` 返回 `StreamingHttpResponse`；
- 浏览器使用 `EventSource` 连接 `/api/dashboard/stream/`；
- Celery 定时刷新 Redis，SSE 视图从缓存读取并推送；
- Nginx 对 `/iwork/` 设置 `proxy_buffering off`。

`consumers.py`、`routing.py`、`/ws/`、Daphne 和 Channels 配置均不属于当前架构。历史迁移设计稿仅用于说明决策过程。
