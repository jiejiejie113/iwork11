# ADR-003: Remote-User 认证模式

**状态**: 已采纳 (2026-06)
**决策**: 放弃应用内认证，完全依赖 Portal 通过 oauth2-proxy + Keycloak 注入 Remote-User header
**原因**: 统一认证入口、用户无需额外登录、安全边界由 Portal 管控
**影响**: 需 TrustedProxyMiddleware 仅信任 Docker 内网 IP、用户账号由 Keycloak 管理
