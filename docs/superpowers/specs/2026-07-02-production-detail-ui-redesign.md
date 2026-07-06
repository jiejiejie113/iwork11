# 生产详情页 UI 重构设计

> 日期：2026-07-02 | 状态：已确认，待实施

---

## 概述

对 `production_detail.html` 详情页进行三项 UI 改进：工具栏合并为单行、新增工单号筛选下拉、表格视图重构为左右双表汇总布局。

## 改动范围

- 文件：`iwork/templates/iwork/production_detail.html`
- 类型：纯前端改动（HTML + CSS + Vue.js）
- 涉及区域：详情页（`currentView === 'detail'`）的工具栏和表格视图

---

## 一、工具栏合并为一行

### 当前状态

```html
<!-- 行1：面包屑 -->
<div class="flex-shrink-0 flex items-center gap-2 mb-4 text-sm">
  生产详情 / {[ detailTitle ]} ...
</div>

<!-- 行2：视图切换 + 搜索 + 编辑按钮 -->
<div class="flex-shrink-0 flex items-center gap-3 mb-4">
  [[表格视图|卡片视图]] [搜索框] [编辑]
</div>
```

### 目标状态

```html
<!-- 单行：面包屑 + 控件组 -->
<div class="flex-shrink-0 flex items-center gap-3 mb-4 flex-wrap text-sm">
  <!-- 左侧：面包屑（保留原有内容，移除 mb-4） -->
  <a href="...">生产详情</a> / <span>{[ detailTitle ]}</span>
  <span class="text-slate-400">👤 {[ detailSummary.worker_count ]}人 ...</span>
  
  <!-- 右侧：控件组（用 ml-auto 推到右侧） -->
  <div class="flex items-center gap-3 ml-auto flex-wrap">
    [[表格视图|卡片视图]]
    [全部工单 ▼]  <!-- 新增 -->
    [搜索框]
    [编辑/取消/保存]
  </div>
</div>
```

### 要点

- 原面包屑 `div` 和控件 `div` 合并为一个 `flex` 容器
- 面包屑保持左对齐，控件组 `ml-auto` 右对齐
- 保留 `flex-wrap`，小屏（<768px）自动换行
- 容器统一 `mb-4`，消除两个独立 `mb-4`

---

## 二、工单号筛选下拉

### 渲染条件

仅当 `detailType === 'flow'` 时显示，位于视图切换按钮右侧、搜索框左侧。

### 数据结构

```javascript
const wrkOrderFilter = ref('');  // '' 表示"全部工单"

const workorderOptions = computed(() => {
  const set = new Set();
  employees.value.forEach(emp => {
    (emp.workorders || []).forEach(wo => set.add(wo));
    (emp.steps || []).forEach(s => { if (s.workorder) set.add(s.workorder); });
  });
  return [...set].sort((a, b) => naturalCompare(a, b));
});
```

### 交互逻辑

- 默认选中 `<option value="">全部工单</option>`
- 选择具体工单号后，`filteredEmployees` 增加过滤条件
- `wrkOrderFilter` 变化时重新计算 `filteredEmployees`（无需额外 API 请求）
- 切换 detail 或刷新数据时重置为"全部工单"

### HTML

```html
<select v-if="detailType === 'flow'" v-model="wrkOrderFilter"
        class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200">
  <option value="">全部工单</option>
  <option v-for="wo in workorderOptions" :key="wo" :value="wo">{[ wo ]}</option>
</select>
```

---

## 三、左右双表汇总布局

### 替代对象

完全替代当前 `<div v-if="detailLayout === 'table'">` 内的原有表格，不再保留动态列（工序号列 + 工单列 + 每工序分列）。

### 布局容器

```html
<div class="flex gap-4 max-lg:flex-col">
  <!-- 左表 -->
  <div class="w-1/2 max-lg:w-full">...</div>
  <!-- 右表 -->
  <div class="w-1/2 max-lg:w-full">...</div>
</div>
```

### 左表：工序汇总

| 工序号 | 总数量 |
|--------|--------|
| 70 | 1,200 件 |
| 71 | 890 件 |

```javascript
const stepSummary = computed(() => {
  const map = {};
  const emps = filterByWorkOrder(employees.value);
  emps.forEach(emp => {
    (emp.steps || []).forEach(s => {
      map[s.stepno] = (map[s.stepno] || 0) + (s.qty || 0);
    });
  });
  return Object.entries(map)
    .map(([stepno, total]) => ({ stepno: Number(stepno), total }))
    .sort((a, b) => a.stepno - b.stepno);
});
```

- 受工单筛选影响（只统计匹配工单的 steps）
- 不受搜索框影响
- 按工序号升序排列

### 右表：员工汇总（保留编辑目标）

| 员工ID | 总产量 | 目标 | 达标 | 效率 |
|--------|--------|------|------|------|
| 1001 | 350 | 300 | ✓ | 116.7% |
| 1002 | 280 | -- | -- | -- |

```javascript
const employeeSummary = computed(() => {
  let emps = filterByWorkOrder(employees.value);
  // 搜索过滤
  if (tableSearch.value) {
    const q = String(tableSearch.value).toLowerCase();
    emps = emps.filter(e => String(e.reg_per_sys_id).includes(q));
  }
  // 排序
  const key = sortKey.value;
  const asc = sortAsc.value;
  return [...emps].sort((a, b) => {
    const va = key === 'reg_per_sys_id' ? Number(a.reg_per_sys_id) : (a.qty || 0);
    const vb = key === 'reg_per_sys_id' ? Number(b.reg_per_sys_id) : (b.qty || 0);
    return asc ? va - vb : vb - va;
  });
});
```

- 受工单筛选和搜索框双重影响
- 支持按员工ID或总产量排序（表头点击切换）
- 保留编辑/保存/取消目标功能（`isEditing`、`draft`）
- 目标列：非编辑态显示数值或 `--`，编辑态显示 `<input type="number">`

### 数据过滤辅助函数

```javascript
function filterByWorkOrder(emps) {
  if (!wrkOrderFilter.value) return emps;
  return emps.filter(emp => {
    if ((emp.workorders || []).includes(wrkOrderFilter.value)) return true;
    return (emp.steps || []).some(s => s.workorder === wrkOrderFilter.value);
  });
}
```

### 移除的内容

- 原有 `detailStepnos` 计算属性（不再需要动态工序列）
- 原有 `getStepQty()` 函数
- 原有 `stepnoColumnTotals` / `columnGrandTotal` / `columnTargetTotal` 计算属性
- 原有 `<thead>` 动态列表头和 `<tfoot>` 合计行

### 新增的内容

- `wrkOrderFilter` ref + `workorderOptions` computed
- `stepSummary` computed
- `employeeSummary` computed
- `filterByWorkOrder()` 辅助函数

### 保留的功能

| 功能 | 状态 |
|------|------|
| 搜索框（`tableSearch`） | 保留，作用于右表 |
| 编辑目标 / 取消 / 保存 | 保留，作用于右表目标列 |
| 排序（`sortKey`/`sortAsc`） | 保留，作用于右表（员工ID/总产量） |
| 卡片视图 | 不变 |

---

## 四、响应式设计

| 断点 | 工具栏 | 表格布局 |
|------|--------|---------|
| >= 1024px | 单行水平 | 左右并排（各 50%） |
| 768-1023px | 自动换行 | 上下堆叠（各 100%） |
| < 768px | 控件换到第二行 | 上下堆叠（各 100%） |
