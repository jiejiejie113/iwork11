from pathlib import Path


TEMPLATE = (
    Path(__file__).parents[1]
    / 'iwork'
    / 'templates'
    / 'iwork'
    / 'production_detail.html'
).read_text(encoding='utf-8')

DASHBOARD_TEMPLATE = (
    Path(__file__).parents[1]
    / 'iwork'
    / 'templates'
    / 'iwork'
    / 'dashboard.html'
).read_text(encoding='utf-8')


def test_step_metadata_uses_dedicated_columns():
    """工序元数据应使用独立列。"""
    assert '>工序描述</div>' in TEMPLATE
    assert '>标准工时</div>' in TEMPLATE
    assert "info += ' · 标准工时 '" not in TEMPLATE


def test_output_value_has_its_own_table_column():
    """产值应使用独立表格列。"""
    assert '>产值</div>' in TEMPLATE
    assert 'row.outputValue' in TEMPLATE


def test_step_metadata_columns_require_both_dimensions():
    """工序元数据列应要求两个维度。"""
    assert 'const showStepMetadataColumns = computed' in TEMPLATE
    assert "selectedLevels.value.includes('wrk_order')" in TEMPLATE
    assert "selectedLevels.value.includes('stepno')" in TEMPLATE


def test_metadata_is_only_populated_when_composite_key_is_resolved():
    """复合键解析成功后才应填充元数据。"""
    assert 'completesStepMetadataPair' in TEMPLATE
    assert 'metadataResolved' in TEMPLATE
    assert "const displayName = curDim === 'stepno' ? '工序' + val : val;" in TEMPLATE


def test_product_metric_controls_tree_sort_and_chart_reuses_tree_order():
    """产品指标应控制树表排序，图表应直接沿用树表顺序。"""
    assert "const productChartMetric = ref('qty');" in TEMPLATE
    assert "setProductChartMetric('qty')" in TEMPLATE
    assert "setProductChartMetric('output_value')" in TEMPLATE
    assert 'function productMetricValue(item, metric)' in TEMPLATE
    assert 'return Number(item[metricKey] ?? 0);' in TEMPLATE
    assert '[...ancestorDims, curDim],' in TEMPLATE
    assert 'sortMetric,' in TEMPLATE
    assert 'nodes.sort((a, b) => a._rawVal - b._rawVal);' in TEMPLATE
    assert 'productMetricValue(b, sortMetric) - productMetricValue(a, sortMetric)' in TEMPLATE

    chart_items = TEMPLATE.split('const productChartItems = computed', 1)[1].split(
        'const productChartLabels',
        1,
    )[0]
    assert 'value: productMetricValue(row, productChartMetric.value)' in chart_items
    assert 'items.sort(' not in chart_items


def test_product_view_displays_and_charts_cumulative_quantity():
    """产品树应显示累计产量，图表切换后沿用树表排序。"""
    product_view = TEMPLATE.split('<!-- 产品模式：图表固定 + 表格可滚动 -->', 1)[1]
    product_view = product_view.split('<!-- ===== 详情页 ===== -->', 1)[0]

    assert "setProductChartMetric('cumulative_qty')" in product_view
    assert '<button v-if="!isHistoricalDate"' in product_view
    assert '>累计产量</div>' in product_view
    assert 'fmtNum(row.cumulativeQty)' in product_view
    assert "['qty', 'cumulative_qty', 'output_value']" in TEMPLATE
    assert 'cumulative_qty: fl.cumulative_qty ?? null' in TEMPLATE
    assert 'const hasCompleteCumulativeQty = groupLeaves.every' in TEMPLATE
    assert 'cumulativeQty: totalCumulativeQty' in TEMPLATE
    assert "cumulative_qty: 'cumulativeQty'" in TEMPLATE
    assert 'const allowedProductChartMetrics = isHistoricalDate.value' in TEMPLATE

    chart_items = TEMPLATE.split('const productChartItems = computed', 1)[1].split(
        'const productChartLabels',
        1,
    )[0]
    assert 'value: productMetricValue(row, productChartMetric.value)' in chart_items
    assert 'items.sort(' not in chart_items


def test_product_chart_resets_cumulative_metric_when_switching_to_history():
    """从今日切换历史日期时，产品图表应回退今日产量指标。"""
    date_change = TEMPLATE.split('function changeProductionDate()', 1)[1].split(
        'async function loadDetail',
        1,
    )[0]

    assert "isHistoricalDate.value && productChartMetric.value === 'cumulative_qty'" in date_change
    assert "productChartMetric.value = 'qty';" in date_change
    assert 'saveProductViewState();' in date_change


def test_product_view_state_is_saved_and_restored_in_browser():
    """产品维度、树路径和图表指标应保存到浏览器并在加载时恢复。"""
    assert "const PRODUCT_VIEW_STORAGE_KEY = 'iwork:production-detail:product-view:v1';" in TEMPLATE
    assert 'function loadProductViewState()' in TEMPLATE
    assert 'function saveProductViewState()' in TEMPLATE
    assert 'selectedLevels: [...selectedLevels.value]' in TEMPLATE
    assert 'activePath: [...activePath.value]' in TEMPLATE
    assert 'productChartMetric: productChartMetric.value' in TEMPLATE
    assert 'loadProductViewState();' in TEMPLATE


def test_product_view_state_rejects_invalid_cache_and_stale_tree_path():
    """非法缓存应回退默认值，失效树路径应在数据加载后截断。"""
    assert 'function normalizeSelectedLevels(levels)' in TEMPLATE
    assert 'dimensionPool.includes(level)' in TEMPLATE
    assert 'allowedProductChartMetrics.includes(state.productChartMetric)' in TEMPLATE
    assert "state.activePath.filter(key => typeof key === 'string')" in TEMPLATE
    assert 'function normalizeProductActivePath()' in TEMPLATE
    assert 'normalizeProductActivePath();' in TEMPLATE


def test_product_chart_rebinds_when_vue_replaces_its_canvas():
    """Vue 重建产品画布后应销毁旧图表并绑定当前画布。"""
    assert "const existingChart = charts['product-chart'];" in TEMPLATE
    assert 'if (existingChart && existingChart.canvas !== canvas)' in TEMPLATE
    assert 'existingChart.destroy();' in TEMPLATE
    assert "charts['product-chart'] = null;" in TEMPLATE


def test_product_silent_refresh_revalidates_state_and_redraws_chart():
    """产品数据静默刷新后应校验树路径并重绘当前图表。"""
    refresh_block = TEMPLATE.split(
        'async function refreshOverviewSilently()',
        maxsplit=1,
    )[1].split('function goDetail', maxsplit=1)[0]
    assert 'normalizeProductActivePath();' in refresh_block
    assert 'saveProductViewState();' in refresh_block
    assert 'renderProductChart();' in refresh_block


def test_silent_refresh_validates_http_responses_before_replacing_state():
    """静默刷新应先拒绝 HTTP 错误，再更新详情或概览数据。"""
    detail_refresh = TEMPLATE.split(
        'async function refreshDetailSilently()',
        maxsplit=1,
    )[1].split('// 概览静默刷新', maxsplit=1)[0]
    overview_refresh = TEMPLATE.split(
        'async function refreshOverviewSilently()',
        maxsplit=1,
    )[1].split('function goDetail', maxsplit=1)[0]

    assert 'const data = await readResponse(resp);' in detail_refresh
    assert 'resp.json()' not in detail_refresh
    assert 'const data = await readResponse(resp);' in overview_refresh
    assert 'const [flowData, woData] = await Promise.all([' in overview_refresh
    assert 'readResponse(flowResp)' in overview_refresh
    assert 'readResponse(woResp)' in overview_refresh
    assert '.json()' not in overview_refresh


def test_product_view_can_toggle_normal_line_filter_locally():
    """产品视图应默认显示普通线，并在浏览器本地切换全部 Flow。"""
    product_view = TEMPLATE.split('<!-- 产品模式：图表固定 + 表格可滚动 -->', 1)[1]
    product_view = product_view.split('<!-- ===== 详情页 ===== -->', 1)[0]
    load_block = TEMPLATE.split('async function loadProductOverview()', 1)[1].split(
        'async function loadDetail',
        1,
    )[0]
    refresh_block = TEMPLATE.split('async function refreshOverviewSilently()', 1)[1].split(
        'function goDetail',
        1,
    )[0]
    toggle_block = TEMPLATE.split('function toggleProductNormalLine()', 1)[1].split(
        'function toggleProductChartPinned',
        1,
    )[0]

    assert 'const productNormalLineOnly = ref(true);' in TEMPLATE
    assert 'const productNormalFlows = ref([]);' in TEMPLATE
    assert '@click="toggleProductNormalLine"' in product_view
    assert '普通线</button>' in product_view
    assert 'const productVisibleLeaves = computed(() => {' in TEMPLATE
    assert 'if (!productNormalLineOnly.value) return leaves;' in TEMPLATE
    assert 'productNormalFlowSet.value.has(leaf.flow)' in TEMPLATE
    assert 'buildGroupedTree(productVisibleLeaves.value' in TEMPLATE
    assert 'productNormalFlows.value = data.normal_flows || [];' in load_block
    assert 'productNormalFlows.value = data.normal_flows || [];' in refresh_block
    assert 'normalizeProductActivePath();' in toggle_block
    assert 'nextTick(() => renderProductChart());' in toggle_block
    assert 'fetch(' not in toggle_block


def test_product_chart_uses_compact_height_on_tablet_viewports():
    """平板视口应使用紧凑图表高度。"""
    assert 'class="product-chart-panel ' in TEMPLATE
    assert '@media (min-width: 768px) and (max-width: 1366px)' in TEMPLATE
    assert 'height: clamp(180px, 24vh, 220px);' in TEMPLATE
    assert 'style="height:300px;"' not in TEMPLATE


def test_product_chart_pin_switches_scroll_owner_and_freezes_tree_header():
    """产品图表固定时仅树表滚动，取消固定后应由整个产品区滚动。"""
    product_view = TEMPLATE.split('<!-- 产品模式：图表固定 + 表格可滚动 -->', 1)[1]
    product_view = product_view.split('<!-- ===== 详情页 ===== -->', 1)[0]

    assert 'const productChartPinned = ref(true);' in TEMPLATE
    assert '@click="toggleProductChartPinned"' in product_view
    assert "productChartPinned ? '取消固定' : '固定图表'" in product_view
    assert 'productRows, productChartMetric, productChartPinned, productChartTitle' in TEMPLATE
    assert 'setProductChartMetric, toggleProductChartPinned, toggleRow' in TEMPLATE
    assert 'data-product-scroll-root' in product_view
    assert "productChartPinned ? 'overflow-hidden' : 'overflow-y-auto'" in product_view
    assert 'data-product-tree-scroll' in product_view
    assert (
        "productChartPinned ? 'flex-1 min-h-0 overflow-auto' : 'overflow-visible'"
        in product_view
    )
    assert 'sticky top-0 z-20' in product_view


def test_product_view_hides_scrollbars_without_disabling_scroll():
    """产品区和树表应只隐藏滚动条外观，并保留原有 overflow 滚动能力。"""
    product_view = TEMPLATE.split('<!-- 产品模式：图表固定 + 表格可滚动 -->', 1)[1]
    product_view = product_view.split('<!-- ===== 详情页 ===== -->', 1)[0]
    product_scroll_root = product_view.split('data-product-scroll-root', 1)[1].split(
        '>',
        1,
    )[0]
    product_tree_scroll = product_view.split('data-product-tree-scroll', 1)[1].split(
        '>',
        1,
    )[0]

    assert 'hide-scrollbar' in product_scroll_root
    assert 'hide-scrollbar' in product_tree_scroll
    assert "productChartPinned ? 'overflow-hidden' : 'overflow-y-auto'" in product_scroll_root
    assert "productChartPinned ? 'flex-1 min-h-0 overflow-auto'" in product_tree_scroll


def test_overview_employee_search_control_is_removed():
    """生产详情概览不应再显示无效的员工ID搜索框。"""
    assert 'v-model="searchQuery"' not in TEMPLATE
    assert "const searchQuery = ref('');" not in TEMPLATE
    assert 'filteredFlowCards' not in TEMPLATE
    assert 'filteredStepnoCards' not in TEMPLATE
    assert 'v-model="tableSearch"' in TEMPLATE


def test_product_dimension_drag_is_frame_throttled_and_composited():
    """产品维度拖动应按帧节流并启用合成。"""
    assert '.dim-tag-wrap .dim-tag, [data-area="activation"] .dim-tag {' in TEMPLATE
    assert 'cursor: grab; touch-action: none;' in TEMPLATE
    assert 'will-change: transform;' in TEMPLATE
    assert 'let tagDragFrame = null;' in TEMPLATE
    assert 'requestAnimationFrame(flushTagPointerMove)' in TEMPLATE
    assert 'translate3d(${dx}px, ${dy}px, 0) scale(1.12)' in TEMPLATE
    assert "window.addEventListener('pointercancel', onTagPointerCancel);" in TEMPLATE
    assert "window.removeEventListener('pointercancel', onTagPointerCancel);" in TEMPLATE
    assert 'if (activeTagDrag.value) onTagPointerCancel();' in TEMPLATE


def test_worker_card_drag_owns_touch_gesture_and_handles_cancel():
    """平板触摸拖动卡片时应阻止原生滚动接管并正确处理取消事件。"""
    assert '.card-wrapper .card.grab { cursor:grab; touch-action:none; }' in TEMPLATE
    assert "window.addEventListener('pointercancel', onPointerUp);" in TEMPLATE
    assert "window.removeEventListener('pointercancel', onPointerUp);" in TEMPLATE
    assert 'if (activeDrag.value) onPointerUp();' in TEMPLATE


def test_flow_table_uses_composite_key_step_rows():
    """Flow 表格应使用复合键工序行。"""
    assert '>本厂款号</th>' in TEMPLATE
    assert '>工序号</th>' in TEMPLATE
    assert 'row._step.description' in TEMPLATE
    assert 'row._step.step_time' in TEMPLATE
    assert 'row._step.output_value' in TEMPLATE
    assert 'row._woFirst' in TEMPLATE
    assert 'row._empFirst' in TEMPLATE
    assert "collapsed ? 'min-w-[860px]' : 'min-w-[1280px]'" in TEMPLATE
    assert ':colspan="collapsed ? 7 : 13"' in TEMPLATE
    assert 'max-lg:h-[220px]' in TEMPLATE


def test_flow_table_has_visible_themed_horizontal_scroll_and_drag():
    """Flow 表格应支持可见的主题滚动与拖动。"""
    assert 'detail-table-scroll' in TEMPLATE
    assert 'ref="detailTableScrollRef"' in TEMPLATE
    assert '<div ref="detailTableScrollRef" class="overflow-auto flex-1 detail-table-scroll"' in TEMPLATE
    assert 'function onDetailTablePointerDown' in TEMPLATE
    assert 'detailTableEl.scrollLeft = detailTableStartScrollLeft - dx;' in TEMPLATE
    assert 'hide-scrollbar' not in TEMPLATE.split('ref="detailTableScrollRef"', 1)[1].split('<table', 1)[0]


def test_flow_table_separates_target_rate_and_employee_efficiency():
    """Flow 表格应区分目标达成率和员工效率。"""
    assert '>目标达成率</th>' in TEMPLATE
    assert '>员工效率</th>' in TEMPLATE
    assert 'row.emp.employee_efficiency' in TEMPLATE
    assert '· 已设目标产量 {[ fmtNum(detailSummary.targeted_qty) ]}' in TEMPLATE
    assert '· 产值 {[ fmtNum(detailSummary.targeted_qty) ]}' not in TEMPLATE


def test_flow_target_uses_one_group_input_and_read_only_allocations():
    """目标编辑应只输入整组值，员工和工序目标由系统分配并只读展示。"""
    assert 'placeholder="整组目标"' in TEMPLATE
    assert 'v-model.number="groupTargetDraft"' in TEMPLATE
    assert "group_target: Number(groupTargetDraft.value)" in TEMPLATE
    assert "flow: detailKey.value" in TEMPLATE
    assert 'v-model.number="woDraft[' not in TEMPLATE
    assert 'v-model.number="draft[' not in TEMPLATE
    assert 'getStepTarget(row.emp, row._step.stepno)' in TEMPLATE
    assert 'getStepTargetRate(row.emp, row._step.stepno)' in TEMPLATE
    assert '目标 {[ fmtNum(s.target) ]}' not in TEMPLATE
    assert 'if (!isEditing.value) groupTargetDraft.value = groupTarget.value || 0;' in TEMPLATE


def test_flow_target_uses_work_hours_and_merges_same_employee_step_cells():
    """工作时长应随整组目标保存，同员工同工序的目标与达成率应合并显示。"""
    assert 'placeholder="工作时间（小时）"' in TEMPLATE
    assert 'v-model.number="workHoursDraft"' in TEMPLATE
    assert 'work_hours: Number(workHoursDraft.value)' in TEMPLATE
    assert 'v-if="row._targetFirst" :rowspan="row._targetRowspan"' in TEMPLATE
    assert 'current_group_target' in TEMPLATE


def test_expanded_flow_table_uses_requested_column_order():
    """展开表格的表头和数据单元格应使用指定业务顺序。"""
    expanded_header = TEMPLATE.split('<template v-if="!collapsed">', 1)[1].split(
        '</template>',
        1,
    )[0]
    expected_headers = [
        '本厂款号',
        '工序号',
        '工序描述',
        '产量',
        '累计产量',
        '总产量',
        '目标',
        '目标达成率',
        '标准工时',
        '产值',
        '总产值',
        '员工效率',
    ]
    positions = [expanded_header.index(header) for header in expected_headers]
    assert positions == sorted(positions)

    expanded_row = TEMPLATE.split('<!-- 展开模式：员工 + 本厂款号 + 工序组合键明细 -->', 1)[1]
    expanded_row = expanded_row.split('</tr>', 1)[0]
    expected_cells = [
        'row._wo_name',
        'row._step.stepno',
        'row._step.description',
        'fmtNum(row._step.qty)',
        'fmtNum(row._step.cumulative_qty)',
        'fmtNum(row._total_qty)',
        'getStepTarget(row.emp, row._step.stepno)',
        'getStepTargetRate(row.emp, row._step.stepno)',
        'fmtStepTime(row._step.step_time)',
        'fmtOutputValue(row._step.output_value)',
        'fmtOutputValue(row.emp.output_value)',
        'row.emp.employee_efficiency',
    ]
    positions = [expanded_row.index(cell) for cell in expected_cells]
    assert positions == sorted(positions)


def test_flow_detail_displays_cumulative_quantity_summary_and_rows():
    """累计产量应在 Flow 顶部、展开行和收起员工行中展示。"""
    assert '· 累计产量 {[ fmtNum(detailSummary.cumulative_qty) ]}' in TEMPLATE
    assert 'fmtNum(row._step.cumulative_qty)' in TEMPLATE
    assert 'fmtNum(emp.cumulative_qty)' in TEMPLATE


def test_step_sidebar_can_switch_between_today_and_cumulative_quantity():
    """左侧工序汇总应默认显示今日产量，并可在展开按钮左侧切换累计产量。"""
    assert "const stepQuantityMode = ref('today');" in TEMPLATE
    assert "stepQuantityMode.value === 'cumulative'" in TEMPLATE
    assert 's.cumulative_qty || 0' in TEMPLATE

    toolbar = TEMPLATE.split('<div class="flex items-center gap-3">', 1)[1].split(
        '</div>',
        1,
    )[0]
    assert 'v-if="detailType === \'flow\'"' in toolbar
    assert "@click=\"stepQuantityMode = stepQuantityMode === 'today'" in toolbar
    assert "stepQuantityMode === 'today' ? '今日产量' : '累计产量'" in toolbar
    assert toolbar.index('stepQuantityMode') < toolbar.index('collapsed = !collapsed')
    assert 'map[s.stepno].total += quantity;' in TEMPLATE


def test_detail_default_date_uses_business_timezone():
    """详情默认日期应使用业务时区。"""
    assert 'function businessDateString()' in TEMPLATE
    assert "timeZone: 'Asia/Bangkok'" in TEMPLATE
    assert "new URLSearchParams(window.location.search).get('date')" in TEMPLATE
    assert 'requestedDate <= businessToday ? requestedDate : businessToday' in TEMPLATE
    assert 'const selectedDate = ref(initialDate);' in TEMPLATE


def test_historical_detail_keeps_date_and_disables_live_actions():
    """历史详情应保留日期并禁用实时操作。"""
    assert '已加载历史数据' in TEMPLATE
    assert 'const isHistoricalDate = computed' in TEMPLATE
    assert "!isEditing && !isHistoricalDate" in TEMPLATE
    assert "if (isHistoricalDate.value) return;" in TEMPLATE
    assert "'?date=' + encodeURIComponent(selectedDate.value)" in TEMPLATE
    assert 'v-if="loadError"' in TEMPLATE
    assert 'payload.error || `请求失败 (${response.status})`' in TEMPLATE
    assert "new Date().toISOString().split('T')[0]" not in TEMPLATE


def test_history_dashboard_auto_builds_snapshots_without_source_controls():
    """历史看板应自动构建快照且不暴露来源切换。"""
    assert '>本地</button>' not in DASHBOARD_TEMPLATE
    assert '>远程</button>' not in DASHBOARD_TEMPLATE
    assert '同步数据' not in DASHBOARD_TEMPLATE
    assert 'currentMode' not in DASHBOARD_TEMPLATE
    assert 'api/history/sync/' not in DASHBOARD_TEMPLATE
    assert 'api/history/snapshots/${snapshotDate}/ensure/' in DASHBOARD_TEMPLATE
    assert 'historySnapshotMessage' in DASHBOARD_TEMPLATE
    assert 'const historySnapshotPromises = new Map();' in DASHBOARD_TEMPLATE
    assert 'let historyLoadSequence = 0;' in DASHBOARD_TEMPLATE
    assert 'historySnapshotError' in DASHBOARD_TEMPLATE
    assert 'const selectedDate = ref(businessDateString(-1));' in DASHBOARD_TEMPLATE
    assert 'const historyMaxDate = businessDateString(-1);' in DASHBOARD_TEMPLATE
    assert ':max="historyMaxDate"' in DASHBOARD_TEMPLATE
    assert '版本 v' not in DASHBOARD_TEMPLATE
    assert "new Date().toISOString().split('T')[0]" not in DASHBOARD_TEMPLATE


def test_sse_uses_embedded_workorders_without_duplicate_request():
    """SSE 更新直接消费同版本工单，不再次请求工单接口。"""
    sse_handler = DASHBOARD_TEMPLATE.split('eventSource.onmessage = async (event) => {', 1)[1]
    sse_handler = sse_handler.split('eventSource.onerror = () => {', 1)[0]

    assert 'msg.data.workorders || []' in sse_handler
    assert 'api/dashboard/workorders/' not in sse_handler
    assert "msg.stale ? '已连接（数据更新延迟）'" in sse_handler


def test_sse_snapshot_unavailable_event_preserves_data_and_waits_for_recovery():
    """命名的快照不可用事件应标记异常，但保留旧数据和长连接。"""
    unavailable_handler = DASHBOARD_TEMPLATE.split(
        "eventSource.addEventListener('snapshot_unavailable', () => {",
        1,
    )[1]
    unavailable_handler = unavailable_handler.split("});", 1)[0]

    assert "wsConnected.value = false;" in unavailable_handler
    assert "wsStatus.value = '实时数据暂不可用，等待恢复...';" in unavailable_handler
    assert "Object.assign(data" not in unavailable_handler
    assert "eventSource.close" not in unavailable_handler


def test_historical_production_detail_builds_snapshot_and_hides_update_time():
    """历史生产详情应构建快照并隐藏更新时间。"""
    assert 'api/history/snapshots/${snapshotDate}/ensure/' in TEMPLATE
    assert 'historySnapshotMessage' in TEMPLATE
    assert 'const historySnapshotPromises = new Map();' in TEMPLATE
    assert 'v-if="!isHistoricalDate"' in TEMPLATE
    assert 'const businessToday = businessDateString();' in TEMPLATE
    assert ':max="businessToday"' in TEMPLATE
    assert '快照 v' not in TEMPLATE
    assert 'localStorage.getItem(`targets:${dateStr}`)' not in TEMPLATE
