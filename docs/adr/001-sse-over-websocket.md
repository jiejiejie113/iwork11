# ADR 001: 使用 SSE 替代 WebSocket

> 日期：2026-06 | 状态：已实施，2026-08-07 复核

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
- Celery 完整发布快照并切换 `current` 后，通过原生 Redis Pub/Sub 发布轻量版本通知；
- 每个 Uvicorn Worker 只维护一个 Redis 异步订阅，并在进程内广播给 SSE 连接；
- 同日期、同工序的客户端共享一次 Redis 读取和 JSON 序列化；
- 每客户端只保留一个最新通知，慢客户端自动丢弃被新版本替代的旧通知；
- Pub/Sub 只承担即时唤醒，60 秒共享版本核对负责补偿丢失消息；
- Nginx 对 `/iwork/` 设置 `proxy_buffering off`。

`consumers.py`、`routing.py`、`/ws/`、Daphne 和 Channels 配置均不属于当前架构。历史迁移设计稿仅用于说明决策过程。

## 2026-08-07 并发复核

本次没有重新引入 Django Channels。原生 `redis.asyncio` 只作为 Web Worker 内部的
快照版本通知通道，浏览器协议仍为标准 SSE，写操作仍为普通 HTTP。这样保留了
单向推送的简单故障面，同时消除每个浏览器各自等待 60 秒轮询水位的问题。

通知消息禁止携带业务负载，只允许包含协议版本、业务日期和快照版本。通知失败不得
回滚已经发布的 `current`，也不得触发完整远程数据库采集重试；SSE 的周期核对会从
当前完整快照恢复。
