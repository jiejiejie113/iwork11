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


def test_today_production_detail_uses_lightweight_sse_notifications():
    """今日生产详情应由统一快照通知驱动，并按当前视图执行静默刷新。"""
    assert "api/dashboard/stream/?mode=notification" in TEMPLATE
    assert 'function connectProductionDetailSSE()' in TEMPLATE
    assert 'function disconnectProductionDetailSSE()' in TEMPLATE
    assert 'async function handleProductionDetailSnapshot(' in TEMPLATE
    assert "msg.type !== 'snapshot_published'" in TEMPLATE
    assert '? await refreshDetailSilently()' in TEMPLATE
    assert ': await refreshOverviewSilently();' in TEMPLATE
    assert 'const source = new EventSource(url);' in TEMPLATE
    assert 'detailEventSource = source;' in TEMPLATE


def test_production_detail_sse_lease_renewal_avoids_status_flicker():
    """生产详情正常续租不应立即标记断线，真实故障延迟确认。"""
    connection = TEMPLATE.split('function connectProductionDetailSSE() {', 1)[1]
    connection = connection.split('function shouldApplyProductionDetailSnapshot', 1)[0]

    assert 'let detailReconnectWarningTimer = null;' in TEMPLATE
    assert "source.addEventListener('lease_expiring', () => {" in connection
    assert 'if (connectionGeneration !== detailSSEGeneration) return;' in connection
    assert 'if (detailReconnectWarningTimer !== null) return;' in connection
    assert 'SSE_RECONNECT_WARNING_DELAY_MS' in connection
    assert 'source.readyState === EventSource.OPEN' in connection
    assert 'wsConnected.value = false;' in connection


def test_production_detail_sse_is_disabled_for_history_and_replaces_timer():
    """历史日期不得连接 SSE，今日也不再保留浏览器独立的 60 秒刷新计时器。"""
    assert 'if (isHistoricalDate.value) return;' in TEMPLATE.split(
        'function connectProductionDetailSSE()',
        1,
    )[1].split('async function handleProductionDetailSnapshot', 1)[0]
    assert 'disconnectProductionDetailSSE();' in TEMPLATE.split(
        'function changeProductionDate()',
        1,
    )[1].split('async function loadDetail', 1)[0]

    lifecycle = TEMPLATE.split('// 生命周期', 1)[1].split('return {', 1)[0]
    assert 'connectProductionDetailSSE();' in lifecycle
    assert 'disconnectProductionDetailSSE();' in lifecycle
    assert 'setInterval(() =>' not in lifecycle
    assert '60000' not in lifecycle


def test_production_detail_sse_discards_late_today_responses_after_date_change():
    """切换历史日期后，晚到的今日 SSE 刷新不得覆盖历史页面。"""
    detail_refresh = TEMPLATE.split(
        'async function refreshDetailSilently()',
        1,
    )[1].split('// 概览静默刷新', 1)[0]
    overview_refresh = TEMPLATE.split(
        'async function refreshOverviewSilently()',
        1,
    )[1].split('let detailEventSource', 1)[0]
    handler = TEMPLATE.split(
        'async function handleProductionDetailSnapshot',
        1,
    )[1].split('function goDetail', 1)[0]

    assert 'const refreshDate = selectedDate.value;' in detail_refresh
    assert 'detailType.value !== refreshDetailType' in detail_refresh
    assert 'detailKey.value !== refreshDetailKey' in detail_refresh
    assert 'const refreshDate = selectedDate.value;' in overview_refresh
    assert overview_refresh.count("currentView.value !== 'overview'") == 3
    assert overview_refresh.count('groupMode.value !== refreshGroupMode') == 3
    assert 'expectedGeneration !== detailSSEGeneration' in handler
    assert 'const retrySnapshot = pendingDetailSnapshot || nextSnapshot;' in handler
    assert '1 + Math.random() * 0.2' in handler
    assert 'detailRefreshRetryDelayMs * 2' in handler
    assert '60000' in handler


def test_production_detail_sse_advances_to_new_business_date_at_midnight():
    """持续打开的今日页面应随 SSE 通知切换到新的曼谷业务日期。"""
    assert 'const businessToday = ref(businessDateString());' in TEMPLATE
    assert 'function adoptProductionDetailBusinessDate(msg)' in TEMPLATE
    assert 'const wasFollowingToday = selectedDate.value === businessToday.value;' in TEMPLATE
    assert 'businessToday.value = notificationDate;' in TEMPLATE
    assert 'selectedDate.value = notificationDate;' in TEMPLATE
    assert "url.searchParams.set('date', notificationDate);" in TEMPLATE
    assert '!adoptProductionDetailBusinessDate(msg)' in TEMPLATE


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
    assert 'filteredStepnoCards' not in TEMPLATE
    assert 'v-model.trim="initialStyleSearch"' in TEMPLATE
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


def test_worker_card_touch_uses_long_press_without_blocking_scroll_or_click():
    """触摸卡片应长按后排序，普通滑动和点击不得启动拖拽。"""
    assert '.card-wrapper .card.grab { cursor:grab; touch-action:none; }' in TEMPLATE
    assert 'ref="cardViewRef"' in TEMPLATE
    assert ':data-employee-id="emp.reg_per_sys_id"' in TEMPLATE
    assert 'const CARD_LONG_PRESS_DELAY = 500;' in TEMPLATE
    assert 'const CARD_AUTO_SCROLL_EDGE = 72;' in TEMPLATE
    assert 'const CARD_AUTO_SCROLL_MIN_SPEED = 2;' in TEMPLATE
    assert 'const CARD_AUTO_SCROLL_MAX_SPEED = 14;' in TEMPLATE
    assert 'function startCardDrag(' in TEMPLATE
    assert "if (e.pointerType === 'touch') {" in TEMPLATE
    assert "if (e.pointerType === 'touch') return;" not in TEMPLATE
    assert 'cardLongPressTimer = window.setTimeout(' in TEMPLATE
    assert 'CARD_LONG_PRESS_DELAY,' in TEMPLATE
    assert 'function onPendingCardPointerMove' in TEMPLATE
    assert "window.addEventListener('pointermove', onPendingCardPointerMove)" in TEMPLATE
    assert 'scrollCardViewBy(deltaY)' in TEMPLATE
    assert 'function updateCardAutoScroll(' in TEMPLATE
    assert 'function runCardAutoScroll(' in TEMPLATE
    assert 'function updateCardDropTarget(' in TEMPLATE
    assert 'window.requestAnimationFrame(runCardAutoScroll)' in TEMPLATE
    assert 'function cancelPendingCardDrag' in TEMPLATE
    assert '.card-wrapper .card.dragging' in TEMPLATE
    assert 'touch-action: none;' in TEMPLATE
    assert 'if (e.cancelable) e.preventDefault();' in TEMPLATE
    assert "window.addEventListener('pointercancel', onPointerUp);" in TEMPLATE
    assert "window.removeEventListener('pointercancel', onPointerUp);" in TEMPLATE
    assert "window.addEventListener('pointercancel', cancelPendingCardDrag);" in TEMPLATE
    assert "window.removeEventListener('pointercancel', cancelPendingCardDrag);" in TEMPLATE
    assert 'cancelPendingCardDrag();' in TEMPLATE
    assert 'if (activeDrag.value) onPointerUp();' in TEMPLATE

    pending_lifecycle = TEMPLATE.split(
        'function removePendingCardDragListeners()', 1
    )[1].split('function activatePendingCardDrag()', 1)[0]
    assert 'preventDefault' not in pending_lifecycle


def test_flow_table_uses_composite_key_step_rows():
    """Flow 表格应使用复合键工序行。"""
    assert "{ key: 'wrk_order', label: '本厂款号'" in TEMPLATE
    assert "{ key: 'stepno', label: '工序号'" in TEMPLATE
    assert 'row._step.description' in TEMPLATE
    assert 'row._step.step_time' in TEMPLATE
    assert 'row._step.output_value' in TEMPLATE
    assert 'row._woFirst' in TEMPLATE
    assert 'row._empFirst' in TEMPLATE
    assert ':style="detailTableStyle"' in TEMPLATE
    assert ':colspan="Math.max(visibleDetailColumns.length, 1)"' in TEMPLATE
    assert 'max-lg:h-[220px]' in TEMPLATE


def test_flow_table_has_visible_themed_horizontal_scroll_and_drag():
    """Flow 表格应支持可见的主题滚动与拖动。"""
    detail_panel = TEMPLATE.split('<!-- 右侧：员工明细表 -->', 1)[1].split(
        '<!-- ===== 版面2：卡片视图',
        1,
    )[0]
    assert 'detail-table-scroll' in TEMPLATE
    assert 'ref="detailTableScrollRef"' in TEMPLATE
    assert '<div ref="detailTableScrollRef" class="overflow-auto flex-1 detail-table-scroll"' in TEMPLATE
    assert 'flex-1 min-w-0 min-h-0' in detail_panel
    assert 'function onDetailTablePointerDown' in TEMPLATE
    assert 'detailTableEl.scrollLeft = detailTableStartScrollLeft - dx;' in TEMPLATE
    assert 'hide-scrollbar' not in TEMPLATE.split('ref="detailTableScrollRef"', 1)[1].split('<table', 1)[0]


def test_flow_table_supports_persistent_column_configuration():
    """Flow 表格应支持按视图保存列显隐、顺序和宽度。"""
    assert '字段设置' in TEMPLATE
    assert 'detailColumnPanelOpen' in TEMPLATE
    assert 'visibleDetailColumns' in TEMPLATE
    assert 'toggleDetailColumnVisibility' in TEMPLATE
    assert 'startDetailColumnDrag' in TEMPLATE
    assert 'startDetailColumnResize' in TEMPLATE
    assert 'resetDetailColumnPreferences' in TEMPLATE
    assert 'production-detail-columns:v1' in TEMPLATE
    assert 'localStorage.setItem(DETAIL_COLUMN_STORAGE_KEY' in TEMPLATE
    assert 'class="detail-data-table text-sm"' in TEMPLATE
    assert 'class="detail-table-cell"' in TEMPLATE
    assert 'white-space: nowrap;' in TEMPLATE
    assert '.detail-column-list {' in TEMPLATE
    assert 'touch-action: pan-y;' in TEMPLATE
    assert 'displayRowsEmpty && visibleDetailColumns.length > 0' in TEMPLATE


def test_collapsed_flow_table_displays_initial_styles_and_step_numbers():
    """收起视图应按员工汇总去重后的初版款号和工序号。"""
    collapsed_columns = TEMPLATE.split('collapsed: [', 1)[1].split('],', 1)[0]
    expected_keys = [
        'employee_id',
        'collapsed_initial_styles',
        'collapsed_stepnos',
        'employee_qty',
    ]
    positions = [collapsed_columns.index(f"key: '{key}'") for key in expected_keys]
    assert positions == sorted(positions)
    assert "column.key === 'collapsed_initial_styles'" in TEMPLATE
    assert "column.key === 'collapsed_stepnos'" in TEMPLATE
    assert 'emp._collapsed_initial_styles.join' in TEMPLATE
    assert 'emp._collapsed_stepnos.map' in TEMPLATE
    assert 'new Set()' in TEMPLATE


def test_detail_column_cards_animate_hover_drag_and_exchange():
    """字段设置卡片应提供悬停、拖动目标和交换位移动画。"""
    assert '<transition-group name="detail-column"' in TEMPLATE
    assert 'class="detail-column-item' in TEMPLATE
    assert "'is-dragging': draggingDetailColumnKey === column.key" in TEMPLATE
    assert "'is-drop-target': detailColumnHoverKey === column.key" in TEMPLATE
    assert '.detail-column-item:hover {' in TEMPLATE
    assert '.detail-column-item.is-dragging {' in TEMPLATE
    assert '.detail-column-item.is-drop-target {' in TEMPLATE
    assert '.detail-column-move {' in TEMPLATE
    assert 'transition: transform' in TEMPLATE


def test_flow_table_separates_target_rate_and_employee_efficiency():
    """Flow 表格应区分目标达成率和员工效率。"""
    assert "{ key: 'target_rate', label: '目标达成率'" in TEMPLATE
    assert "{ key: 'employee_efficiency', label: '员工效率'" in TEMPLATE
    assert 'row.emp.employee_efficiency' in TEMPLATE
    assert '· 已设目标产量 {[ fmtNum(detailSummary.targeted_qty) ]}' not in TEMPLATE
    assert '· 产值 {[ fmtNum(detailSummary.targeted_qty) ]}' not in TEMPLATE


def test_production_detail_summary_removes_requested_icons_and_fields():
    """生产详情摘要应移除表情符号及不再展示的摘要字段。"""
    assert '👤' not in TEMPLATE
    assert '📦' not in TEMPLATE
    assert '🎯' not in TEMPLATE
    assert 'detailSummary.worker_count' not in TEMPLATE
    assert 'detailSummary.cumulative_qty' not in TEMPLATE
    assert 'detailSummary.targeted_count' not in TEMPLATE
    assert 'detailSummary.targeted_qty' not in TEMPLATE
    assert "'达标 ✓'" not in TEMPLATE
    assert "'不达标 ✗'" not in TEMPLATE


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
    assert "if (['target', 'target_rate'].includes(column.key))" in TEMPLATE
    assert 'return row._targetFirst;' in TEMPLATE
    assert 'return row._targetRowspan;' in TEMPLATE
    assert 'current_group_target' in TEMPLATE


def test_expanded_flow_table_uses_requested_column_order():
    """展开表格的表头和数据单元格应使用指定业务顺序。"""
    expanded_columns = TEMPLATE.split('expanded: [', 1)[1].split('],', 1)[0]
    expected_keys = [
        'employee_id',
        'initial_style',
        'wrk_order',
        'stepno',
        'description',
        'step_qty',
        'cumulative_qty',
        'employee_qty',
        'target',
        'target_rate',
        'step_time',
        'output_value',
        'total_output_value',
        'employee_efficiency',
    ]
    positions = [expanded_columns.index(f"key: '{key}'") for key in expected_keys]
    assert positions == sorted(positions)

    expanded_row = TEMPLATE.split('<!-- 展开模式：员工 + 本厂款号 + 工序组合键明细 -->', 1)[1]
    expanded_row = expanded_row.split('</tr>', 1)[0]
    positions = [expanded_row.index(f"column.key === '{key}'") for key in expected_keys]
    assert positions == sorted(positions)


def test_flow_detail_displays_cumulative_quantity_in_rows():
    """顶部摘要移除累计产量后，展开行和收起员工行仍应展示累计产量。"""
    assert 'fmtNum(row._step.cumulative_qty)' in TEMPLATE
    assert 'fmtNum(emp.cumulative_qty)' in TEMPLATE


def test_step_sidebar_can_switch_between_today_and_cumulative_quantity():
    """左侧工序汇总应默认显示今日产量，并可在展开按钮左侧切换累计产量。"""
    assert "const stepQuantityMode = ref('today');" in TEMPLATE
    assert "stepQuantityMode.value === 'cumulative'" in TEMPLATE
    assert 's.cumulative_qty || 0' in TEMPLATE

    button_start = TEMPLATE.index(
        '@click="stepQuantityMode = stepQuantityMode === \'today\''
    )
    toolbar = TEMPLATE[button_start - 200:button_start + 1000]
    assert (
        'v-if="detailType === \'flow\' || detailType === \'initial_style\'"'
        in toolbar
    )
    assert "@click=\"stepQuantityMode = stepQuantityMode === 'today'" in toolbar
    assert "stepQuantityMode === 'today' ? dailyQtyLabel : '累计产量'" in toolbar
    assert toolbar.index('stepQuantityMode') < toolbar.index('collapsed = !collapsed')
    assert 'map[s.stepno].total += quantity;' in TEMPLATE


def test_step_sidebar_supports_per_detail_drag_order_and_browser_storage():
    """左侧工序列表应使用独立手柄按详情排序并保存到浏览器。"""
    assert "const STEP_ORDER_STORAGE_PREFIX = 'iwork:production-detail:step-order:v1:';" in TEMPLATE
    assert 'const stepOrderDragEnabled = ref(false);' in TEMPLATE
    assert 'v-model="stepOrderDragEnabled"' in TEMPLATE
    assert 'v-if="stepOrderDragEnabled"' in TEMPLATE
    assert 'ref="stepOrderListRef"' in TEMPLATE
    assert 'v-for="s in orderedStepSummary"' in TEMPLATE
    assert 'data-step-order-stepno' in TEMPLATE
    assert 'class="step-order-drag-handle' in TEMPLATE
    assert '@pointerdown.stop="startStepOrderDrag($event, s.stepno)"' in TEMPLATE
    assert '@click="selectedStep = s.stepno"' in TEMPLATE
    assert 'function loadStepOrder(type = detailType.value, key = detailKey.value)' in TEMPLATE
    assert 'function saveStepOrder(order, type = detailType.value, key = detailKey.value)' in TEMPLATE
    assert 'function normalizeStepOrder(values)' in TEMPLATE
    assert 'loadStepOrder(type, key);' in TEMPLATE
    assert 'stepOrder.value = [...stepOrderDragOriginal];' in TEMPLATE
    assert 'saveStepOrder(stepOrder.value, savedType, savedKey);' in TEMPLATE


def test_step_sidebar_keeps_scrolling_and_auto_scroll_during_handle_drag():
    """工序列表普通触控应继续纵向滚动，手柄拖动支持上下沿自动滚动。"""
    assert '.step-order-list {' in TEMPLATE
    assert 'touch-action: pan-y;' in TEMPLATE
    assert '.step-order-drag-handle {' in TEMPLATE
    assert 'touch-action: none;' in TEMPLATE
    assert 'const STEP_ORDER_AUTO_SCROLL_EDGE = 64;' in TEMPLATE
    assert 'function runStepOrderAutoScroll()' in TEMPLATE
    assert 'updateStepOrderDropTarget(' in TEMPLATE
    assert 'stopStepOrderDrag({ pointerId: stepOrderPointerId, type: \'pointercancel\' });' in TEMPLATE
    assert 'delay: 300' in TEMPLATE
    assert 'delayOnTouchOnly: true' in TEMPLATE
    assert 'function onPendingStepOrderDragMove(event)' in TEMPLATE
    assert 'function activatePendingStepOrderDrag()' in TEMPLATE
    assert 'scrollStepOrderListBy(deltaY);' in TEMPLATE
    assert 'event.cancelable' in TEMPLATE


def test_step_drag_toggle_uses_square_theme_and_matches_all_steps_row_height():
    """工序拖拽开关应使用方形主题样式，并与“全部工序”按钮保持同一行高。"""
    assert '.step-order-drag-toggle {' in TEMPLATE
    assert '.step-order-drag-toggle-track {' in TEMPLATE
    assert 'width: 48px;' in TEMPLATE
    assert 'height: 28px;' in TEMPLATE
    assert 'border-radius: 6px;' in TEMPLATE
    assert 'background: #64748b;' in TEMPLATE
    assert 'class="step-order-drag-toggle"' in TEMPLATE
    assert 'class="step-order-drag-toggle-track"' in TEMPLATE
    assert 'class="accent-blue-500"' not in TEMPLATE


def test_step_order_is_used_by_detail_rows_without_changing_card_drag_state():
    """右侧员工明细应读取工序顺序，员工卡片拖拽状态仍保持独立。"""
    assert 'const orderedStepSummary = computed(() => orderStepsByPreference(stepSummary.value));' in TEMPLATE
    assert 'function orderedEmployeeSteps(steps)' in TEMPLATE
    assert TEMPLATE.count('v-for="(s, i) in orderedEmployeeSteps(emp.steps)"') == 2
    assert 'const orderedStepnos = orderStepsByPreference(' in TEMPLATE
    assert '_collapsed_stepnos: orderedStepnos' in TEMPLATE
    assert 'const aStepRank = getStepOrderRank(a.stepno);' in TEMPLATE
    assert 'const bStepRank = getStepOrderRank(b.stepno);' in TEMPLATE
    assert 'const aRank = aFirst ? getStepOrderRank(aFirst.stepno) : undefined;' in TEMPLATE
    assert 'const bRank = bFirst ? getStepOrderRank(bFirst.stepno) : undefined;' in TEMPLATE
    assert 'worker-card-order:${detailType.value}:${detailKey.value}' in TEMPLATE


def test_detail_default_date_uses_business_timezone():
    """详情默认日期应使用业务时区。"""
    assert 'function businessDateString()' in TEMPLATE
    assert "timeZone: 'Asia/Yangon'" in TEMPLATE
    assert "new URLSearchParams(window.location.search).get('date')" in TEMPLATE
    assert 'requestedDate <= businessToday.value' in TEMPLATE
    assert ': businessToday.value;' in TEMPLATE
    assert 'const selectedDate = ref(initialDate);' in TEMPLATE


def test_historical_detail_keeps_date_and_disables_live_actions():
    """历史详情应保留日期并禁用实时操作。"""
    assert '已加载历史数据' in TEMPLATE
    assert 'const isHistoricalDate = computed' in TEMPLATE
    assert 'v-if="canEditCurrentFlow && !isEditing"' in TEMPLATE
    assert "&& !isHistoricalDate" in TEMPLATE
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
    sse_handler = DASHBOARD_TEMPLATE.split('source.onmessage = async (event) => {', 1)[1]
    sse_handler = sse_handler.split('source.onerror = () => {', 1)[0]

    assert 'msg.data.workorders || []' in sse_handler
    assert 'api/dashboard/workorders/' not in sse_handler
    assert "msg.stale ? '已连接（数据更新延迟）'" in sse_handler


def test_sse_rejects_duplicate_or_older_snapshot_events():
    """SSE 重连或并发响应不得用重复、旧快照覆盖较新数据。"""
    assert 'let latestSnapshotVersion = null;' in DASHBOARD_TEMPLATE
    assert 'let latestSnapshotGeneratedAt = null;' in DASHBOARD_TEMPLATE
    assert 'function shouldApplyRealtimeSnapshot(msg)' in DASHBOARD_TEMPLATE
    assert 'if (!shouldApplyRealtimeSnapshot(msg)) return;' in DASHBOARD_TEMPLATE
    connect_handler = DASHBOARD_TEMPLATE.split('function connectSSE() {', 1)[1]
    connect_handler = connect_handler.split('const source = new EventSource(url);', 1)[0]
    assert 'latestSnapshotVersion = null;' in connect_handler
    assert 'latestSnapshotGeneratedAt = null;' in connect_handler


def test_sse_snapshot_unavailable_event_preserves_data_and_waits_for_recovery():
    """命名的快照不可用事件应标记异常，但保留旧数据和长连接。"""
    unavailable_handler = DASHBOARD_TEMPLATE.split(
        "source.addEventListener('snapshot_unavailable', () => {",
        1,
    )[1]
    unavailable_handler = unavailable_handler.split("});", 1)[0]

    assert "wsConnected.value = false;" in unavailable_handler
    assert "wsStatus.value = '实时数据暂不可用，等待恢复...';" in unavailable_handler
    assert "Object.assign(data" not in unavailable_handler
    assert "eventSource.close" not in unavailable_handler


def test_sse_lease_renewal_delays_disconnection_warning_until_reconnect_fails():
    """正常租约续订不应误报断线，只有超时未重连才显示告警。"""
    assert 'const SSE_RECONNECT_WARNING_DELAY_MS = 5000;' in DASHBOARD_TEMPLATE
    assert 'let expectedLeaseReconnect = false;' in DASHBOARD_TEMPLATE
    assert 'let reconnectWarningTimer = null;' in DASHBOARD_TEMPLATE
    assert 'const source = new EventSource(url);' in DASHBOARD_TEMPLATE
    assert 'eventSource = source;' in DASHBOARD_TEMPLATE
    assert 'if (eventSource !== source) return;' in DASHBOARD_TEMPLATE

    lease_handler = DASHBOARD_TEMPLATE.split(
        "source.addEventListener('lease_expiring', () => {",
        1,
    )[1].split("});", 1)[0]
    assert 'expectedLeaseReconnect = true;' in lease_handler
    assert 'wsStatus.value' not in lease_handler
    assert 'wsConnected.value = false;' not in lease_handler
    assert '正在续订连接' not in DASHBOARD_TEMPLATE

    assert 'source.onopen = () => {' in DASHBOARD_TEMPLATE
    open_handler = DASHBOARD_TEMPLATE.split('source.onopen = () => {', 1)[1]
    open_handler = open_handler.split('};', 1)[0]
    assert 'clearReconnectWarning();' in open_handler
    assert 'expectedLeaseReconnect = false;' in open_handler
    assert 'wsConnected.value = true;' in open_handler
    assert "wsStatus.value = '已连接';" in open_handler

    error_handler = DASHBOARD_TEMPLATE.split('source.onerror = () => {', 1)[1]
    error_handler = error_handler.split('};', 1)[0]
    assert 'if (reconnectWarningTimer !== null) return;' in error_handler
    assert 'setTimeout' in error_handler
    assert 'SSE_RECONNECT_WARNING_DELAY_MS' in error_handler
    assert 'source.readyState === EventSource.CLOSED' in error_handler
    assert "'连接已关闭，请刷新页面或重新登录'" in error_handler
    assert "'连接断开，自动重连中...'" in error_handler


def test_historical_production_detail_builds_snapshot_and_hides_update_time():
    """历史生产详情应构建快照并隐藏更新时间。"""
    assert 'api/history/snapshots/${snapshotDate}/ensure/' in TEMPLATE
    assert 'historySnapshotMessage' in TEMPLATE
    assert 'const historySnapshotPromises = new Map();' in TEMPLATE
    assert 'v-if="!isHistoricalDate"' in TEMPLATE
    assert 'const businessToday = ref(businessDateString());' in TEMPLATE
    assert ':max="businessToday"' in TEMPLATE
    assert '快照 v' not in TEMPLATE
    assert 'localStorage.getItem(`targets:${dateStr}`)' not in TEMPLATE


def test_dashboard_workorder_list_uses_business_names_and_initial_style():
    """实时数据列表应显示初版款号，并使用今日/当日业务口径。"""
    list_view = DASHBOARD_TEMPLATE.split('<!-- ========== 第6行：', 1)[1].split(
        '</section>',
        1,
    )[0]

    assert '今日生产列表' in list_view
    assert '>本厂款号</th>' in list_view
    assert '>初版款号</th>' in list_view
    assert '{[ wo.initial_style_no || \'-\' ]}' in list_view
    assert '{[ dailyQtyLabel ]}' in list_view
    assert "const dailyQtyLabel = computed(() =>" in DASHBOARD_TEMPLATE
    assert "currentView.value === 'history' ? '当日产量' : '今日产量'" in DASHBOARD_TEMPLATE


def test_flow_overview_searches_and_displays_initial_styles():
    """Flow 概览应按初版款号部分匹配并显示各款件数。"""
    flow_view = TEMPLATE.split('<!-- Flow 卡片 -->', 1)[1].split(
        '<!-- 工序卡片 -->',
        1,
    )[0]

    assert 'v-model.trim="initialStyleSearch"' in flow_view
    assert 'placeholder="搜索初版款号..."' in flow_view
    assert 'v-for="card in managedFlowCards"' in flow_view
    assert 'v-for="card in otherFlowCards"' in flow_view
    assert 'v-for="style in card.initial_styles"' in flow_view
    assert 'style.initial_style_no || \'未设置\'' in flow_view
    assert 'fmtNum(style.qty)' in flow_view
    assert 'card.stepnos' not in flow_view
    assert 'const filteredFlowCards = computed(() =>' in TEMPLATE


def test_overview_replaces_stepno_grouping_with_initial_style_cards():
    """概览页应以可搜索的初版款号分组替换按工序分组。"""
    toolbar = TEMPLATE.split('<!-- 顶部工具栏 -->', 1)[1].split(
        '<!-- 静默加载条 -->',
        1,
    )[0]
    assert '>按初版款号</button>' in toolbar
    assert '>按工序</button>' not in toolbar
    assert "groupMode = 'initial_style'; loadInitialStyleOverview()" in toolbar
    assert 'v-model.trim="initialStyleOverviewSearch"' in TEMPLATE
    assert 'v-for="card in filteredInitialStyleCards"' in TEMPLATE
    assert "goDetail('initial_style', card.initial_style_no)" in TEMPLATE
    assert '{[ card.label ]}' in TEMPLATE
    assert '{[ card.worker_count || 0 ]}人' in TEMPLATE
    assert '{[ fmtNum(card.total_qty) ]}件' in TEMPLATE
    assert '{[ card.workorder_count ]}个本厂款号' in TEMPLATE
    assert 'v-for="flow in card.flows"' in TEMPLATE
    assert '暂无初版款号数据' in TEMPLATE


def test_overview_cards_show_slowest_step_against_step_average():
    """生产线与初版款号卡片应显示低于工序平均产量的最慢工序。"""
    flow_view = TEMPLATE.split('<!-- Flow 卡片 -->', 1)[1].split(
        '<!-- 工序卡片 -->',
        1,
    )[0]
    initial_style_view = TEMPLATE.split('<!-- 初版款号卡片', 1)[1].split(
        '<!-- 产品模式',
        1,
    )[0]

    for card_view in (flow_view, initial_style_view):
        assert 'slowestStepInfo(card)' in card_view
        assert '最慢工序：工序' in card_view
        assert 'text-red-400' in card_view
        assert '件 ▼' in card_view

    assert 'function slowestStepInfo(card)' in TEMPLATE
    assert 'Object.entries(card.stepnos || {})' in TEMPLATE
    assert 'const averageQty = totalQty / steps.length;' in TEMPLATE
    assert 'Math.round((averageQty - slowest.qty) / averageQty * 100)' in TEMPLATE
    assert 'initialStyleOverviewSearch, slowestStepInfo,' in TEMPLATE


def test_flow_and_initial_style_cards_share_content_structure():
    """生产线与初版款号卡片应使用一致的标题、汇总、分项和最慢工序结构。"""
    flow_view = TEMPLATE.split('<!-- Flow 卡片 -->', 1)[1].split(
        '<!-- 工序卡片 -->',
        1,
    )[0]
    initial_style_view = TEMPLATE.split('<!-- 初版款号卡片', 1)[1].split(
        '<!-- 产品模式',
        1,
    )[0]
    common_classes = [
        'transition-colors flex flex-col',
        'class="font-bold text-lg"',
        'class="text-sm text-slate-400 mt-1"',
        'class="mt-2 text-xs text-slate-400 flex flex-wrap gap-x-3 gap-y-0.5"',
        'border border-cyan-400/80 text-cyan-300 bg-cyan-400/10',
    ]
    for card_view in (flow_view, initial_style_view):
        for class_text in common_classes:
            assert class_text in card_view
        assert '{[ dailyQtyLabel ]}' in card_view
        assert '最慢工序：工序' in card_view

    assert 'fmtNum(card.output_qty)' in flow_view
    assert 'card.initial_styles.length' in flow_view
    assert '个初版款号' in flow_view
    assert 'fmtNum(card.total_qty)' in initial_style_view
    assert 'card.workorder_count' in initial_style_view
    assert '个本厂款号' in initial_style_view
    assert 'card.target_total' in flow_view
    assert 'card.target_total' not in initial_style_view
    assert flow_view.index('slowestStepInfo(card)') < flow_view.index('card.target_total')


def test_flow_card_builder_is_shared_by_initial_load_and_sse_refresh():
    """生产线首次加载和SSE刷新应复用同一卡片构建口径。"""
    assert 'function buildFlowOverviewCards(flowData)' in TEMPLATE
    assert TEMPLATE.count(
        'flowCards.value = buildFlowOverviewCards(flowData);',
    ) == 2
    builder = TEMPLATE.split('function buildFlowOverviewCards(flowData)', 1)[1].split(
        '// API',
        1,
    )[0]
    assert "output_qty: stepnos['70']" in builder
    assert 'total_qty,' in builder
    assert 'initial_styles: info.initial_styles || []' in builder
    assert 'return cards.sort((a, b) => naturalCompare(a.flow, b.flow));' in builder


def test_flow_detail_filters_by_initial_style_and_shows_it_in_rows():
    """Flow 详情应按初版款号筛选，并在表格和卡片中显示该字段。"""
    assert 'const initialStyleFilter = ref(\'\');' in TEMPLATE
    assert 'const initialStyleOptions = computed(() =>' in TEMPLATE
    assert '<option value="">全部初版款号</option>' in TEMPLATE
    assert 'v-model="initialStyleFilter"' in TEMPLATE
    assert 'step.initial_style_no === initialStyleFilter.value' in TEMPLATE
    assert 'const steps = (emp.steps || []).filter' in TEMPLATE
    assert 'qty: steps.reduce' in TEMPLATE
    assert "{ key: 'initial_style', label: '初版款号'" in TEMPLATE
    assert 'row._step.initial_style_no || \'--\'' in TEMPLATE
    assert 's.initial_style_no || \'未设置初版\'' in TEMPLATE


def test_initial_style_detail_has_dedicated_flow_columns_and_data_loading():
    """初版款号详情应使用独立列配置并显示每条工序的生产线。"""
    assert "initial_style_expanded: [" in TEMPLATE
    assert "initial_style_collapsed: [" in TEMPLATE
    style_columns = TEMPLATE.split('initial_style_expanded: [', 1)[1].split('],', 1)[0]
    expected_keys = [
        'employee_id',
        'flow',
        'wrk_order',
        'stepno',
        'description',
        'step_qty',
        'cumulative_qty',
        'employee_qty',
        'target',
        'target_rate',
        'step_time',
        'output_value',
        'total_output_value',
        'employee_efficiency',
    ]
    positions = [style_columns.index(f"key: '{key}'") for key in expected_keys]
    assert positions == sorted(positions)
    assert "column.key === 'flow'" in TEMPLATE
    assert '{[ row._step.flow || \'--\' ]}' in TEMPLATE
    assert "column.key === 'collapsed_flows'" in TEMPLATE
    assert 'emp._collapsed_flows.join' in TEMPLATE
    assert "detailType.value === 'initial_style'" in TEMPLATE
    assert 'api/dashboard/detail/initial-style/?' in TEMPLATE
    assert "detailType.value === 'flow' ? data.group_target : null" in TEMPLATE
    assert (
        'v-if="detailType === \'flow\' && '
        '(detailSummary.group_target !== null || detailSummary.target_total > 0)"'
        in TEMPLATE
    )
    assert "initial_style_expanded: detailColumnPreferences.initial_style_expanded" in TEMPLATE
    assert "initial_style_collapsed: detailColumnPreferences.initial_style_collapsed" in TEMPLATE
    collapsed_columns = TEMPLATE.split(
        'initial_style_collapsed: [',
        1,
    )[1].split('],', 1)[0]
    assert "key: 'displayed_target'" in collapsed_columns
    assert "key: 'displayed_target_rate'" in collapsed_columns
    assert "function getRowStepTarget(row)" in TEMPLATE
    assert "function getRowStepTargetRate(row)" in TEMPLATE
    assert "function getTargetGroupKey(step)" in TEMPLATE
    assert "`${step.flow || ''}::${step.stepno}`" in TEMPLATE


def test_initial_style_detail_is_table_only():
    """初版款号详情应强制使用表格，且不呈现卡片视图入口或内容。"""
    layout_controls = TEMPLATE.split('<!-- 右侧：控件组 -->', 1)[1].split(
        '<input v-model="tableSearch"',
        1,
    )[0]
    load_detail = TEMPLATE.split('async function loadDetail(type, key)', 1)[1].split(
        'async function refreshDetailSilently()',
        1,
    )[0]

    assert '<div v-if="detailType !== \'initial_style\'"' in layout_controls
    assert 'v-if="detailType !== \'initial_style\' && detailLayout === \'cards\'"' in TEMPLATE
    assert "if (type === 'initial_style') detailLayout.value = 'table';" in load_detail


def test_initial_style_detail_reuses_table_controls_with_flow_filter():
    """初版款号表格应提供分组筛选、字段设置和今日/累计产量切换。"""
    table_toolbar = TEMPLATE.split('<!-- 右侧：员工明细表 -->', 1)[1].split(
        '<div ref="detailTableScrollRef"',
        1,
    )[0]

    assert 'const flowFilter = ref(\'\');' in TEMPLATE
    assert 'const flowOptions = computed(() =>' in TEMPLATE
    assert 'v-if="detailType === \'initial_style\'" v-model="flowFilter"' in table_toolbar
    assert '<option value="">全部分组</option>' in table_toolbar
    assert 'v-for="flow in flowOptions"' in table_toolbar
    assert table_toolbar.count(
        "detailType === 'flow' || detailType === 'initial_style'"
    ) == 2
    assert 'step.flow === flowFilter.value' in TEMPLATE


def test_initial_style_views_join_snapshot_sse_refresh_flow():
    """今日初版款号概览和详情应随统一快照刷新，历史日期继续拒绝 SSE。"""
    detail_refresh = TEMPLATE.split(
        'async function refreshDetailSilently()',
        1,
    )[1].split('// 概览静默刷新', 1)[0]
    overview_refresh = TEMPLATE.split(
        'async function refreshOverviewSilently()',
        1,
    )[1].split('let detailEventSource', 1)[0]
    connect_block = TEMPLATE.split(
        'function connectProductionDetailSSE()',
        1,
    )[1].split('async function handleProductionDetailSnapshot', 1)[0]

    assert "refreshDetailType === 'initial_style'" in detail_refresh
    assert 'api/dashboard/detail/initial-style/?' in detail_refresh
    assert "refreshGroupMode === 'initial_style'" in overview_refresh
    assert 'api/dashboard/detail/initial-style-overview/?' in overview_refresh
    assert 'if (isHistoricalDate.value) return;' in connect_block


def test_product_view_exposes_initial_style_as_optional_dimension():
    """产品视图应新增初版款号备选维度，但不改变默认激活层级。"""
    assert "const dimensionPool = ['product', 'initial_style', 'wrk_order', 'stepno', 'flow'];" in TEMPLATE
    assert "const selectedLevels = ref(['product']);" in TEMPLATE
    assert "initial_style: '初版款号'" in TEMPLATE
    assert "if (dim === 'initial_style') return leaf.initial_style_no;" in TEMPLATE
    assert 'initial_style_no: wo.initial_style_no || \'未设置\'' in TEMPLATE


def test_flow_target_inputs_are_visible_before_editing_in_both_layouts():
    """目标和工作时间输入应始终可见，点击编辑后才解除只读。"""
    controls = TEMPLATE.split('<!-- 右侧：控件组 -->', 1)[1].split(
        '</div>\n        </div>',
        1,
    )[0]

    assert controls.count('<label v-if="detailType === \'flow\'"') == 2
    assert '<span class="whitespace-nowrap">整组目标</span>' in controls
    assert '<span class="whitespace-nowrap">工作时间</span>' in controls
    assert 'v-model.number="groupTargetDraft"' in controls
    assert 'v-model.number="workHoursDraft"' in controls
    assert ':readonly="!isEditing"' in controls
    assert "detailType === 'flow' && detailLayout === 'table' && !isEditing" not in controls
    assert "detailType === 'flow' && detailLayout === 'table' && isEditing" not in controls
    assert 'v-if="canEditCurrentFlow && !isEditing"' in controls


def test_account_role_controls_managed_flow_filter_and_target_editing():
    """我管理的分组置顶展示，其余分组带标题分隔，编辑按钮由可信账号职能控制。"""
    assert "我管理的分组" in TEMPLATE
    assert "其余分组" in TEMPLATE
    assert "otherFlowCards" in TEMPLATE
    assert "await loadAccount();" in TEMPLATE
    assert "managedFlowCards" in TEMPLATE
    assert "managedFlowNames.value.includes(detailKey.value)" in TEMPLATE
    assert 'v-if="canEditCurrentFlow && !isEditing"' in TEMPLATE


def test_target_responsibility_status_and_initial_style_targets_are_read_only():
    """Flow责任状态应展示，初版款号仅展示各分组目标而不开放编辑。"""
    assert "targetObligationLabel" in TEMPLATE
    assert "正常提交" in TEMPLATE
    assert "目标已逾期" in TEMPLATE
    assert "逾期补填" in TEMPLATE
    assert "分组目标：" in TEMPLATE
    assert "flowTargets.length" in TEMPLATE
