# 2026-08-13 Portal+iwork 应用授权闭环实施与验收记录（历史快照）

## 1. 文档目的

本文记录截至2026-08-13的 Portal+iwork 应用级授权闭环历史快照，包括方案设计、本地实施、真实链路验收、问题修复和当时的收口状态，作为后续推送远程、服务器部署、故障排查和权限审计的依据。文中的测试数量、分支领先数和容器状态均为当日验收记录，不代表当前工作区状态。

本轮工作的核心目标是解决以下安全缺口：Keycloak Group 原先只控制 Portal 首页是否显示应用卡片，但用户即使没有对应应用 Group，仍可直接输入 `/iwork/` 等应用地址访问后端。也就是说，原有 Group 只提供“导航可见性”，并没有形成真正的应用入口访问控制。

本轮最终实现了以下闭环：

- Keycloak Authorization Services 负责应用资源、Group Policy 和访问 Permission。
- 独立 Authorizer 容器负责身份确认和 UMA 权限决策。
- Nginx 在每个子应用入口强制执行授权子请求。
- 页面、API和授权系统故障分别返回明确的403或503响应。
- iwork SSE连接通过60秒授权租约周期性重新经过入口授权。
- Portal首页卡片过滤继续保留，但不再承担安全边界职责。

## 2. 实施范围和边界

### 2.1 本轮修改仓库

| 仓库 | 本地路径 | 分支 | 修改范围 |
|---|---|---|---|
| Portal/认证入口 | `C:\Users\lipengfei\ZCodeProject\DTD_nginx` | `feature/keycloak-migration` | Keycloak授权资源、Authorizer、Nginx门禁、错误页面、oauth2-proxy配置、重建流程和文档 |
| iwork | `C:\Users\lipengfei\ZCodeProject\iwork` | `Keycloak` | SSE连接授权租约、配置、测试和规范手册 |

### 2.2 明确未执行的操作

- 未推送GitHub或其他远程仓库。
- 未连接、拉取或部署服务器 `192.168.0.97`。
- 未修改DSM、Fabric、Pattern和DesignProgress业务仓库。
- 未关闭DSM的8002端口。
- 未删除、重建或重新导入Keycloak、PostgreSQL、MySQL、Redis数据卷。
- 未修改现有真实用户的Group关系。
- 未读取、输出或提交中央密钥文件 `dkt-secrets.env`。
- 未提交iwork工作区中的 `.reasonix/`。

本轮只在本地Docker环境完成代码实施与真实授权验收。后续生产部署必须单独进行服务器基线检查、配置同步、重建和回滚准备。

## 3. 修改前后的授权模型

### 3.1 修改前

修改前的访问链路为：

```text
浏览器
  → Nginx
  → oauth2-proxy检查是否已经登录
  → 已登录即转发至iwork等子应用
```

Keycloak `/apps/{slug}` Group 只影响Portal首页的应用卡片显示：

| 用户状态 | Portal卡片 | 直接访问应用地址 |
|---|---:|---:|
| 属于 `/apps/iwork` | 显示 | 允许 |
| 不属于 `/apps/iwork` | 隐藏 | 仍然允许 |

主要问题是“隐藏卡片”不能替代服务端授权。只要用户已经通过统一登录，输入或收藏应用URL便可以绕过首页限制。

### 3.2 修改后

修改后的页面访问链路为：

```text
浏览器请求 /iwork/
  → Nginx固定映射应用slug=iwork
  → auth_request调用独立Authorizer
  → Authorizer携带浏览器Cookie调用oauth2-proxy确认身份
  → oauth2-proxy返回用户Access Token和身份Header
  → Authorizer向Keycloak Authorization Services申请
    app:iwork#access 的UMA decision
  → 允许：Nginx将既有Remote-*身份Header传给iwork
  → 拒绝：返回统一HTML 403或JSON 403
  → 授权依赖故障：严格返回HTML/JSON 503
```

最终权限判断规则为：

```text
属于 /apps/{slug}  OR  属于 /admin  → 允许访问该应用
其他已登录用户                         → 拒绝访问
```

应用slug由生成后的Nginx配置固定，不接受浏览器自定义Header，因此用户不能通过伪造请求参数选择其他应用权限。

### 3.3 修改后的授权职责

| 组件 | 职责 | 是否为安全边界 |
|---|---|---:|
| Portal首页卡片过滤 | 改善用户导航体验，只展示有权访问的应用 | 否 |
| oauth2-proxy | 确认用户已经登录并取得Access Token | 是，身份认证边界 |
| Keycloak Authorization Services | 根据实时Realm Group关系判断应用权限 | 是，权限决策边界 |
| Authorizer | 编排身份确认、UMA决策、短期缓存和严格失败语义 | 是，应用授权执行点 |
| Nginx `auth_request` | 每个应用入口强制执行授权，阻止绕过 | 是，入口门禁 |
| iwork | 接收Nginx确认后的Remote-*身份，处理业务请求 | 不是本次应用权限决策点 |

## 4. Keycloak Authorization Services配置

本轮新增幂等管理命令：

```powershell
python manage.py sync_application_authorization
```

命令在Keycloak 26.6.3中创建或更新以下对象：

| 类型 | 名称或数量 | 说明 |
|---|---|---|
| Confidential Client/资源服务器 | `portal-apps-authz` | 关闭标准登录和Direct Access Grant，启用Authorization Services |
| Scope | `access` | 所有应用资源统一使用的授权Scope |
| Resource | 6个 `app:{slug}` | 对应iwork、fabric、pattern、dsm、design-progress、gitea |
| Group Policy | 7个 | 6个 `/apps/{slug}` Policy，加1个 `/admin` Policy |
| Resource Permission | 6个 | 每个应用资源对应一个Affirmative Permission |

同步后的固定统计结果为：

```text
client=portal-apps-authz
resources=6
policies=7
permissions=6
```

连续运行同步命令得到相同结果，证明该流程具备幂等性，不会重复创建资源、Policy或Permission。

Group Policy没有指定旧Token中的Groups Claim，而是由Keycloak直接读取当前Realm Group关系。真实测试证明，同一枚 `dkt-portal` 用户Access Token可以跨Client申请 `portal-apps-authz` 的UMA decision，并在用户加入或移出Group后改变决策结果。

## 5. Portal与Authorizer实现

### 5.1 独立Authorizer容器

新增容器：

```text
DKT_kc_authorizer
```

容器特征：

- 复用Portal Django镜像，避免维护第二套应用代码和依赖。
- 不映射宿主机端口。
- 只连接共享Docker网络 `docker_dkt-net`。
- 通过 `AUTHORIZER_MODE=True` 启用内部授权端点。
- 公网Nginx明确对 `/internal/authorize/` 和 `/internal/access-error/` 返回404。
- 只允许Nginx通过Docker内部location访问。

最终收口时进一步执行了最小权限调整：Authorizer运行时不再持有Keycloak管理员密码，也不再持有 `portal-api` Client Secret。Keycloak管理凭据仍只保留在需要运行同步管理命令的Portal容器中。

### 5.2 内部授权接口

内部接口为：

```text
GET /internal/authorize/{app_slug}/
```

状态语义：

| 状态码 | 含义 |
|---:|---|
| 202 | 身份有效且Keycloak允许访问目标应用 |
| 401 | Cookie缺失、会话失效或Access Token失效 |
| 403 | 身份有效，但不属于目标应用Group或 `/admin` |
| 503 | oauth2-proxy或Keycloak授权端点不可用、响应无效 |
| 404 | 非Authorizer角色或请求了不受支持的slug |

允许和拒绝决策均按 `用户sub + 应用slug` 缓存15秒。缓存键使用用户sub的SHA-256摘要，不在缓存键中暴露原始用户标识。

日志只记录用户名、应用slug、结果、耗时和错误类型，不记录Access Token、Cookie或密钥。Keycloak决策阶段发生故障时，也会保留已经由oauth2-proxy确认的用户名，方便定位故障范围。

### 5.3 oauth2-proxy调整

本轮增加：

```text
pass_access_token = true
cookie_refresh = 4m
```

Access Token只传递到内部Authorizer。Nginx在转发普通子应用请求前主动清除 `X-Auth-Request-Access-Token`，因此iwork等子应用不会接收到用户Access Token。

## 6. Nginx应用入口门禁

6个应用入口统一从“仅检查是否登录”改为“身份确认 + 应用权限决策”：

| URL | 固定授权资源 |
|---|---|
| `/iwork/` | `app:iwork#access` |
| `/fabric/` | `app:fabric#access` |
| `/pattern/` | `app:pattern#access` |
| `/dsm/` | `app:dsm#access` |
| `/design-progress/` | `app:design-progress#access` |
| `/gitea/` | `app:gitea#access` |

DSM的PPT下载独立location同样接入应用授权，避免特殊下载路径绕过门禁。Fabric既有自动更新Bearer Token专用接口继续保持原有旁路规则，没有被本轮应用授权机制破坏。

错误处理规则：

- 页面未登录：进入既有 `/oauth2/start` OIDC登录流程。
- API未登录：保留401，不把API响应重定向为登录HTML。
- 页面无权限：返回统一HTML 403。
- API无权限：返回统一JSON 403。
- 授权系统异常：返回统一HTML或JSON 503。
- 所有拒绝和故障响应使用 `Cache-Control: no-store`。

API无权限响应：

```json
{
  "code": "application_access_denied",
  "message": "当前账号无权访问此应用",
  "application": "iwork"
}
```

授权系统异常响应：

```json
{
  "code": "authorization_service_unavailable",
  "message": "权限服务暂不可用"
}
```

## 7. iwork SSE授权租约

iwork新增配置：

```text
SSE_CONNECTION_LEASE_SECONDS=60
```

实现后的行为：

1. SSE连接建立时照常经过Nginx应用授权。
2. 首条事件和租约内的快照事件、心跳保持原有行为。
3. 连接最长持续60秒。
4. 租约到期后服务端正常结束异步生成器，不制造500或异常断连。
5. 浏览器原有EventSource自动重新建立连接。
6. 新连接重新经过Nginx、Authorizer和Keycloak Authorization Services。

因此撤权并不是依赖前端定时器，而是通过服务端租约强制已有长连接周期性回到授权入口。考虑15秒授权缓存后，最大预期撤权延迟约为75秒。

本次没有修改以下实时数据机制：

- Redis快照发布。
- 快照版本和统一时间水位。
- SSE通知队列和事件广播。
- 15秒心跳。
- 快照不可用事件。
- Celery每分钟读模型刷新。

## 8. 真实验收中发现并修复的问题

单元测试和静态配置检查全部通过后，真实浏览器与Docker链路仍发现了多个只会在完整代理链中出现的问题。所有问题均已修复并增加回归保护。

| 问题 | 实际表现 | 根因 | 修复方法 | 修复效果 |
|---|---|---|---|---|
| Authorizer非法Host | 访问 `/iwork/` 返回Nginx 500 | Nginx把含下划线的容器名 `DKT_kc_authorizer` 当作HTTP Host，Django按RFC拒绝 | 内部授权location固定发送合法 `Host: authorizer` | 未登录请求能正确得到401并进入登录流程 |
| 页面401不跳登录 | Host修复后页面停留在Nginx 401 | 子location定义 `error_page 403` 后不再继承server级401规则 | 页面location显式配置 `error_page 401 = /oauth2/start`，API不配置 | 页面进入OIDC；API继续保留原始401 |
| 403页面非法Host | 撤权后显示Django `DisallowedHost` 调试页 | 统一错误location把 `DKT_kc_portal` 当作Host转发 | 错误渲染location固定发送 `Host: portal` | 正确显示统一无权限页面和JSON |
| 503被错误显示为403 | 暂停Keycloak后显示“无权访问” | `auth_request`只识别2xx/401/403；Authorizer 503转换过程中故障标记丢失 | Authorizer 503响应携带内部故障标记，由Nginx映射并恢复外部503语义 | 页面显示“权限服务暂不可用”，Nginx最终状态为503 |
| 静态应用路由不一致 | 本地仅刷新fabric、gitea、iwork配置 | 本地RegisteredApp清单不完整，`--preserve-stale`保留了另外3份旧配置 | 同步修正全部6份提交内路由并增加全文件断言 | 仓库配置不再依赖生产数据库重新生成后才正确 |
| 重建脚本偶发误报 | Nginx重载后立即检查曾收到一次401并终止脚本 | Nginx旧worker与新配置切换存在短暂竞态 | HTTP检查增加最多5次、间隔1秒的有限重试 | 后续完整重建稳定通过，不掩盖持续故障 |
| Authorizer持有多余密钥 | 功能正常但容器攻击面过大 | 复用Portal环境时注入了管理密码和Token API Secret | 移除无关凭据，生产启动校验区分Portal与Authorizer角色 | Authorizer被攻破时的密钥暴露范围降低 |
| 测试客户端误判SSE截断 | 50连接测试最初报告中文JSON中途截断 | Python `requests` 对无charset的SSE默认按ISO-8859-1解码，把部分UTF-8续字节误判为换行 | 验收客户端明确按UTF-8解析，并用Nginx发送字节数交叉验证 | 证明服务端响应完整，正式两轮并发测试通过 |

## 9. 真实授权矩阵验收

本地Keycloak中创建了一个唯一临时测试账号。验收结束后已按唯一用户ID删除，并再次查询确认不存在。没有修改任何现有账号。

| 测试状态 | 预期结果 | 实际结果 |
|---|---|---|
| 属于 `/users` 和 `/apps/iwork` | 真实iwork页面200 | 通过，加载Eastex生产看板真实页面和数据 |
| 仅属于 `/users` | HTML 403 | 通过，显示统一“无权访问此应用”页面 |
| 属于 `/admin` | 全局放行 | 通过，不属于 `/apps/iwork` 时仍可访问真实页面 |
| 账号禁用并终止会话 | 重新认证 | 通过，浏览器返回Keycloak登录页 |
| Keycloak授权端点不可用 | 严格503 | 通过，页面显示“权限服务暂不可用”，Nginx日志状态503 |
| 未授权iwork API | JSON 403 | 通过，JSON字段完全匹配且 `Cache-Control: no-store` |
| 授权用户iwork API | JSON 200 | 通过，真实工单API成功返回 |
| 授权用户SSE | 建连并接收数据 | 通过，真实快照事件正常 |

Keycloak故障验收采用短暂停止本地Keycloak、发起一次授权请求、立即恢复的方式。恢复后Keycloak重新达到 `healthy`，没有删除或重新导入数据卷。

## 10. 50连接、两轮SSE租约验收

正式验收参数：

```text
并发SSE连接：50
租约轮次：2
单轮目标时长：60秒
总连接租约数：100
```

结果：

| 轮次 | 连接数 | 实际总耗时 | 每条连接事件数 | 快照版本 |
|---:|---:|---:|---:|---|
| 第1轮 | 50 | 60.22秒 | 2 | 全部一致 |
| 第2轮 | 50 | 60.28秒 | 2 | 全部一致 |

验收结论：

- 100个连接租约均在约60秒正常结束。
- 第二轮可以立即重新建连，符合EventSource自动重连路径。
- 没有连接风暴、连接排队超时或异常断连。
- 没有客户端数据错乱或同轮快照版本分裂。
- Nginx、Authorizer、oauth2-proxy、Keycloak和iwork均未异常重启。
- iwork真实API和SSE可在同一授权会话中正常访问。

## 11. 自动化测试与静态检查（截至2026-08-13）

### 11.1 Portal

最终结果：

```text
56 tests passed
2 tests skipped
```

两项跳过测试需要显式提供真实 `FABRIC_TEST_COOKIE`。没有真实浏览器会话时测试会安全跳过，避免把Keycloak登录HTML误判为Fabric API JSON。

新增或更新的测试覆盖：

- Authorization Services资源、Scope、Group Policy和Permission幂等同步。
- 有权限、无权限、管理员放行、身份失效和授权服务故障。
- 允许和拒绝决策15秒缓存。
- Authorizer 503故障标记和故障用户名日志。
- 页面HTML 403、API JSON 403及503契约。
- 应用slug固定映射和Access Token清除。
- DSM特殊下载路径授权。
- Authorizer和Portal内部合法Host。
- 页面401登录流程与API 401语义隔离。
- 6份提交内应用路由配置一致性。
- Authorizer不持有无关管理员密钥。
- 本地重建有限重试及生产兼容路由保留。

### 11.2 iwork

最终结果：

```text
479 tests passed
```

SSE目标测试覆盖：

- 响应仍为 `StreamingHttpResponse` 和 `text/event-stream`。
- 租约内首条数据照常发送。
- 租约到期后生成器正常结束。
- 快照通知、不可用事件和心跳无回归。

### 11.3 其他检查

- 本轮涉及Python文件Ruff检查通过。
- Portal和iwork两套Docker Compose配置解析通过。
- `nginx -t`通过。
- `git diff --check`通过。
- Keycloak Authorization Services同步命令连续运行结果一致。
- 敏感信息扫描未发现真实Token、Cookie、密码或临时测试账号残留。

全仓Ruff仍能发现两个仓库的既有历史代码问题，集中在旧设置文件、旧诊断脚本和旧测试代码。本轮按“只检查本次涉及文件”的仓库规范执行，没有借本次授权改造批量修改无关历史债务。

## 12. 本地Docker验收状态（截至2026-08-13）

本轮使用Portal联合重建脚本完成本地部署：

```powershell
.\scripts\Rebuild-Local.ps1 -Target auth
.\scripts\Rebuild-Local.ps1 -Target portal
```

重建过程没有执行 `docker compose down -v`，也没有删除、重建或重新导入Keycloak卷。

最终运行状态：

| 容器 | 状态 | 健康/重启情况 |
|---|---|---|
| `DKT_kc_keycloak` | running | healthy，重启次数0 |
| `DKT_kc_oauth2proxy` | running | 重启次数0 |
| `DKT_kc_portal` | running | 重启次数0 |
| `DKT_kc_authorizer` | running | 重启次数0 |
| `DKT_kc_nginx` | running | 重启次数0 |
| `DKT_iwork` | running | 重启次数0 |

未登录访问 `/iwork/` 会正常进入本地Keycloak OIDC登录流程。真实登录后再根据应用Group返回200、403或503，不能再仅用未登录302判断授权链路成功。

## 13. Git提交与工作区状态（截至2026-08-13）

### 13.1 Portal仓库

```text
4cf764d [2026-08-12][FEAT] 接入Keycloak应用级授权服务
9af857b [2026-08-13][FIX] 修复应用授权真实链路问题
```

相对远程分支，本地Portal分支领先2个提交；工作树在交付时干净。

### 13.2 iwork仓库

```text
8320b9f [2026-08-12][FIX] 为SSE连接增加授权租约
```

相对远程分支，本地iwork分支领先1个提交。`.reasonix/` 为用户原有未跟踪目录，本轮未读取、修改或提交。

本轮没有执行Git push。

## 14. Standards与Spec双轴审查结论

### 14.1 Standards轴

- 本轮新增Python函数和类使用中文docstring。
- 配置项放置在现有配置区域并使用大写命名。
- 运行日志使用既有Loguru，不输出Token、Cookie或密钥。
- Git提交符合 `[YYYY-MM-DD][TYPE] 描述` 格式。
- 没有提交中央密钥、临时账号资料或iwork `.reasonix/`。
- 本地部署使用仓库规定的联合重建入口，没有直接清理共享卷。

结论：本次差异没有发现未解决的明确规范违规。

### 14.2 Spec轴

原方案要求的Authorization Services、独立Authorizer、Nginx应用门禁、统一错误页面、API错误契约、SSE租约、真实授权矩阵、50连接两轮重连、本地提交和本地Docker验收均已完成。

真实链路验收发现的Host、401继承、503语义、静态路由一致性、重建竞态和最小权限问题已在第二个Portal提交中修复。

结论：本轮本地实施与验收范围已经闭环，没有遗留的Spec阻断项。

## 15. 已知非阻断项

以下问题已确认存在，但属于本轮之前的既有状态，没有阻断应用授权闭环：

1. DSM Nginx配置存在重复 `text/html` MIME类型警告；`nginx -t`仍成功。
2. 本机Python `requests` 依赖组合会发出版本匹配警告；测试与真实请求均能正常完成。
3. 两个仓库存在本轮修改范围之外的历史Ruff债务。
4. 本地RegisteredApp清单只包含部分应用，因此重建脚本必须继续使用 `--preserve-stale`，防止删除生产兼容路由。

这些事项后续应单独建立低风险清理任务，避免与生产授权部署混合处理。

## 16. 后续服务器部署建议

本轮没有授权服务器部署。后续如需交付到 `192.168.0.97`，建议按以下顺序单独执行：

1. 记录Portal和iwork服务器仓库分支、HEAD、未提交文件及容器状态。
2. 确认服务器工作区与远程分支是否存在未合并修改，不覆盖服务器现有文件。
3. 推送并拉取上述3个提交，先完成代码审查和差异核对。
4. 备份当前Nginx生成配置和Keycloak Realm配置；不直接操作Keycloak数据库表。
5. 确认Keycloak healthy后运行幂等授权同步命令。
6. 使用生产既有部署脚本重建oauth2-proxy、Portal、Authorizer、Nginx和iwork，不删除任何数据卷。
7. 按本文件第9节重新执行真实授权矩阵。
8. 按本文件第10节至少执行一次50连接、两轮SSE租约验收。
9. 观察Authorizer拒绝率、Keycloak UMA耗时、SSE重连数量、容器重启次数和Nginx 5xx。
10. 验收通过后再宣布生产授权闭环生效。

生产验收不能只检查容器running或未登录302。必须使用真实授权用户确认200、真实无权限用户确认403，并通过故障演练确认503语义。

## 17. 回滚方案

如果后续生产部署后出现关键认证或授权故障，应优先执行可逆回滚：

1. 停止继续部署其他应用，不删除Keycloak或数据库卷。
2. 回滚Portal和iwork到部署前已记录的提交。
3. 恢复部署前的Nginx应用路由配置并执行 `nginx -t`。
4. 重载Nginx，验证原有oauth2-proxy登录链路恢复。
5. `portal-apps-authz`资源服务器对象可以暂时保留；没有Nginx调用时不会改变现有应用访问。
6. 如果必须移除Keycloak授权对象，应通过Admin API按对象ID处理，禁止手工修改Keycloak数据库表。

SSE租约回滚只需恢复iwork提交并重建 `DKT_iwork`，不会修改Redis快照、历史数据或远程生产数据库。

## 18. 最终结论

截至2026-08-13的本地验收记录表明，本轮已经完成从“Portal卡片可见性控制”到“Keycloak实时Group驱动的应用入口强制授权”的改造。验收覆盖真实浏览器、真实Keycloak、真实Nginx代理、真实iwork API和50条并发SSE连接：

- 未授权用户无法再通过直接输入URL绕过Portal权限。
- `/admin` 保留全局访问能力。
- Group撤权会在短缓存和SSE租约边界内生效。
- 页面、API和授权系统故障具有明确且可审计的403/503语义。
- SSE连接在50条并发连接、连续两轮租约下保持数据一致和稳定重连。
- Authorizer的运行凭据和网络暴露已收敛到必要范围。

本地实施与验收已经完成；远程推送和服务器部署仍需后续明确授权后单独执行。
