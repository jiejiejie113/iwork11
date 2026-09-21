# iwork CI/CD Owner/ACL 校验规范

> 版本：`v1`
> 制定日期：2026-08-31
> 适用范围：`jiejiejie113/iwork11` 生产部署、外部探针、看门狗、状态和准入安装
> （2026-09-21 起由 `GuChenkano/iwork` 迁移，见总方案第15节）
> 文档性质：专项安全参考规范；不替代唯一总方案

本规范是 iwork CI/CD 的 Owner、Windows DACL、路径和文件完整性统一标准。
它解决 Hosted Runner 与生产主机身份不同的问题，但不通过放宽生产校验来解决兼容性。
任何实现、Workflow、安装器和测试都必须遵循本规范；若当前实现与本规范冲突，以失败关闭为准，
并在总方案中登记偏差和下一入口。

## 1. 不变量和安全边界

1. 生产部署必须验证固定主机上的受信文件、目录和计划任务；不得从服务器 Git 工作区读取候选脚本或生产配置。
2. Hosted Runner 只执行隔离测试，不读取生产密钥、不访问生产路径、不接受生产域账号作为测试前提。
3. 测试可以使用临时信任清单和临时 SID，但必须调用与生产相同的严格校验器；不得增加自动放宽的生产分支。
4. Owner、DACL、重解析点、内容 SHA-256 和运行身份是相互独立的门禁，不能用其中一项替代另一项。
5. Workflow dispatch 不得让用户输入生产路径、Owner、SID、哈希、密钥或 ACL 策略；这些值只能来自固定 Workflow、主机安装清单或受控变量。
6. 任一校验失败都必须在候选容器切换前失败关闭；失败不能写入 `deployed`，不能复用旧收据或旧证明。
7. Windows 本机管理员或 SYSTEM 可以在操作系统层面接管文件。若威胁模型包括恶意本机管理员，必须使用独立签名服务、HSM 或独立主机，不能以增加 ACL 条件声称已经解决。

## 2. 身份模型

安全判断统一使用 SID；账号名称只用于诊断输出，不参与授权比较。

| 身份 | 作用 | 约束 |
|---|---|---|
| 部署执行身份 | 运行固定部署脚本的 Runner 账号 | 由 Runner 安装、Hook 和脚本共同固定；生产值在主机准入时记录 |
| 探针生产者身份 | 生成六项外部探针收据的服务账号或 SYSTEM | 与部署执行身份可以不同；必须由清单固定 |
| 安装身份 | 安装或更新生产机制 | 只在维护窗口使用，不作为运行期写入者 |
| SYSTEM | 看门狗、恢复和受控归档 | SID 固定为 `S-1-5-18` |
| 本机 Administrators | 维护人员组 | 不得作为运行期生产 Owner、写入者或密钥读取者的默认白名单 |

生产者身份、文件 Owner 和部署执行身份不得再复用一个字符串参数。收据中的
`producer_identity` 只是声明，必须同时由固定生产者进程身份和 ACL 清单验证。

## 3. 受保护对象与 ACL 基线

以下是默认策略；对象的最终允许 SID 集合必须写入主机 trust manifest，不能依赖本机默认 ACL。

| 对象 | 推荐 Owner | 允许读取 | 允许写入 | 额外要求 |
|---|---|---|---|---|
| 外部探针生产者脚本/程序 | SYSTEM | 探针生产者、部署验证身份 | SYSTEM、安装身份 | 固定路径、内容 SHA-256、禁止重解析 |
| 探针签名私钥（HMAC 过渡期） | SYSTEM | 仅探针生产者；验证者仅在无法升级时读取 | SYSTEM、安装身份 | 禁止未授权读取；不得写入日志或 Artifact |
| 探针公钥/证书（非对称方案） | SYSTEM | 部署验证身份、SYSTEM | SYSTEM、安装身份 | 固定指纹；生产最终方案优先使用此模式 |
| 外部探针收据目录 | SYSTEM | 部署身份、SYSTEM | 探针生产者、SYSTEM | 禁止继承；禁止宽泛主体写入 |
| 单次外部探针收据 | SYSTEM 或清单声明的生产者 SID | 部署身份、SYSTEM | 探针生产者、SYSTEM | 只能对应一次 nonce；旧文件不得覆盖 |
| 看门狗脚本和机制清单 | SYSTEM | 部署身份、SYSTEM | SYSTEM、安装身份 | 脚本 SHA、清单 SHA、任务身份和 Action 固定 |
| 部署状态目录 | SYSTEM 或固定部署身份 | 部署身份、SYSTEM | 部署身份、SYSTEM | 按 Run/request 分隔；不可通过旧文件放行 |
| 部署锁目录 | SYSTEM | 部署身份、SYSTEM | 部署身份、SYSTEM | 共享锁的创建方必须全部能访问 |

运行期 ACL 不得显式授予以下主体写权限：
`Everyone`、`Authenticated Users`、`Users`、未声明账号、未知 SID 和本机
`Administrators`。对于状态文件和收据文件，如果创建者必须成为 Owner，必须在清单中逐对象声明，
不能把该例外推广到脚本、密钥或信任清单。

## 4. Trust Manifest

Trust manifest 是主机级授权策略，不是 Release Manifest，也不包含密码或私钥正文。它本身必须以
无 BOM、LF、UTF-8 字节存储，安装器和生产 Workflow 固定其完整 SHA-256。清单哈希不能自引用，
应由 Workflow/Hook 或独立 `.sha256` 文件固定。

最小字段如下：

```json
{
  "schema": "iwork-owner-acl/v1",
  "policy_id": "iwork-production-trust-v1",
  "environment": "production",
  "deployment_identity_sid": "S-1-...",
  "probe_producer_identity_sid": "S-1-...",
  "objects": [
    {
      "id": "probe-producer",
      "kind": "file",
      "path": "D:\\DM\\cicd-tools\\iwork\\ExternalProbeProducer.ps1",
      "content_sha256": "...",
      "owner_sids": ["S-1-5-18"],
      "allowed_read_sids": ["S-1-..."],
      "allowed_write_sids": ["S-1-5-18"],
      "inheritance_protected": true,
      "reparse_allowed": false
    }
  ],
  "receipt_schema": "iwork-external-probe-receipt/v4",
  "probe_contract_id": "iwork-external-probes-v2"
}
```

每个对象必须声明 `kind`、规范化绝对路径、Owner SID 集合、读写 SID 集合、继承策略和是否允许重解析点。
脚本、密钥、公钥、收据目录、状态目录和看门狗不得共享一套隐含 ACL。

## 5. 校验算法

通用校验器必须按以下顺序执行：

1. 检查当前进程 SID 是否匹配生产清单中的部署执行身份（测试清单使用当前隔离 SID）。
2. 读取固定 trust manifest，先校验清单自身 SHA-256，再校验 Schema、环境和字段集合。
3. 将路径规范化为绝对路径，确认位于批准根目录；检查文件及所有父目录没有 Junction、Symbolic Link 或其他重解析点。
4. 读取 Owner 为 `SecurityIdentifier`，确认属于该对象的 `owner_sids`。
5. 确认 DACL 已关闭继承（`AreAccessRulesProtected`），拒绝任何未声明继承 ACE，包括 `InheritOnly` 规则。
6. 使用 `GetAccessRules(..., [SecurityIdentifier])` 枚举显式 ACE；拒绝未知 SID、宽泛主体和非规范 Deny/Allow 组合。
7. 对每个 Allow ACE 确认主体在该对象白名单内，且权限不超过该对象允许掩码。
8. 变更权限必须显式检查：`WriteData`、`AppendData`、`WriteAttributes`、
   `WriteExtendedAttributes`、`Delete`、`DeleteSubdirectoriesAndFiles`、
   `ChangePermissions` 和 `TakeOwnership`。不能使用模糊的 `Write -bor Modify -bor FullControl` 代替。
9. 私钥还必须拒绝未授权读取；仅检查写权限是不够的。
10. 对固定文件计算 SHA-256；在调用生产者前重新检查路径、ACL 和哈希，避免简单 TOCTOU。
11. 生产者必须在自身进程中读取当前 SID，并把它与 challenge 中的预期 SID 一起写入收据。
12. 收据生成后重新打开并验证 Owner、DACL、HMAC/非对称签名、nonce、Run/request、切换时间、
    双容器身份和六项探针；任何不匹配都失败关闭。

脚本、密钥和信任清单应尽量使用只读句柄计算哈希。错误日志只能记录策略 ID、对象 ID、SID、路径摘要和错误码，
不能输出密钥、收据签名或完整敏感环境变量。

## 6. 签名与密钥边界

当前 HMAC 收据模式要求部署验证者读取共享密钥；因此 Runner 被攻破时可能伪造收据。生产最终方案应升级为：

- 探针生产者持有私钥；
- 部署脚本只持有公钥或证书；
- trust manifest 固定公钥指纹；
- 收据使用非对称签名的 `iwork-external-probe-receipt/v4`；
- 私钥 ACL 只允许生产者服务和 SYSTEM 读取。

在该升级完成前，v3 HMAC 只能作为过渡机制；即使 ACL 校验通过，也不能把它描述为对抗 Runner 被攻破的完整生产信任链。

## 7. CI/CD 集成要求

### 7.1 Hosted Runner CI

- 只使用 `%TEMP%` 下的隔离路径、Fake Docker 和临时 trust manifest。
- 测试清单中的 SID 来自当前 Runner；不得硬编码或解析 `DONGMING\\shuju`。
- 测试夹具应关闭继承，只授予当前测试 SID 和 SYSTEM 所需权限，并保留 Owner/未知写入/密钥读取的负向用例。
- 生产脚本不得存在根据 `CI=true`、Runner 名称或路径自动跳过 ACL 的分支。

### 7.2 Release

Release 只产生不可变镜像、配置包和 Release Manifest；不携带主机私钥，不把主机 ACL 当作 Release 证据。

### 7.3 生产准入安装

安装器必须在 Runner 空闲和维护窗口中：

1. 原子暂存探针生产者、公钥/密钥、trust manifest 和看门狗。
2. 计算源文件和副本 SHA-256，复制后再次计算。
3. 设置最终 Owner、关闭继承、写入精确 DACL。
4. 校验任务名称、任务路径、执行身份和唯一 Action。
5. 生成固定 Hook，锁定 Workflow 路径、提交和机制清单 SHA。
6. 任一失败都不得替换现有生产安装。

Workflow 只固定传递 trust manifest 路径和 SHA（以及清单解析出的固定参数），不得把这些值声明为 dispatch 输入。

### 7.4 Preflight

`apply=false` 必须完成 trust manifest、探针生产者、公钥/密钥、收据目录和看门狗 ACL/哈希校验，
但不得切换容器、生成生产收据或消费部署请求。缺少生产材料时，预检应提前失败，而不是把失败推迟到 `apply=true`。

### 7.5 Deploy

正式部署在任何 `docker compose up` 前再次运行完整校验，随后才创建 nonce、切换 Web/Alert Worker、
调用探针生产者和验证收据。六项探针或任何 ACL/身份校验失败时，恢复双容器和配置包，写入失败收据，
不得写 `deployed`。

### 7.6 production-status

只读状态应报告策略 ID、trust manifest SHA、对象校验结果、生产者/看门狗哈希和错误码，不输出密钥正文。

## 8. 测试验收矩阵

必须同时具备正向和负向测试：

- 当前隔离 SID + SYSTEM 的受保护 ACL 可以通过；
- 部署身份、探针生产者身份和文件 Owner 不同但符合清单可以通过；
- Owner 错误、Owner 为 Administrators、继承 ACL、重解析点必须失败；
- Everyone、Users、Authenticated Users、未知账号写 ACE 必须失败；
- 只读 ACE 不得被误判为写权限；
- `ChangePermissions`、`TakeOwnership`、删除权限必须失败；
- 私钥存在未授权读取必须失败；
- 文件或清单哈希改变必须失败；
- 旧收据、nonce、生产者 SID、容器 ID、签名和六项探针任一不匹配必须失败；
- 所有失败场景必须断言没有执行候选切换命令。

生产静态契约还必须断言：

- Workflow 没有 ACL/路径/身份的可变 dispatch 输入；
- 安装器和 Workflow 使用同一 trust manifest SHA；
- 机制变更会同步更新部署脚本、看门狗、清单、安装器和准入 Hook 哈希；
- 生产配置、密钥和探针收据不从 Git 工作区读取或写回仓库。

## 9. 当前实现的迁移要求

当前 `Invoke-IworkProductionDeployment.ps1` 将探针生产者身份同时用作文件 Owner 和收据身份，且主要使用账号名称和少量黑名单 ACL。
这解释了 Hosted Runner 临时目录 Owner 为 `BUILTIN\\Administrators` 时的 CI 失败，但不能通过全局跳过 Owner 校验修复。

下一切片应：

1. 新增 SID 化通用校验器和 trust manifest 解析；
2. 将部署执行身份、生产者身份、Owner 和允许写入主体拆开；
3. 收紧 DACL 为显式允许集合，并补充私钥读取校验；
4. 让 Hosted Runner 夹具生成受保护临时 ACL，继续走同一严格校验；
5. 在生产主机提供真实生产者、公钥/密钥、清单和 ACL 证据后，再更新 Workflow、安装器和部署脚本哈希。

在第 5 步完成并通过生产主机只读核验前，`apply=true` 必须保持失败关闭；不得用测试夹具、`BUILTIN\\Administrators` 或旧收据替代生产证据。

## 10. 社区验证依据与本仓库采用方式

- [libgit2 #6279](https://github.com/libgit2/libgit2/issues/6279) 记录了同一类 Hosted Windows Runner 现象：默认 PowerShell 创建的文件可能由
  `BUILTIN\\Administrators` 持有，而当前进程用户是 `runneradmin`。
- [libgit2 #6341](https://github.com/libgit2/libgit2/pull/6341) 是已合并的修复：只有当前用户确实属于管理员组时，才把管理员组 Owner
  视为普通仓库读取的可接受情况。该语义不能移植到 iwork 的生产信任边界，生产清单仍禁止管理员组 Owner。
- [Microsoft `icacls` 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls) 明确支持数值 SID、
  `/setowner`、`/inheritancelevel:r` 和 `/verify`，适合在 Windows 上设置后立即回读验证。

iwork 的 Hosted Runner 隔离夹具采用上述工具语义而不是放宽生产校验：先写入当前 SID+SYSTEM 的受保护 DACL，立即回读 Owner；若 .NET
`SetOwner` 未生效或抛出异常，则调用 `icacls /setowner *<当前SID>`，再回读并在仍不匹配时失败关闭。夹具脚本使用 UTF-8 BOM，避免
Windows PowerShell 5.1 按系统代码页解析中文字符串。生产脚本不调用该回退、不识别 CI 环境，也不把 `BUILTIN\\Administrators` 加入白名单。
