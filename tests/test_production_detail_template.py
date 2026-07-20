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
    assert '>工序描述</div>' in TEMPLATE
    assert '>标准工时</div>' in TEMPLATE
    assert "info += ' · 标准工时 '" not in TEMPLATE


def test_output_value_has_its_own_table_column():
    assert '>产值</div>' in TEMPLATE
    assert 'row.outputValue' in TEMPLATE


def test_step_metadata_columns_require_both_dimensions():
    assert 'const showStepMetadataColumns = computed' in TEMPLATE
    assert "selectedLevels.value.includes('wrk_order')" in TEMPLATE
    assert "selectedLevels.value.includes('stepno')" in TEMPLATE


def test_metadata_is_only_populated_when_composite_key_is_resolved():
    assert 'completesStepMetadataPair' in TEMPLATE
    assert 'metadataResolved' in TEMPLATE
    assert "const displayName = curDim === 'stepno' ? '工序' + val : val;" in TEMPLATE


def test_product_chart_switches_and_sorts_by_selected_metric():
    assert "const productChartMetric = ref('qty');" in TEMPLATE
    assert "setProductChartMetric('qty')" in TEMPLATE
    assert "setProductChartMetric('output_value')" in TEMPLATE
    assert 'items.sort((a, b) => b.value - a.value)' in TEMPLATE


def test_product_chart_uses_compact_height_on_tablet_viewports():
    assert 'class="product-chart-panel ' in TEMPLATE
    assert '@media (min-width: 768px) and (max-width: 1366px)' in TEMPLATE
    assert 'height: clamp(180px, 24vh, 220px);' in TEMPLATE
    assert 'style="height:300px;"' not in TEMPLATE


def test_flow_table_uses_composite_key_step_rows():
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
    assert 'detail-table-scroll' in TEMPLATE
    assert 'ref="detailTableScrollRef"' in TEMPLATE
    assert '<div ref="detailTableScrollRef" class="overflow-auto flex-1 detail-table-scroll"' in TEMPLATE
    assert 'function onDetailTablePointerDown' in TEMPLATE
    assert 'detailTableEl.scrollLeft = detailTableStartScrollLeft - dx;' in TEMPLATE
    assert 'hide-scrollbar' not in TEMPLATE.split('ref="detailTableScrollRef"', 1)[1].split('<table', 1)[0]


def test_flow_table_separates_target_rate_and_employee_efficiency():
    assert '>目标达成率</th>' in TEMPLATE
    assert '>员工效率</th>' in TEMPLATE
    assert 'row.emp.employee_efficiency' in TEMPLATE
    assert '· 已设目标产量 {[ fmtNum(detailSummary.targeted_qty) ]}' in TEMPLATE
    assert '· 产值 {[ fmtNum(detailSummary.targeted_qty) ]}' not in TEMPLATE


def test_detail_default_date_uses_business_timezone():
    assert 'function businessDateString()' in TEMPLATE
    assert "timeZone: 'Asia/Bangkok'" in TEMPLATE
    assert "new URLSearchParams(window.location.search).get('date')" in TEMPLATE
    assert 'requestedDate <= businessToday ? requestedDate : businessToday' in TEMPLATE
    assert 'const selectedDate = ref(initialDate);' in TEMPLATE


def test_historical_detail_keeps_date_and_disables_live_actions():
    assert '已加载历史数据' in TEMPLATE
    assert 'const isHistoricalDate = computed' in TEMPLATE
    assert "!isEditing && !isHistoricalDate" in TEMPLATE
    assert "if (isHistoricalDate.value) return;" in TEMPLATE
    assert "'?date=' + encodeURIComponent(selectedDate.value)" in TEMPLATE
    assert 'v-if="loadError"' in TEMPLATE
    assert 'payload.error || `请求失败 (${response.status})`' in TEMPLATE
    assert "new Date().toISOString().split('T')[0]" not in TEMPLATE


def test_history_dashboard_auto_builds_snapshots_without_source_controls():
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


def test_historical_production_detail_builds_snapshot_and_hides_update_time():
    assert 'api/history/snapshots/${snapshotDate}/ensure/' in TEMPLATE
    assert 'historySnapshotMessage' in TEMPLATE
    assert 'const historySnapshotPromises = new Map();' in TEMPLATE
    assert 'v-if="!isHistoricalDate"' in TEMPLATE
    assert 'const businessToday = businessDateString();' in TEMPLATE
    assert ':max="businessToday"' in TEMPLATE
    assert '快照 v' not in TEMPLATE
    assert 'localStorage.getItem(`targets:${dateStr}`)' not in TEMPLATE
