# 激活区拖拽占位挤压 + 树形外框先过渡再淡入

日期：2026-07-09
提交：`e97efc1` `[2026-07-09][FEAT] 激活区拖拽占位挤压 + 树形外框先过渡再淡入`

## 变更概览

针对生产明细数据页 `/iwork/production/detail-data/` 的两处交互体验改造，保留原有 Tailwind 字体大小、颜色、间距、布局风格，仅替换拖拽与过渡的交互逻辑。

| # | 改造点 | 改造前问题 | 改造后效果 |
|---|--------|-----------|-----------|
| 1 | 激活区标签拖拽 | 插入指示器为细竖线 `dim-tag-insert-indicator`，不占布局空间，不挤压其他标签，视觉与落位不一致 | 占位虚线框 `dim-tag-insert-placeholder` 参与布局，挤压后续标签，落位与视觉位置一致 |
| 2 | 树形表格展开/收起 | 用 `<table>/<tbody>/<tr>`，`<tr>` 无法 `position:absolute`，离开行仍占空间，其他行无法立即 FLIP 上移，过渡卡顿 | 改为 `div + grid`，外层 `.tree-wrap` 先做高度过渡，内部行随后淡入/淡出 |

修改文件：`iwork/templates/iwork/production_detail.html`（1 文件，+99 / -62 行）

---

## 详情一：激活区拖拽占位挤压

### 改造前问题

- 插入指示器 `.dim-tag-insert-indicator` 为 `display:inline-block` 的 2px 细竖线，宽度虽设为 `tagDragWidth` 但仅靠 `border-left` 表现，不占实际布局宽度，无法挤压其他标签
- 插入位置判定依赖 `.dim-tag-wrap` 包裹层 + 占位符 `.placeholder` 计数 `realBefore`，逻辑复杂且在换位时易错位

### 改造方案

1. **CSS**：新增 `.dim-tag-insert-placeholder` 样式，带宽度/高度的虚线框，参与 flex 布局，脉冲背景动画体现占位
2. **HTML**：去掉 `.dim-tag-wrap` 包裹层；插入位渲染带宽度高度的占位虚线框；原标签拖动换位时 `display:none` 让位给虚线框，拖出激活区时保留原位；拖动期间隐藏 `▸` 箭头避免视觉错乱
3. **JS**：`onTagPointerMove` 改用 `[data-act-idx]` + `offsetWidth>0` 过滤可见标签，基于实际中心点判断插入位；新增 `tagDragHeight` 让占位框高度匹配标签；换位时校正索引（移除自身后 `ins -= 1`）

### 关键代码位置

- CSS：`.dim-tag-insert-placeholder` + `@keyframes tagPlaceholderPulse`
- HTML：激活区 `<template v-for="(lv, idx) in selectedLevels">` 内占位框 + 原标签 `display` 控制
- JS：`onTagPointerMove` 激活区分支 + `tagDragHeight` ref + `onTagPointerDown` 记录高度

### 行为对照

| 场景 | 改造前 | 改造后 |
|------|--------|--------|
| 激活区内换位 | 细竖线不挤压，标签位置不变 | 虚线框挤开其他标签，实时反映落位 |
| 拖出激活区 | 原标签变占位符 | 原标签保留原位不挤压，松手即移除 |
| 插入精度 | 依赖 wrap 计数，边缘死区 | 基于可见标签实际中心点，无死区 |

---

## 详情二：树形外框先过渡再淡入

### 改造前问题

- 用 `<table>/<thead>/<tbody>/<tr>/<td>` 结构，`<tr>` 无法设 `position:absolute`，离开行在 leave 动画期间仍占文档空间
- 其他行无法立即触发 FLIP move 动画上移，收起时卡顿
- 行过渡 `tree-enter-active` 无 delay，子行淡入与外框伸缩同时进行，时序混乱

### 改造方案

1. **HTML**：`<table>` → `div + display:grid(1fr 80px 80px)` 精确复刻原列宽；表头独立固定不参与过渡；外层包 `.tree-wrap`，`transition-group` 用 `.tree-body`
2. **CSS**：
   - `.tree-wrap { overflow:hidden; transition:height 0.32s }` 外框高度先过渡
   - `.tree-leave-active { position:absolute; left:0; right:0 }` 离开行脱离流，其他行立即 move 上移
   - `.tree-enter-active { transition-delay:0.12s }` 子行淡入在外框撑开之后
   - `.tree-move { transition-delay:0.04s }` 行位移略微延后
3. **JS**：新增 `treeWrapEl` ref + `watch(productRows)`，变化前固定 `oldH` → `nextTick` 设 `newH` 触发外框先伸缩 → 340ms 后释放为 `auto` 避免内容裁剪

### 时序

- **展开**：外框撑高（0.32s）→ 子行延迟 0.12s 后淡入（0.26s）
- **收起**：旧行淡出 + 外框收缩同步（0.18s / 0.32s）→ 后续行 FLIP 上移（0.30s）

### 关键代码位置

- CSS：`.tree-wrap` / `.tree-body` / `.tree-enter-active` / `.tree-leave-active` / `.tree-move`
- HTML：表头 grid div + `.tree-wrap > transition-group.tree-body`
- JS：`treeWrapEl` ref + `watch(productRows)` 外框高度驱动逻辑 + setup return 暴露 `treeWrapEl`

---

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Django 模板编译 | OK |
| JS 括号/花括号平衡 | 0 / 0 |
| 容器重建（`docker compose -p iwork up -d --build iwork`） | 成功，镜像 `70d25fd` |
| Nginx 重载 | `signal process started` |
| iwork 直连 `http://localhost:8000/production/detail-data/` | HTTP 200 |
| Nginx 代理 `http://localhost:8080/iwork/` | HTTP 302（OIDC 重定向，符合预期）|
| 渲染输出含改造标识 | `dim-tag-insert-placeholder` / `tree-wrap` / `treeWrapEl` / `tagDragHeight` 全部存在 |

浏览器访问 `https://dktportal.dongming.local/iwork/production/detail-data/` 实测：
- 激活区拖拽：虚线框挤开其他标签，落位与视觉一致
- 树形展开：外框先平滑伸缩，子行随后淡入
