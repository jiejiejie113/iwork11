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
