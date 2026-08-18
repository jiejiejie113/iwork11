# iwork账号职能、目标责任与站内警报

## 背景

iwork此前只依赖Portal判断应用访问权，应用内部没有稳定的Keycloak subject、生产组负责人关系、每日目标责任快照和个人通知中心。目标写入也无法可靠回答“谁在何时修改了哪个生产组”，管理员无法统一查看逾期未填目标。

本次只在本地Portal与iwork实现账号职能闭环，不推送远程或部署服务器。

## 身份与安全边界

- Authorizer从已验证Access Token提取subject，并通过Nginx注入`Remote-Subject`。
- Nginx先清空浏览器提交的全部`Remote-*`身份头。
- iwork只接受配置的`DKT_kc_nginx`解析地址和本机回环请求，不再信任整个RFC1918共享网络。
- Portal聚合iwork数据时携带浏览器会话访问固定内部Nginx入口，由Authorizer再次认证；Portal不自行签发管理员头。
- Keycloak严格查询明确区分账号不存在404与上游故障503。

## 账号职能与目标责任

- `IworkPrincipal`保存subject及展示属性快照，不保存密码或Keycloak管理密钥。
- `ManagedFlowAssignment`支持一个账号管理多个Flow、一个Flow配置多个组长。
- `DailyTargetObligation`和负责人快照固化每日截止时间与责任人，状态为`pending / fulfilled / overdue / fulfilled_late / waived`。
- 管理员可修改全部Flow；组长只能修改当前业务日且有效分配给自己的Flow；普通用户和缺少subject的请求被拒绝。
- 0目标是有效填报；目标、责任状态和审计日志在同一数据库事务中提交。
- 旧员工/工单目标格式仅管理员可用，先完整校验后事务保存，0值会覆盖旧值。
- 修改或撤销最后一名组长时，截止前未完成责任标记为`waived`；截止后保留逾期事实。

## Portal管理页

`/management/iwork-accounts/`提供：

- Keycloak账号启用状态、管理员状态和iwork访问权。
- 显式分开的“授予/撤销iwork访问权”和“分配/移除Flow”操作。
- 当前账号的Flow分配与所选日期目标责任。
- Keycloak账号状态只读，不提供账号创建、删除、改密或启停。

页面查询失败时会清空上一次账号结果，默认日期使用浏览器本地日期。

## 警报与站内通知

- 新增检测器、评估服务和通知渠道协议；测试检测器覆盖快照到事件、受众和投递的完整链路。
- 首版启用`target_submission_overdue`，水位异常规则保留但默认禁用。
- 事件、评估运行和投递均有唯一约束；投递使用`select_for_update(skip_locked=True)`与五分钟领取租约，避免多Worker重复发布。
- 订阅读取和事件可见性会重新校验当前角色及有效Flow，撤销负责人后旧订阅立即失效。
- SSE只发送`notification_changed`，每客户端队列容量为1，租约60秒；最后一个客户端断开后释放Redis监听任务。
- 警报任务使用独立`alerts`队列和`DKT_iwork_alert_worker`，故障不阻塞实时快照发布。

## 本地验收范围

- 身份头防伪造、管理员/组长/普通用户目标权限。
- 多组长、0目标、截止边界、逾期补填、负责人修改和责任免除。
- 订阅范围撤权、通知隔离、50个并发SSE连接和60秒租约。
- 重复评估与重复投递幂等。
- Portal账号管理、Keycloak 404/503、内部Nginx二次认证。
- 实时数据、生产详情、历史数据、既有SSE回归。
- Django/pytest全量测试、Ruff、JavaScript语法、Compose解析、Nginx配置和`git diff --check`。

## 部署与回滚

本地使用Portal联合重建脚本重建Portal、Authorizer、Nginx、iwork和alert worker。不删除或重建MySQL、Redis、PostgreSQL、Keycloak数据库或任何物理卷。回滚时恢复两个仓库对应提交并重新构建无状态容器，保留新增本地表中的审计和通知历史。
