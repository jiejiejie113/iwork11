def parse_stepno_filter(request) -> list[int] | None:
    """解析逗号分隔的工序号；无有效值时表示不过滤。"""
    params = getattr(request, 'query_params', request.GET)
    raw = params.get('stepno', '')
    if not raw:
        return None

    stepnos = [int(value) for item in raw.split(',') if (value := item.strip()).isdigit()]
    return stepnos or None
