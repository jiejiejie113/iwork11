# 生产详情页 UI 重构 实施计划

> **For agentic workers:** 本计划对 `production_detail.html` 进行纯前端重构。使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 按任务逐个实施。步骤使用 `- [ ]` 语法追踪。

**目标:** 对生产详情页进行三项 UI 改进：合并工具栏为单行、新增工单号筛选下拉、表格视图替换为左右双表汇总布局。

**架构:** 纯前端改动，仅修改 `iwork/templates/iwork/production_detail.html` 一个文件，在 Vue.js 3 组件内新增 computed 属性和辅助函数，无后端变更。

**技术栈:** HTML + Tailwind CSS + Vue.js 3（Composition API）

---

### 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `iwork/templates/iwork/production_detail.html` | 生产详情页模板（含 Vue 组件代码） | 修改 |

---

### Task 1: 合并工具栏为单行

**文件:**
- 修改: `iwork/templates/iwork/production_detail.html:193-230`

- [ ] **Step 1: 替换详情页工具栏 HTML 结构（第 193-230 行）**

将原有两行独立的 `div`（面包屑 + 控件栏）合并为一个 `flex` 容器。

找到以下两段 HTML（第 193-230 行）:

```html
        <!-- 面包屑 -->
        <div class="flex-shrink-0 flex items-center gap-2 mb-4 text-sm">
            <a :href="basePath + 'production/detail-data/'" class="text-blue-400 hover:underline">生产详情</a>
            <span class="text-slate-600">/</span>
            <span class="font-semibold">{[ detailTitle ]}</span>
            <span class="ml-auto text-slate-400">
                👤 {[ detailSummary.worker_count ]}人
                <span v-if="detailSummary.target_total > 0">
                    · 已设目标 {[ detailSummary.targeted_count ]}/{[ detailSummary.worker_count ]}人
                    · 🎯 目标 {[ fmtNum(detailSummary.target_total) ]}
                    · 产值 {[ fmtNum(detailSummary.targeted_qty) ]}
                    · <span :class="detailSummary.efficiency >= 100 ? 'text-emerald-400' : 'text-red-400'">
                        效率 {[ detailSummary.efficiency.toFixed(1) ]}% {[ detailSummary.efficiency >= 100 ? '达标 ✓' : '不达标 ✗' ]}
                    </span>
                </span>
            </span>
        </div>

        <!-- Tab + 搜索 -->
        <div class="flex-shrink-0 flex items-center gap-3 mb-4">
            <div class="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
                <button @click="detailLayout = 'table'"
                    :class="detailLayout === 'table' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                    class="px-3 py-1 rounded-md text-xs transition-colors">表格视图</button>
                <button @click="detailLayout = 'cards'"
                    :class="detailLayout === 'cards' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                    class="px-3 py-1 rounded-md text-xs transition-colors">卡片视图</button>
            </div>
            <input v-model="tableSearch" placeholder="搜索员工ID..."
                class="max-w-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
            <button v-if="detailLayout === 'table' && !isEditing" @click="startEditing"
                class="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm transition-colors">编辑</button>
            <button v-if="detailLayout === 'table' && isEditing" @click="cancelEditing"
                class="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg text-sm transition-colors">取消</button>
            <button v-if="detailLayout === 'table' && isEditing" @click="saveTargets"
                class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm transition-colors">保存</button>
        </div>
```

替换为:

```html
        <!-- 工具栏：面包屑 + 控件组（单行） -->
        <div class="flex-shrink-0 flex items-center gap-3 mb-4 flex-wrap text-sm">
            <!-- 左侧：面包屑 -->
            <a :href="basePath + 'production/detail-data/'" class="text-blue-400 hover:underline">生产详情</a>
            <span class="text-slate-600">/</span>
            <span class="font-semibold">{[ detailTitle ]}</span>
            <span class="text-slate-400">
                👤 {[ detailSummary.worker_count ]}人
                <span v-if="detailSummary.target_total > 0">
                    · 已设目标 {[ detailSummary.targeted_count ]}/{[ detailSummary.worker_count ]}人
                    · 🎯 目标 {[ fmtNum(detailSummary.target_total) ]}
                    · 产值 {[ fmtNum(detailSummary.targeted_qty) ]}
                    · <span :class="detailSummary.efficiency >= 100 ? 'text-emerald-400' : 'text-red-400'">
                        效率 {[ detailSummary.efficiency.toFixed(1) ]}% {[ detailSummary.efficiency >= 100 ? '达标 ✓' : '不达标 ✗' ]}
                    </span>
                </span>
            </span>

            <!-- 右侧：控件组（ml-auto 推到右侧） -->
            <div class="flex items-center gap-3 ml-auto flex-wrap">
                <div class="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
                    <button @click="detailLayout = 'table'"
                        :class="detailLayout === 'table' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                        class="px-3 py-1 rounded-md text-xs transition-colors">表格视图</button>
                    <button @click="detailLayout = 'cards'"
                        :class="detailLayout === 'cards' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-slate-600'"
                        class="px-3 py-1 rounded-md text-xs transition-colors">卡片视图</button>
                </div>
                <!-- 工单筛选下拉（仅 flow 详情显示） — 占位，Task 2 填充 -->
                <select v-if="detailType === 'flow'" v-model="wrkOrderFilter"
                        class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200">
                    <option value="">全部工单</option>
                    <option v-for="wo in workorderOptions" :key="wo" :value="wo">{[ wo ]}</option>
                </select>
                <input v-model="tableSearch" placeholder="搜索员工ID..."
                    class="max-w-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
                <button v-if="detailLayout === 'table' && !isEditing" @click="startEditing"
                    class="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm transition-colors">编辑</button>
                <button v-if="detailLayout === 'table' && isEditing" @click="cancelEditing"
                    class="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg text-sm transition-colors">取消</button>
                <button v-if="detailLayout === 'table' && isEditing" @click="saveTargets"
                    class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm transition-colors">保存</button>
            </div>
        </div>
```

- [ ] **Step 2: 验证 HTML 结构**

确认 Vue 模板语法正确：所有 `{[` `]}` 分隔符、`v-if`、`v-for`、`@click`、`:class` 指令无语法错误。

---

### Task 2: 新增工单筛选相关 Vue 状态和计算属性

**文件:**
- 修改: `iwork/templates/iwork/production_detail.html`（`setup()` 函数内）

- [ ] **Step 1: 在 `setup()` 中添加 `wrkOrderFilter` 和 `workorderOptions`**

在 `const tableSearch = ref('');` 之后添加：

```javascript
const wrkOrderFilter = ref('');  // '' = 全部工单

const workorderOptions = computed(() => {
    const set = new Set();
    employees.value.forEach(emp => {
        (emp.workorders || []).forEach(wo => set.add(wo));
        (emp.steps || []).forEach(s => { if (s.workorder) set.add(s.workorder); });
    });
    return [...set].sort((a, b) => naturalCompare(a, b));
});
```

- [ ] **Step 2: 在 `onMounted` 生命周期中重置工单筛选**

在 `loadDetail` 函数末尾（`loadCardOrder();` 之后），确保切换详情时重置筛选。但更优雅的方式是直接在 `loadDetail` 中重置。找到 `loadDetail` 函数开头处，在 `detailKey.value = key;` 之后添加：

```javascript
wrkOrderFilter.value = '';
```

---

### Task 3: 新增辅助函数和计算属性（左表 + 右表）

**文件:**
- 修改: `iwork/templates/iwork/production_detail.html`（`setup()` 函数内）

- [ ] **Step 1: 添加 `filterByWorkOrder` 辅助函数**

在 `naturalCompare` 函数定义之后添加：

```javascript
// 按工单筛选员工列表
function filterByWorkOrder(emps) {
    if (!wrkOrderFilter.value) return emps;
    return emps.filter(emp => {
        if ((emp.workorders || []).includes(wrkOrderFilter.value)) return true;
        return (emp.steps || []).some(s => s.workorder === wrkOrderFilter.value);
    });
}
```

- [ ] **Step 2: 添加 `stepSummary` 计算属性（左表数据源）**

```javascript
const stepSummary = computed(() => {
    const map = {};
    const emps = filterByWorkOrder(employees.value);
    emps.forEach(emp => {
        (emp.steps || []).forEach(s => {
            if (!wrkOrderFilter.value || s.workorder === wrkOrderFilter.value) {
                map[s.stepno] = (map[s.stepno] || 0) + (s.qty || 0);
            }
        });
    });
    return Object.entries(map)
        .map(([stepno, total]) => ({ stepno: Number(stepno), total }))
        .sort((a, b) => a.stepno - b.stepno);
});
```

> **注意:** 当 `wrkOrderFilter` 非空时，只统计匹配工单的 steps。当为空时统计所有 steps。

- [ ] **Step 3: 添加 `employeeSummary` 计算属性（右表数据源，替代原 `filteredEmployees`）**

在 `stepSummary` 之后添加：

```javascript
const employeeSummary = computed(() => {
    let emps = filterByWorkOrder(employees.value);
    if (tableSearch.value) {
        const q = String(tableSearch.value).toLowerCase();
        emps = emps.filter(e => String(e.reg_per_sys_id).includes(q));
    }
    const key = sortKey.value;
    const asc = sortAsc.value;
    return [...emps].sort((a, b) => {
        let va, vb;
        if (key === 'reg_per_sys_id') {
            va = Number(a.reg_per_sys_id) || 0;
            vb = Number(b.reg_per_sys_id) || 0;
        } else if (key === 'qty') {
            va = a.qty || 0;
            vb = b.qty || 0;
        } else {
            return 0;
        }
        return asc ? va - vb : vb - va;
    });
});
```

- [ ] **Step 4: 移除不再需要的计算属性**

删除以下计算属性定义：

1. `detailStepnos`（第 589-595 行）
2. `filteredEmployees`（第 621-656 行）
3. `getStepQty`（第 597-599 行）
4. `stepnoColumnTotals`（第 602-609 行）
5. `columnGrandTotal`（第 612-614 行）
6. `columnTargetTotal`（第 617-619 行）

---

### Task 4: 替换表格视图 HTML 结构（左右双表）

**文件:**
- 修改: `iwork/templates/iwork/production_detail.html:232-316`（原表格视图 `<div v-if="detailLayout === 'table'">` 整块）

- [ ] **Step 1: 替换表格视图 HTML**

找到第 232-316 行的原表格视图（从 `<!-- ===== 版面1：表格视图 ===== -->` 到 `</div>`），替换为：

```html
        <!-- ===== 版面1：表格视图 — 左右双表汇总 ===== -->
        <div v-if="detailLayout === 'table'" class="flex gap-4 max-lg:flex-col flex-1 overflow-hidden">
            <!-- 左表：工序汇总 -->
            <div class="w-1/2 max-lg:w-full bg-slate-800 border border-slate-700 rounded-lg flex flex-col overflow-hidden">
                <div class="px-4 py-3 border-b border-slate-700 flex-shrink-0">
                    <h3 class="text-sm font-semibold text-slate-300 flex items-center gap-2">
                        <span class="w-2 h-2 bg-blue-500 rounded-full"></span>工序汇总
                    </h3>
                </div>
                <div class="overflow-y-auto flex-1">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-left text-slate-400 border-b border-slate-700">
                                <th class="px-3 py-3 sticky top-0 bg-slate-800 z-10">工序号</th>
                                <th class="px-3 py-3 text-right sticky top-0 bg-slate-800 z-10">总数量</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="s in stepSummary" :key="'step-' + s.stepno" class="border-b border-slate-700 hover:bg-slate-700/50">
                                <td class="py-2 px-3 text-slate-300">工序{[ s.stepno ]}</td>
                                <td class="py-2 px-3 text-emerald-400 font-bold tabular-nums text-right">{[ fmtNum(s.total) ]} 件</td>
                            </tr>
                            <tr v-if="stepSummary.length === 0">
                                <td colspan="2" class="py-4 text-slate-500 text-center">暂无数据</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- 右表：员工汇总（保留编辑目标） -->
            <div class="w-1/2 max-lg:w-full bg-slate-800 border border-slate-700 rounded-lg flex flex-col overflow-hidden">
                <div class="px-4 py-3 border-b border-slate-700 flex-shrink-0 flex items-center justify-between">
                    <h3 class="text-sm font-semibold text-slate-300 flex items-center gap-2">
                        <span class="w-2 h-2 bg-emerald-500 rounded-full"></span>员工汇总
                    </h3>
                    <span class="font-mono text-xs text-slate-400 bg-slate-700 px-2.5 py-1 rounded-full">
                        {[ employeeSummary.length ]} 人
                    </span>
                </div>
                <div class="overflow-y-auto flex-1">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-left text-slate-400 border-b border-slate-700">
                                <th class="px-3 py-3 cursor-pointer select-none hover:text-white sticky top-0 bg-slate-800 z-10"
                                    @click="sortBy('reg_per_sys_id')">
                                    员工ID {[ sortKey === 'reg_per_sys_id' ? (sortAsc ? '▲' : '▼') : '' ]}
                                </th>
                                <th class="px-3 py-3 text-right cursor-pointer select-none hover:text-white sticky top-0 bg-slate-800 z-10"
                                    @click="sortBy('qty')">
                                    总产量 {[ sortKey === 'qty' ? (sortAsc ? '▲' : '▼') : '' ]}
                                </th>
                                <th class="px-3 py-3 sticky top-0 bg-slate-800 z-10">目标</th>
                                <th class="px-3 py-3 text-center sticky top-0 bg-slate-800 z-10">达标</th>
                                <th class="px-3 py-3 text-right sticky top-0 bg-slate-800 z-10">效率</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="emp in employeeSummary" :key="emp.reg_per_sys_id"
                                class="border-b border-slate-700 hover:bg-slate-700/50">
                                <td class="py-2 px-3 text-slate-300">{[ emp.reg_per_sys_id ]}</td>
                                <td class="py-2 px-3 text-emerald-400 font-bold tabular-nums text-right">
                                    {[ fmtNum(emp.qty) ]}
                                </td>
                                <td class="py-2 px-3">
                                    <input v-if="isEditing" v-model.number="draft[emp.reg_per_sys_id]" type="number" min="0"
                                        class="w-16 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-center text-sm tabular-nums">
                                    <span v-else class="tabular-nums">{[ emp.target > 0 ? fmtNum(emp.target) : '--' ]}</span>
                                </td>
                                <td class="py-2 px-3 text-center">
                                    <span v-if="emp.target > 0" :class="emp.qty >= emp.target ? 'text-emerald-400' : 'text-red-400'">
                                        {[ emp.qty >= emp.target ? '✓' : '✗' ]}
                                    </span>
                                    <span v-else class="text-slate-500">--</span>
                                </td>
                                <td class="py-2 px-3 text-right">
                                    <span v-if="emp.target > 0" :class="emp.efficiency >= 100 ? 'text-emerald-400' : 'text-red-400'">
                                        {[ emp.efficiency.toFixed(1) ]}%
                                    </span>
                                    <span v-else class="text-slate-500">--</span>
                                </td>
                            </tr>
                            <tr v-if="employeeSummary.length === 0">
                                <td colspan="5" class="py-4 text-slate-500 text-center">暂无数据</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
```

---

### Task 5: 清理和更新 `return` 语句

**文件:**
- 修改: `iwork/templates/iwork/production_detail.html:1096-1112`（`return` 语句）

- [ ] **Step 1: 更新 `return` 中的导出列表**

将原 `return` 块（第 1096-1112 行）:

```javascript
        return {
            basePath,
            currentView, groupMode, detailType, detailKey, detailLayout,
            cardOrder, dragIndex, activeDrag, dragStyle, orderedEmployees, getStatusColor,
            onPointerDown,
            searchQuery, tableSearch, selectedDate, isLoading, loadingProgress, wsConnected, lastUpdateTime,
            flowCards, stepnoCards, employees, targets,
            detailTitle, detailSummary, detailStepnos, getStepQty,
            stepnoColumnTotals, columnGrandTotal, columnTargetTotal,
            filteredFlowCards, filteredStepnoCards, filteredEmployees,
            isEditing, draft, sortKey, sortAsc,
            sortBy, startEditing, cancelEditing,
            fmtNum, stepColor, loadOverview, loadStepnoOverview, goDetail, saveTargets,
            // 工单列表相关
            workorderList, workorderSummaryList, workorderListRef,
            pauseWorkorderScroll, resumeWorkorderScroll,
        };
```

替换为:

```javascript
        return {
            basePath,
            currentView, groupMode, detailType, detailKey, detailLayout,
            cardOrder, dragIndex, activeDrag, dragStyle, orderedEmployees, getStatusColor,
            onPointerDown,
            searchQuery, tableSearch, wrkOrderFilter, workorderOptions,
            selectedDate, isLoading, loadingProgress, wsConnected, lastUpdateTime,
            flowCards, stepnoCards, employees, targets,
            detailTitle, detailSummary,
            filteredFlowCards, filteredStepnoCards,
            stepSummary, employeeSummary, filterByWorkOrder,
            isEditing, draft, sortKey, sortAsc,
            sortBy, startEditing, cancelEditing,
            fmtNum, stepColor, loadOverview, loadStepnoOverview, goDetail, saveTargets,
            // 工单列表相关
            workorderList, workorderSummaryList, workorderListRef,
            pauseWorkorderScroll, resumeWorkorderScroll,
        };
```

变更说明:
- 新增导出: `wrkOrderFilter`, `workorderOptions`, `stepSummary`, `employeeSummary`, `filterByWorkOrder`
- 移除导出: `detailStepnos`, `getStepQty`, `stepnoColumnTotals`, `columnGrandTotal`, `columnTargetTotal`, `filteredEmployees`

- [ ] **Step 2: 确认 `filterByWorkOrder` 的导出顺序**

由于 `filterByWorkOrder` 是一个函数声明（`function filterByWorkOrder(emps) {...}`），Vue 3 Composition API 中函数声明作用域提升，在 `return` 中可以直接引用。确保 `filterByWorkOrder` 定义在 `return` 语句之前。

---

### Task 6: 提交变更

**文件:**
- 修改: `iwork/templates/iwork/production_detail.html`

- [ ] **Step 1: 启动本地服务验证**

```powershell
cd C:\Users\lipengfei\ZCodeProject\iwork
docker compose -p iwork --env-file .env.local up -d --build
Start-Sleep 5
docker logs DKT_iwork --tail 10
```

打开浏览器访问 `http://localhost:8000/production/detail-data/flow/SO3-L3A/` 验证：
- 工具栏：面包屑和控件在同一行
- 工单下拉：有选项，选择后过滤左侧和右侧数据
- 表格视图：左右双表，工序汇总 + 员工汇总
- 卡片视图：不受影响，照常工作
- 编辑目标：点击编辑后可输入目标值，保存正常

- [ ] **Step 2: 提交**

```powershell
cd C:\Users\lipengfei\ZCodeProject\iwork
git add iwork/templates/iwork/production_detail.html
git commit -m "[2026-07-02][FEAT] 生产详情页 UI 重构：工具栏合并 + 工单筛选 + 左右双表汇总"
```
