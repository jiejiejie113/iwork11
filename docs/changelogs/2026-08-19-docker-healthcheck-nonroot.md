# iwork容器健康检查与非root运行

## 背景

第二优先级任务“补运行可靠性”：容器层此前只有 alert-worker 有健康检查，`DKT_iwork` 的“Up”不能证明服务可用；Celery 以 root 运行并持续输出 superuser 安全警告。另外，逾期补填测试硬编码业务日期，跨日后被组长“只能修改当前业务日”的校验拒绝。

## 变更

- `docker-compose.yml`：`iwork` Web 容器新增 healthcheck（HTTP `GET /` 期待 200），`start_period` 90 秒覆盖迁移与静态收集窗口；探法与 Rebuild-Local 的 `Wait-IworkReady` 语义一致。
- `Dockerfile` + `entrypoint.sh`：新增固定 uid/gid 10001 的 `iwork` 用户。entrypoint 先以 root 修正 bind mount（`logs`/`static`）中历史 root 属主文件——非 root 进程无法追加这些文件——再通过 `setpriv` 降权运行整个应用栈（uvicorn、realtime worker、beat、迁移），消除 Celery superuser 警告并满足最小权限。
- `tests/test_identity_and_targets.py`：逾期补填测试改用 `get_business_date()` 动态取业务日，分配生效日期相对当前业务日计算。

## 验证

- `docker top`：uvicorn、realtime worker、beat、alert worker 全部以 uid 10001 运行。
- 两个容器日志无 PermissionError、无 superuser 警告；`celerybeat-schedule` 由 iwork 属主写入。
- `logs` bind mount 追加写入正常（当日日志持续增长）；`static` bind mount 可写（touch 验证）。
- alert worker `celery inspect ping` 正常；两个容器 healthcheck 均为 healthy。
- 518 项 pytest 通过；`Rebuild-Local.ps1 -Target iwork` 在冷启动场景下退出 0。

## 已知遗留（非本次引入）

`start.sh` 中 collectstatic 带 `|| true` 掩盖失败，且当前 settings 在容器环境未配置 `STATIC_ROOT`，容器内 collectstatic 实际未生效；静态目录由历史部署方式填充。本轮未修改。
