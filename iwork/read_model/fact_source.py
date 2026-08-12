"""从单次采集的不可变基础事实生成实时读模型查询结果。"""

from collections import defaultdict
from datetime import date, timedelta

from django.conf import settings

from iwork.queries import _build_flow_employees


# ======
# 事实筛选配置
ALLOWED_FLOWS = frozenset(settings.ALLOWED_FLOWS)
ALLOWED_FLOWS_STEPNO = settings.ALLOWED_FLOWS_STEPNO


class ReadModelFactSource:
    """提供与现有统计构建器兼容的内存事实查询接口。"""

    @classmethod
    def collect(cls, business_date: date, source=None) -> "ReadModelFactSource":
        """从远程生产库单次采集基础事实并加载只读补充信息。

        Args:
            business_date: 需要采集的曼谷业务日期。
            source: 远程查询模块兼容适配器；默认使用 ``iwork.queries``。

        Returns:
            ReadModelFactSource: 本轮不可变事实查询适配器。
        """
        if source is None:
            from iwork import queries as source

        with source.read_model_consistent_snapshot():
            facts = source.get_read_model_fact_rows(business_date)
            wrk_orders = sorted({
                str(item.get("wrk_order") or "")
                for item in facts
                if item.get("wrk_order")
            })
            cumulative_facts = source.get_read_model_cumulative_rows(
                wrk_orders,
            )
            products = source.get_read_model_products(wrk_orders)
            initial_styles = source.get_initial_style_numbers(wrk_orders)
            for wrk_order in wrk_orders:
                product = products.setdefault(
                    wrk_order,
                    {"product_name": "", "order_no": ""},
                )
                product["initial_style_no"] = initial_styles.get(wrk_order, "")
            step_metadata = source.get_batch_step_metadata(wrk_orders)
        return cls(
            business_date=business_date,
            facts=facts,
            cumulative_facts=cumulative_facts,
            products=products,
            step_metadata=step_metadata,
            history_source=source,
        )

    def __init__(
        self,
        business_date: date,
        facts: list[dict],
        cumulative_facts: list[dict] | None = None,
        products: dict | None = None,
        step_metadata: dict | None = None,
        history_source=None,
    ) -> None:
        """初始化单次采集事实源。

        Args:
            business_date: 事实所属的曼谷业务日期。
            facts: 单次远程查询返回的细粒度生产事实。
            cumulative_facts: 按当前明细粒度汇总的累计生产事实。
            products: 按完整工单号组织的本地产品信息。
            step_metadata: 按工单和工序组织的描述与标准工时。
            history_source: 只用于读取业务日期之前月度数据的查询适配器。
        """
        self.business_date = business_date
        self.facts = tuple(dict(item) for item in facts)
        self.cumulative_facts = tuple(dict(item) for item in cumulative_facts or [])
        self.cumulative_qty = {
            (
                str(item.get("flow") or ""),
                item.get("reg_per_sys_id"),
                int(item.get("stepno") or 0),
                str(item.get("wrk_order") or ""),
            ): int(item.get("cumulative_qty") or 0)
            for item in self.cumulative_facts
        }
        self.products = dict(products or {})
        self.step_metadata = dict(step_metadata or {})
        self.history_source = history_source

    def _realtime_facts(self) -> list[dict]:
        """返回应用实时 Flow 白名单规则后的事实。

        Returns:
            list[dict]: 实时统计允许使用的事实行。
        """
        return [
            item
            for item in self.facts
            if self._stepno(item) != ALLOWED_FLOWS_STEPNO
            or self._flow(item) in ALLOWED_FLOWS
        ]

    def _detail_facts(self) -> list[dict]:
        """返回生产详情允许展示的 Flow 事实。

        Returns:
            list[dict]: 生产详情白名单内的事实行。
        """
        return [item for item in self.facts if self._flow(item) in ALLOWED_FLOWS]

    def _product_facts(self) -> list[dict]:
        """返回产品视图使用的全部 Flow 事实。

        Returns:
            list[dict]: 未应用普通线白名单的产品生产事实。
        """
        return list(self.facts)

    @staticmethod
    def _stepno(item: dict) -> int:
        """规范化事实中的工序号。

        Args:
            item: 单条生产事实。

        Returns:
            int: 整数工序号，空值按零处理。
        """
        return int(item.get("stepno") or 0)

    @staticmethod
    def _qty(item: dict) -> int:
        """规范化事实中的产量。

        Args:
            item: 单条生产事实。

        Returns:
            int: 整数产量，空值按零处理。
        """
        return int(item.get("qty") or 0)

    @staticmethod
    def _flow(item: dict) -> str:
        """规范化事实中的 Flow。

        Args:
            item: 单条生产事实。

        Returns:
            str: Flow 名称，空值按空字符串处理。
        """
        return str(item.get("flow") or "")

    def get_batch_basic_stats(self, _target_date: date) -> dict:
        """从事实计算每个工序的总量和工单数。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 按工序组织的总量和去重工单数。
        """
        totals: dict[int, int] = defaultdict(int)
        workorders: dict[int, set[str]] = defaultdict(set)
        for item in self._realtime_facts():
            stepno = self._stepno(item)
            totals[stepno] += self._qty(item)
            if item.get("wrk_order") is not None:
                workorders[stepno].add(str(item.get("wrk_order")))
        return {
            stepno: {
                "total_qty": qty,
                "workorder_count": len(workorders[stepno]),
            }
            for stepno, qty in totals.items()
        }

    def get_batch_hourly_stats(self, _target_date: date) -> dict:
        """从事实计算每个工序的小时趋势。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 按工序组织的小时产量行。
        """
        totals: dict[tuple[int, int | None], int] = defaultdict(int)
        for item in self._realtime_facts():
            totals[(self._stepno(item), item.get("event_hour"))] += self._qty(item)
        result: dict[int, list[dict]] = defaultdict(list)
        for (stepno, hour), qty in sorted(
            totals.items(),
            key=lambda value: (value[0][0], value[0][1] is None, value[0][1] or 0),
        ):
            result[stepno].append({"hour": hour, "qty": qty})
        return dict(result)

    def get_batch_process_by_flow(self, _target_date: date) -> dict:
        """从事实计算工序与 Flow 产量。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 按工序组织的 Flow 产量行。
        """
        totals: dict[tuple[int, str], int] = defaultdict(int)
        for item in self._realtime_facts():
            flow = self._flow(item)
            if flow:
                totals[(self._stepno(item), flow)] += self._qty(item)
        result: dict[int, list[dict]] = defaultdict(list)
        for (stepno, flow), qty in totals.items():
            result[stepno].append({"step": stepno, "flow": flow, "qty": qty})
        for rows in result.values():
            rows.sort(key=lambda row: (-row["qty"], row["flow"]))
        return dict(result)

    def get_batch_station_ranking(
        self,
        _target_date: date,
        limit: int = 10,
    ) -> dict:
        """从事实计算每个工序的工站排行。

        Args:
            _target_date: 兼容查询接口的业务日期。
            limit: 每个工序最多返回的工站数量。

        Returns:
            dict: 按工序组织的工站排行。
        """
        totals: dict[tuple[int, str], int] = defaultdict(int)
        for item in self._realtime_facts():
            flow = self._flow(item)
            station_id = str(item.get("station_id") or "")
            if not flow or not station_id:
                continue
            station = f"({flow})[{station_id}]"
            totals[(self._stepno(item), station)] += self._qty(item)
        result: dict[int, list[dict]] = defaultdict(list)
        for (stepno, station), qty in totals.items():
            result[stepno].append({"station": station, "qty": qty})
        for stepno, rows in result.items():
            result[stepno] = sorted(
                rows,
                key=lambda row: (-row["qty"], row["station"]),
            )[:limit]
        return dict(result)

    def get_batch_workorders_list(
        self,
        _target_date: date,
        limit: int = 20,
    ) -> dict:
        """从事实计算每个工序的高产工单列表。

        Args:
            _target_date: 兼容查询接口的业务日期。
            limit: 每个工序最多返回的工单数量。

        Returns:
            dict: 按工序组织的高产工单列表。
        """
        totals: dict[tuple[int, str], int] = defaultdict(int)
        flows: dict[tuple[int, str], set[str]] = defaultdict(set)
        for item in self._realtime_facts():
            stepno = self._stepno(item)
            wrk_order = str(item.get("wrk_order") or "")
            totals[(stepno, wrk_order)] += self._qty(item)
            flows[(stepno, wrk_order)].add(self._flow(item))
        result: dict[int, list[dict]] = defaultdict(list)
        for (stepno, wrk_order), qty in totals.items():
            product = self.products.get(wrk_order, {})
            result[stepno].append({
                "wrk_order": wrk_order,
                "total_qty": qty,
                "flows": sorted(flows[(stepno, wrk_order)]),
                "product_name": product.get("product_name", ""),
                "order_no": product.get("order_no", ""),
                "initial_style_no": product.get("initial_style_no", ""),
            })
        for stepno, rows in result.items():
            result[stepno] = sorted(
                rows,
                key=lambda row: (-row["total_qty"], row["wrk_order"]),
            )[:limit]
        return dict(result)

    def _history_rows(
        self,
        method_name: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        """读取业务日期之前的月度历史聚合。

        Args:
            method_name: 历史查询适配器的方法名称。
            start_date: 月度历史开始日期。
            end_date: 请求结束日期。

        Returns:
            dict: 不包含当前业务日的历史聚合。
        """
        history_end = min(end_date, self.business_date - timedelta(days=1))
        if self.history_source is None or start_date > history_end:
            return {}
        method = getattr(self.history_source, method_name)
        return method(start_date, history_end)

    @staticmethod
    def _merge_monthly_rows(history: dict, today: dict) -> dict:
        """合并历史月度行和本轮事实派生的今日行。

        Args:
            history: 当前业务日之前的月度聚合。
            today: 从本轮事实派生的今日聚合。

        Returns:
            dict: 按工序组织的完整月度聚合。
        """
        result = {stepno: [dict(row) for row in rows] for stepno, rows in history.items()}
        for stepno, rows in today.items():
            result.setdefault(stepno, []).extend(dict(row) for row in rows)
        return result

    def get_batch_monthly_total_trend(
        self,
        start_date: date,
        end_date: date,
    ) -> dict:
        """合并历史日期与本轮事实生成的今日月趋势。

        Args:
            start_date: 请求开始日期。
            end_date: 请求结束日期。

        Returns:
            dict: 按工序组织的每日总产量趋势。
        """
        history = self._history_rows(
            "get_batch_monthly_total_trend",
            start_date,
            end_date,
        )
        today: dict[int, list[dict]] = {}
        if start_date <= self.business_date <= end_date:
            basic = self.get_batch_basic_stats(self.business_date)
            today = {
                stepno: [{"date": self.business_date.isoformat(), "qty": row["total_qty"]}]
                for stepno, row in basic.items()
            }
        return self._merge_monthly_rows(history, today)

    def get_batch_monthly_process_stats(
        self,
        start_date: date,
        end_date: date,
    ) -> dict:
        """合并历史日期与本轮事实生成的今日工序月统计。

        Args:
            start_date: 请求开始日期。
            end_date: 请求结束日期。

        Returns:
            dict: 按工序组织的每日工序产量。
        """
        history = self._history_rows(
            "get_batch_monthly_process_stats",
            start_date,
            end_date,
        )
        today: dict[int, list[dict]] = {}
        if start_date <= self.business_date <= end_date:
            basic = self.get_batch_basic_stats(self.business_date)
            today = {
                stepno: [{
                    "date": self.business_date.isoformat(),
                    "step": stepno,
                    "qty": row["total_qty"],
                }]
                for stepno, row in basic.items()
            }
        return self._merge_monthly_rows(history, today)

    def get_batch_monthly_hourly_stats(
        self,
        start_date: date,
        end_date: date,
    ) -> dict:
        """合并历史日期与本轮事实生成的今日小时月统计。

        Args:
            start_date: 请求开始日期。
            end_date: 请求结束日期。

        Returns:
            dict: 按工序组织的每日小时产量。
        """
        history = self._history_rows(
            "get_batch_monthly_hourly_stats",
            start_date,
            end_date,
        )
        today: dict[int, list[dict]] = {}
        if start_date <= self.business_date <= end_date:
            hourly = self.get_batch_hourly_stats(self.business_date)
            today = {
                stepno: [
                    {
                        "date": self.business_date.isoformat(),
                        "hour": row["hour"],
                        "qty": row["qty"],
                    }
                    for row in rows
                    if row["hour"] is not None
                ]
                for stepno, rows in hourly.items()
            }
        return self._merge_monthly_rows(history, today)

    def get_batch_flow_overview(self, _target_date: date) -> dict:
        """从事实生成生产详情 Flow 概览。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: Flow 下各工序产量、人数和总人数。
        """
        qty: dict[tuple[str, int], int] = defaultdict(int)
        workers: dict[tuple[str, int], set] = defaultdict(set)
        total_workers: dict[str, set] = defaultdict(set)
        initial_style_qty: dict[tuple[str, str], int] = defaultdict(int)
        for item in self._detail_facts():
            flow = self._flow(item)
            stepno = self._stepno(item)
            employee_id = item.get("reg_per_sys_id")
            qty[(flow, stepno)] += self._qty(item)
            if employee_id is not None:
                workers[(flow, stepno)].add(employee_id)
                total_workers[flow].add(employee_id)
            wrk_order = str(item.get("wrk_order") or "")
            initial_style_no = str(
                self.products.get(wrk_order, {}).get("initial_style_no") or ""
            )
            style_key = (flow, initial_style_no)
            initial_style_qty.setdefault(style_key, 0)
            if stepno == ALLOWED_FLOWS_STEPNO:
                initial_style_qty[style_key] += self._qty(item)
        result: dict[str, dict] = {}
        for flow, stepno in sorted(qty):
            row = result.setdefault(flow, {"stepnos": {}, "total_workers": 0})
            row["stepnos"][str(stepno)] = {
                "qty": qty[(flow, stepno)],
                "workers": len(workers[(flow, stepno)]),
            }
            row["total_workers"] = len(total_workers[flow])
        for flow, row in result.items():
            initial_styles = [
                {"initial_style_no": initial_style_no, "qty": qty_value}
                for (style_flow, initial_style_no), qty_value in initial_style_qty.items()
                if style_flow == flow
            ]
            initial_styles.sort(
                key=lambda item: (-item["qty"], item["initial_style_no"]),
            )
            row["initial_styles"] = initial_styles
        return result

    def get_batch_flow_hourly(self, _target_date: date) -> dict:
        """从事实生成生产详情 Flow 小时趋势。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 按 Flow 组织的小时产量趋势。
        """
        totals: dict[tuple[str, int | None], int] = defaultdict(int)
        for item in self._detail_facts():
            totals[(self._flow(item), item.get("event_hour"))] += self._qty(item)
        result: dict[str, list[dict]] = defaultdict(list)
        for (flow, hour), qty in sorted(
            totals.items(),
            key=lambda value: (value[0][0], value[0][1] is None, value[0][1] or 0),
        ):
            result[flow].append({"hour": hour, "qty": qty})
        return dict(result)

    def get_batch_flow_employees(self, _target_date: date) -> dict:
        """从事实生成每个 Flow 的员工与工序明细。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 按 Flow 组织的员工、工序和产值明细。
        """
        totals: dict[tuple[str, object, int, str], int] = defaultdict(int)
        for item in self._detail_facts():
            key = (
                self._flow(item),
                item.get("reg_per_sys_id"),
                self._stepno(item),
                str(item.get("wrk_order") or ""),
            )
            totals[key] += self._qty(item)
        rows = [
            {
                "Flow": flow,
                "RegPerSysID": employee_id,
                "StepNo": stepno,
                "WrkOrder": wrk_order,
                "qty": qty,
                "cumulative_qty": self.cumulative_qty.get(
                    (flow, employee_id, stepno, wrk_order),
                    0,
                ),
            }
            for (flow, employee_id, stepno, wrk_order), qty in sorted(
                totals.items(),
                key=lambda value: (value[0][0], str(value[0][1]), value[0][2], value[0][3]),
            )
        ]
        return _build_flow_employees(rows, self.step_metadata, self.products)

    def get_batch_stepno_employees(self, _target_date: date) -> dict:
        """从事实生成每个工序的员工明细。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 按工序组织的员工产量和 Flow 列表。
        """
        totals: dict[tuple[int, object, str], int] = defaultdict(int)
        for item in self._detail_facts():
            totals[(
                self._stepno(item),
                item.get("reg_per_sys_id"),
                self._flow(item),
            )] += self._qty(item)
        employee_map: dict[int, dict[object, dict]] = defaultdict(dict)
        for (stepno, employee_id, flow), qty in sorted(
            totals.items(),
            key=lambda value: (value[0][0], str(value[0][1]), value[0][2]),
        ):
            employee = employee_map[stepno].setdefault(
                employee_id,
                {"qty": 0, "flows": []},
            )
            employee["qty"] += qty
            employee["flows"].append(flow)
        result = {}
        for stepno, employees in employee_map.items():
            result[stepno] = sorted(
                [
                    {
                        "reg_per_sys_id": employee_id,
                        "qty": values["qty"],
                        "flows": sorted(values["flows"]),
                    }
                    for employee_id, values in employees.items()
                ],
                key=lambda row: row["qty"],
                reverse=True,
            )
        return result

    def get_batch_product_overview(self, _target_date: date) -> dict:
        """从事实生成按产品名称组织的四层生产详情。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: 产品、工单、工序和 Flow 四层生产详情。
        """
        grouped: dict[tuple[str, int, str], dict] = {}
        for item in self._product_facts():
            wrk_order = str(item.get("wrk_order") or "")
            stepno = self._stepno(item)
            flow = self._flow(item)
            row = grouped.setdefault(
                (wrk_order, stepno, flow),
                {"qty": 0, "cumulative_qty": 0, "workers": set()},
            )
            row["qty"] += self._qty(item)
            if item.get("reg_per_sys_id") is not None:
                row["workers"].add(item.get("reg_per_sys_id"))

        current_wrk_orders = {wrk_order for wrk_order, _stepno, _flow in grouped}
        for item in self.cumulative_facts:
            wrk_order = str(item.get("wrk_order") or "")
            flow = self._flow(item)
            if wrk_order not in current_wrk_orders:
                continue
            stepno = self._stepno(item)
            row = grouped.setdefault(
                (wrk_order, stepno, flow),
                {"qty": 0, "cumulative_qty": 0, "workers": set()},
            )
            row["cumulative_qty"] += int(item.get("cumulative_qty") or 0)

        product_map: dict[str, dict] = {}
        for (wrk_order, stepno, flow), values in sorted(grouped.items()):
            product = self.products.get(wrk_order, {})
            product_name = str(product.get("product_name") or "未分类")
            order_no = str(product.get("order_no") or "")
            product_row = product_map.setdefault(
                product_name,
                {"order_no": order_no, "workorders": {}},
            )
            workorders = product_row["workorders"]
            steps = workorders.setdefault(wrk_order, {})
            flows = steps.setdefault(stepno, {})
            flows[flow] = {
                "flow": flow,
                "qty": values["qty"],
                "cumulative_qty": values["cumulative_qty"],
                "workers": len(values["workers"]),
            }

        products = []
        unclassified = None
        for product_name, product_row in product_map.items():
            order_no = product_row["order_no"]
            workorders = product_row["workorders"]
            workorder_rows = []
            for wrk_order, steps in workorders.items():
                step_rows = []
                for stepno, flows in steps.items():
                    flow_rows = sorted(
                        flows.values(),
                        key=lambda row: row["qty"],
                        reverse=True,
                    )
                    qty = sum(row["qty"] for row in flow_rows)
                    metadata = self.step_metadata.get((wrk_order, stepno), {})
                    step_time = metadata.get("step_time")
                    step_rows.append({
                        "stepno": stepno,
                        "description": metadata.get("description", ""),
                        "step_time": step_time,
                        "output_value": qty * step_time if step_time is not None else None,
                        "qty": qty,
                        "cumulative_qty": sum(
                            row["cumulative_qty"] for row in flow_rows
                        ),
                        "workers": sum(row["workers"] for row in flow_rows),
                        "flows": flow_rows,
                    })
                step_rows.sort(key=lambda row: row["stepno"])
                workorder_rows.append({
                    "wrk_order": wrk_order,
                    "initial_style_no": self.products.get(
                        wrk_order,
                        {},
                    ).get("initial_style_no", ""),
                    "qty": sum(row["qty"] for row in step_rows),
                    "cumulative_qty": sum(
                        row["cumulative_qty"] for row in step_rows
                    ),
                    "stepno_count": len(step_rows),
                    "stepnos": step_rows,
                })
            workorder_rows.sort(key=lambda row: row["qty"], reverse=True)
            result_row = {
                "product_name": product_name,
                "order_no": order_no,
                "total_qty": sum(row["qty"] for row in workorder_rows),
                "cumulative_qty": sum(
                    row["cumulative_qty"] for row in workorder_rows
                ),
                "wrk_order_count": len(workorder_rows),
                "wrk_orders": workorder_rows,
            }
            if product_name == "未分类":
                unclassified = result_row
            else:
                products.append(result_row)
        products.sort(key=lambda row: row["total_qty"], reverse=True)
        if unclassified is not None:
            products.append(unclassified)
        return {
            "products": products,
            "normal_flows": sorted(ALLOWED_FLOWS),
        }

    def get_read_model_facts(self, _target_date: date) -> dict:
        """将细粒度事实合并为 Kanban 使用的最低必要粒度。

        Args:
            _target_date: 兼容查询接口的业务日期。

        Returns:
            dict: Kanban 事实和按完整工单组织的产品信息。
        """
        totals: dict[tuple[object, int, str, str], dict] = {}
        for item in self.facts:
            key = (
                item.get("reg_per_sys_id"),
                self._stepno(item),
                str(item.get("wrk_order") or ""),
                self._flow(item),
            )
            row = totals.setdefault(key, {"qty": 0, "record_count": 0})
            row["qty"] += self._qty(item)
            row["record_count"] += int(item.get("record_count") or 0)
        facts = [
            {
                "reg_per_sys_id": employee_id,
                "stepno": stepno,
                "wrk_order": wrk_order,
                "flow": flow,
                "qty": values["qty"],
                "record_count": values["record_count"],
            }
            for (employee_id, stepno, wrk_order, flow), values in totals.items()
        ]
        facts.sort(
            key=lambda row: (
                str(row["reg_per_sys_id"]),
                row["stepno"],
                row["wrk_order"],
                row["flow"],
            )
        )
        return {"facts": facts, "products": self.products}
