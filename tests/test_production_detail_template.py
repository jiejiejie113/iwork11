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


def test_product_chart_switches_and_sorts_by_selected_metric():
    """产品图表应按所选指标切换并排序。"""
    assert "const productChartMetric = ref('qty');" in TEMPLATE
    assert "setProductChartMetric('qty')" in TEMPLATE
    assert "setProductChartMetric('output_value')" in TEMPLATE
    assert 'items.sort((a, b) => b.value - a.value)' in TEMPLATE


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
    assert "['qty', 'output_value'].includes(state.productChartMetric)" in TEMPLATE
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


def test_product_chart_uses_compact_height_on_tablet_viewports():
    """平板视口应使用紧凑图表高度。"""
    assert 'class="product-chart-panel ' in TEMPLATE
    assert '@media (min-width: 768px) and (max-width: 1366px)' in TEMPLATE
    assert 'height: clamp(180px, 24vh, 220px);' in TEMPLATE
    assert 'style="height:300px;"' not in TEMPLATE


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
    assert "collapsed ? 'min-w-[780px]' : 'min-w-[1180px]'" in TEMPLATE
    assert ':colspan="collapsed ? 6 : 12"' in TEMPLATE
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
