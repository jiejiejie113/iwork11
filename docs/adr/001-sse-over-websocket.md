# ADR-001: SSE 替代 WebSocket

**状态**: 已采纳 (2026-06)
**决策**: 使用 Server-Sent Events (SSE) 而非 WebSocket 实现实时数据推送
**原因**: SSE 更简单（HTTP 原生支持）、Nginx 代理无需特殊配置（仅需 proxy_buffering off）、自动重连
**影响**: 删除 consumers.py（Django Channels WebSocket），改用 Django StreamingHttpResponse
