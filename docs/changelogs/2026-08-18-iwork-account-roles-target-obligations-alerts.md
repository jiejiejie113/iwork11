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
- 全局账号/组长清单、未填与逾期责任摘要，以及指定账号的Flow和责任明细。
- Keycloak账号状态只读，不提供账号创建、删除、改密或启停。

页面查询失败时会清空上一次账号结果，默认日期使用浏览器本地日期。
Flow写入由Portal先复验`/apps/iwork`并覆盖浏览器subject，iwork再调用Portal的
`access_only=1`轻量查询复验一次，因此管理员绕过Portal写代理直调iwork也不能
为无应用访问权账号分配Flow。内部HTTP固定地址、禁止重定向且不记录Cookie。

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
- Portal全局账号/组长汇总、服务端Flow双重复验和失败结果清理。
- 实时数据、生产详情、历史数据、既有SSE回归。
- Django/pytest全量测试、Ruff、JavaScript语法、Compose解析、Nginx配置和`git diff --check`。

提交前最终全量结果为：iwork `516 passed`；Portal `90 passed, 2 skipped`。

### 2026-08-18本地Docker实机验收

- `DKT_iwork`和`DKT_iwork_alert_worker`已使用本轮镜像重建，均为运行状态且重启次数为0；alert worker健康检查通过，并且只监听独立`alerts`队列。
- iwork迁移`0009_identity_target_responsibility`和`0010_alerts`均已应用；实时快照成功发布，内部HTTP入口返回200。
- Portal、Authorizer和oauth2-proxy已重建，Keycloak保持原数据库与卷；授权资源同步结果为6个资源、7个策略和6个权限。
- Nginx配置检查通过并完成平滑重载；运行配置确认先清空浏览器传入的`Remote-Subject`，再注入Authorizer返回的可信subject。
- Portal、iwork和管理页的匿名访问均返回302，并跳转到本地`http://192.168.30.190:8080/realms/dkt`；OIDC discovery返回200，issuer严格等于本地Realm地址；退出链路回到本地Keycloak。
- 浏览器已实际到达本地Keycloak登录页。当前验收浏览器没有登录会话，因此未伪造Cookie或账号；管理员、组长和普通用户的真实交互矩阵仍需使用真实测试账号登录后补验，自动化测试已覆盖对应权限分支。

首次Portal重建时发现Keycloak数据卷的导入目录残留一个2026-06-16生成的0字节`dkt-realm.json`，导致Keycloak报`No content to map due to end-of-input`并重启。处置时只停止本地Keycloak、删除已核实为空的历史导入文件并重新启动；没有删除或重建数据库、卷或Realm。恢复后Keycloak健康且重启次数为0，完整联合重建与连通性检查通过。

非阻断既有警告：Celery worker当前仍以root运行；Nginx仍提示DSM配置存在重复`text/html` MIME声明和代理Header哈希尺寸非最优。本轮未扩大范围修改这些历史配置。

## 部署与回滚

本地使用Portal联合重建脚本重建Portal、Authorizer、Nginx、iwork和alert worker。不删除或重建MySQL、Redis、PostgreSQL、Keycloak数据库或任何物理卷。回滚时恢复两个仓库对应提交并重新构建无状态容器，保留新增本地表中的审计和通知历史。
