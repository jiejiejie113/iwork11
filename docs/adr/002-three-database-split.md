# ADR-002: 三数据库分离架构

**状态**: 已采纳 (2026-04)
**决策**: 使用三个独立数据库——default（远程只读）、iwork（本地可写）、iwork_local（本地独立）
**原因**: 生产数据库不可写（安全隔离）、本地缓存提高性能、iwork_local 存放独立业务数据
**影响**: 需配置 DATABASE_ROUTERS、每个 QuerySet 显式 using()
