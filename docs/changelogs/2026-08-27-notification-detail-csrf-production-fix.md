# 站内通知详情点击与生产CSRF修复

## 问题现象

生产环境中，每日责任摘要通知已经显示“查看详情”，但点击通知后详情弹窗没有打开。

## 生产证据与根因

- 通知列表与SSE请求正常返回`200`。
- 用户点击通知时，生产日志记录
  `POST /api/account/notifications/8/read/ HTTP/1.1 403 Forbidden`。
- 生产配置没有提供`DJANGO_CSRF_TRUSTED_ORIGINS`，程序默认值只包含本地测试地址，
  因此来自`https://dituportal.dongming.local`的已读POST未通过Django CSRF Origin校验。
- 共用标题栏没有主动生成CSRF Cookie，新浏览器会话可能无法提供
  `X-CSRFToken`所需令牌。
- 通知点击逻辑先等待已读POST和列表刷新，最后才打开详情；POST失败会直接中断事件处理，
  将后端403放大为“查看详情完全点不了”。

## 修复内容

1. 生产环境显式信任新、旧Portal HTTPS源站：

   ```text
   https://dituportal.dongming.local
   https://dktportal.dongming.local
   ```

2. 共用标题栏渲染CSRF令牌，引导Django为包含通知中心的页面签发CSRF Cookie。
3. 每日摘要点击后立即打开详情，再异步标记已读并刷新列表。
4. 已读POST失败时捕获并记录警告，不关闭已经打开的详情，也不产生未处理的Promise拒绝。

## 回归测试

- 使用启用真实CSRF检查的Django Client，从生产HTTPS Origin调用通知已读接口，验证返回`200`。
- 请求包含通知中心的首页，验证响应签发`csrftoken` Cookie。
- 前端契约测试验证详情打开动作先于已读POST。
- 使用实际`static/iwork/notifications.js`运行最小DOM行为复现；在已读POST固定返回403时，
  详情模态仍为打开状态，结果为`GREEN`。

## 生产交付定位

本修复作为部署机制认证完成后的首个真实iwork生产发布案例执行：

1. 本地测试、静态检查和代码审查。
2. 提交并推送`Keycloak`分支。
3. GitHub Actions CI和GHCR不可变镜像发布。
4. 生产Runner smoke和`apply=false`预检。
5. iwork正式部署及真实通知点击验收。

Portal部署机制认证属于Portal独立发布链路；iwork继续使用自己的受控部署Workflow，不能使用
Portal能力证书代替iwork的CI、Digest、Runner smoke、预检和部署门禁。
