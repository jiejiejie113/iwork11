from pathlib import Path


TEMPLATE = (
    Path(__file__).parents[1]
    / 'iwork'
    / 'templates'
    / 'iwork'
    / 'production_detail.html'
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


def test_flow_table_separates_target_rate_and_employee_efficiency():
    assert '>目标达成率</th>' in TEMPLATE
    assert '>员工效率</th>' in TEMPLATE
    assert 'row.emp.employee_efficiency' in TEMPLATE
    assert '· 已设目标产量 {[ fmtNum(detailSummary.targeted_qty) ]}' in TEMPLATE
    assert '· 产值 {[ fmtNum(detailSummary.targeted_qty) ]}' not in TEMPLATE


def test_detail_default_date_uses_business_timezone():
    assert 'function businessDateString()' in TEMPLATE
    assert "timeZone: 'Asia/Bangkok'" in TEMPLATE
    assert 'const selectedDate = ref(businessDateString());' in TEMPLATE
    assert "new Date().toISOString().split('T')[0]" not in TEMPLATE
