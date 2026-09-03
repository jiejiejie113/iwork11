"""生产详情员工系统 ID 到 Remark 员工 ID 的映射规则。"""

from collections import defaultdict
from collections.abc import Iterable, Mapping


def normalize_source_employee_id(value: object) -> str | None:
    """将员工系统 ID 规范化为可稳定查找的字符串键。

    Args:
        value: 远程生产记录中的员工系统 ID。

    Returns:
        str | None: 去除首尾空白后的 ID；空值返回 None。
    """
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_remark(value: object) -> str:
    """将 Remark 规范化为新的员工 ID 文本。

    Args:
        value: pyperson.Remark 原始值。

    Returns:
        str: 去除首尾空白后的 Remark，空值返回空字符串。
    """
    if value is None:
        return ""
    return str(value).strip()


def build_unique_remark_map(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, str]:
    """构建非空且唯一的员工系统 ID 到 Remark 映射。

    重复判断在传入的员工集合内进行；同一个 Remark 对应多个员工系统 ID 时，
    该 Remark 关联的所有员工都会被排除，避免卡片 ID 合并或交换键冲突。

    Args:
        rows: 包含 ``SysID`` 和 ``Remark`` 键的 pyperson 行。

    Returns:
        dict[str, str]: ``SysID`` 字符串到唯一 Remark 的映射。
    """
    owners_by_remark: dict[str, set[str]] = defaultdict(set)
    normalized_rows: list[tuple[str, str]] = []
    for row in rows:
        source_id = normalize_source_employee_id(row.get("SysID"))
        remark = normalize_remark(row.get("Remark"))
        if source_id is None or not remark:
            continue
        owners_by_remark[remark].add(source_id)
        normalized_rows.append((source_id, remark))

    duplicate_remarks = {
        remark
        for remark, source_ids in owners_by_remark.items()
        if len(source_ids) > 1
    }
    return {
        source_id: remark
        for source_id, remark in normalized_rows
        if remark not in duplicate_remarks
    }


def map_employee_rows(
    rows: Iterable[Mapping[str, object]],
    remark_map: Mapping[object, object],
    employee_key: str = "reg_per_sys_id",
) -> list[dict]:
    """使用 Remark 映射员工事实并过滤无效员工。

    Args:
        rows: 含员工系统 ID 的事实行。
        remark_map: 员工系统 ID 到唯一 Remark 的映射。
        employee_key: 事实行中的员工 ID 字段名。

    Returns:
        list[dict]: 仅保留有合法映射的事实副本，并将员工 ID 替换为 Remark。
    """
    normalized_map = {
        source_id: normalize_remark(remark)
        for source, remark in remark_map.items()
        if (source_id := normalize_source_employee_id(source)) is not None
        and normalize_remark(remark)
    }
    mapped_rows = []
    for row in rows:
        source_id = normalize_source_employee_id(row.get(employee_key))
        remark = normalized_map.get(source_id)
        if not remark:
            continue
        mapped_row = dict(row)
        mapped_row[employee_key] = remark
        mapped_rows.append(mapped_row)
    return mapped_rows
