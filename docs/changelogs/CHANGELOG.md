# 变更日志 (Changelog)

> 本文档记录 iwork（车间工效看板）的变更历史。
> 每次变更创建独立详情文件，按日期命名：`YYYY-MM-DD-简短描述.md`

## 变更时间线

| 日期 | 文件 | 范围 | 说明 |
|------|------|------|------|
| 2026-09-16 | [2026-09-16-myanmar-timezone-workday-shift.md](2026-09-16-myanmar-timezone-workday-shift.md) | 业务时区与作息 | 业务时区切换为缅甸 Asia/Yangon（UTC+6:30），作息改为 07:30-18:30 含两段休息，收工封顶 600 分钟 |
| 2026-08-13 | [2026-08-13-keycloak-application-authorization-closure.md](2026-08-13-keycloak-application-authorization-closure.md) | Portal+iwork 应用授权闭环 | 截至当日的 Keycloak Authorization Services、独立 Authorizer、Nginx 门禁、SSE 授权租约及本地验收历史快照 |
| 2026-07-16 | [2026-07-16-history-module-implementation-review.md](2026-07-16-history-module-implementation-review.md) | 历史模块详细实施回顾 | 本地聚合快照、历史生产详情、30天回填、性能、验证与运维总结 |
| 2026-07-16 | [2026-07-16-production-detail-field-audit.md](2026-07-16-production-detail-field-audit.md) | 生产详情字段核对 | SO5-L5C 与按产品名称字段来源、产值、效率和人工核对方法 |
| 2026-07-15 | [2026-07-15-product-step-metadata-output-value.md](2026-07-15-product-step-metadata-output-value.md) | 生产详情产品/Flow 明细 | 组合键工序元数据、产值、图表切换及员工实时效率 |
| 2026-07-09 | [2026-07-09-tag-drag-placeholder-tree-wrap.md](2026-07-09-tag-drag-placeholder-tree-wrap.md) | 生产明细数据页 | 激活区拖拽改为占位虚线框挤压 + 树形表格外框先过渡再淡入 |

## 文档约定

- 每个变更日志文件包含：变更概览 → 详情 → 验证结果
- 文件名格式：`YYYY-MM-DD-<简短描述>.md`
- 提交信息格式：`[YYYY-MM-DD][TYPE] 描述`（TYPE: FEAT/FIX/DOCS/REFACTOR/STYLE/PERF/CHORE）
