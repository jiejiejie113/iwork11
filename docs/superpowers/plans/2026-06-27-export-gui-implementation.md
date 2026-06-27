# 导出工具 GUI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `export_pytckreg3.py` 添加 XLSX 输出支持和 customtkinter 图形界面，打包为独立 exe。

**Architecture:** GUI 层（customtkinter）收集参数并校验，在后台线程中调用修改后的 `export_to_xlsx`/`export_month_to_xlsx` 函数。进度通过回调函数更新 UI，取消通过 `threading.Event` 实现。

**Tech Stack:** customtkinter 5.2.2, openpyxl 3.1.5 (write_only), pymysql (SSCursor 流式读取), PyInstaller

## Global Constraints

- Python 3.11.6
- 不改动现有函数的查询逻辑（SQL 构建、SSCursor 流式读取）
- 输出格式 XLSX，使用 openpyxl `write_only=True` 避免内存溢出
- 窗口固定宽度 550px，不可调整大小
- 状态文字和提示使用中文

---

### Task 1: 改造 export_pytckreg3.py — CSV → XLSX

**Files:**
- Modify: `scripts/export_pytckreg3.py`

**Interfaces:**
- Produces: `export_to_xlsx(target_date, output_dir, stepno_filter, file_prefix, db_host, progress_callback, cancel_event) -> int`
- Produces: `export_month_to_xlsx(target_month, stepno_filter, output_dir, db_host, progress_callback, cancel_event) -> int`
- Produces: `get_db_config(host) -> dict`

- [ ] **Step 1: 替换 csv 模块为 openpyxl，重命名函数，给 get_db_config 添加 host 参数**

```python
# 替换头部 import
import sys
import threading
from typing import Callable

# csv import 删除，添加：
from openpyxl import Workbook

# 新增数据库主机选项配置
DB_HOST_OPTIONS = {
    "VCO": "192.168.3.15",
    "EST": "192.168.4.19",
}
```

```python
# 修改 get_db_config — 接受 host 参数，支持打包后 .env 查找
def get_db_config(host: str | None = None) -> dict:
    """
    获取数据库连接配置

    Args:
        host: 数据库主机地址，默认使用 IWORK_DB_HOST
    """
    # 按优先级查找 .env：项目目录 > exe 同目录 > 当前目录
    env_paths = [Path(__file__).parent.parent / "iwork" / ".env"]
    if getattr(sys, 'frozen', False):
        env_paths.insert(0, Path(sys.executable).parent / ".env")
    env_paths.append(Path.cwd() / ".env")

    config = {}
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        config[key.strip()] = value.strip()
            break

    return {
        "host": host or IWORK_DB_HOST,
        "port": int(config.get("IWORK_DB_PORT", 3306)),
        "user": config.get("IWORK_DB_USER", ""),
        "password": config.get("IWORK_DB_PASSWORD", ""),
        "database": config.get("IWORK_DB_NAME", ""),
        "charset": "utf8mb4",
        "connect_timeout": CONNECT_TIMEOUT,
        "read_timeout": READ_TIMEOUT,
    }
```

- [ ] **Step 2: 重写 export_to_csv → export_to_xlsx，添加 progress_callback 和 cancel_event**

```python
def export_to_xlsx(
    target_date: date,
    output_dir: Path,
    stepno_filter: list[int] | None = None,
    file_prefix: str = "pytckreg3",
    db_host: str | None = None,
    progress_callback: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> int:
    """
    导出数据到 XLSX

    Args:
        target_date: 目标日期
        output_dir: 输出目录
        stepno_filter: StepNo 筛选值列表，None 表示不过滤
        file_prefix: 输出文件名前缀
        db_host: 数据库主机地址，默认使用 IWORK_DB_HOST
        progress_callback: 进度回调，每 CHUNK_SIZE 行调用一次，参数为当前行数
        cancel_event: 取消事件，设置后中断导出

    Returns:
        int: 导出的记录数（取消时返回已导出行数的负值）
    """
    config = get_db_config(db_host)
    filter_info = f" | StepNo in {stepno_filter}" if stepno_filter else ""
    logger.info(f"连接: {config['host']}/{config['database']} | 日期: {target_date}{filter_info}")

    try:
        conn = pymysql.connect(**config, cursorclass=SSCursor)
    except pymysql.Error as e:
        logger.error(f"连接失败: {e}")
        return 0

    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT TicketNo, SeqNo, WrkOrder, BundleNo, StepNo, Qty,
                       RegPerSysID, RegDate, RegTime, RFID, Flow, PO,
                       TimeCost, SysSource, AccBundleNo, MtrType, Color, Sizx,
                       SerialNum, StationID
                FROM pytckreg3
                WHERE RegDate >= %s AND RegDate < %s + INTERVAL 1 DAY
            """
            params: list = [target_date, target_date]

            if stepno_filter:
                placeholders = ",".join(["%s"] * len(stepno_filter))
                sql += f" AND StepNo IN ({placeholders})"
                params.extend(stepno_filter)

            cursor.execute(sql, params)

            columns = [d[0] for d in cursor.description]

            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"{file_prefix}_{timestamp}.xlsx"

            wb = Workbook(write_only=True)
            ws = wb.create_sheet()
            ws.append(columns)

            count = 0
            for row in cursor:
                if cancel_event and cancel_event.is_set():
                    logger.warning("用户取消导出")
                    ws.append(["导出已取消"])
                    wb.save(output_file)
                    wb.close()
                    logger.warning(f"已取消，部分数据已保存: {output_file} ({count} 条)")
                    return -count

                ws.append(row)
                count += 1
                if count % CHUNK_SIZE == 0:
                    logger.info(f"已写入 {count} 条")
                    if progress_callback:
                        progress_callback(count)

            wb.save(output_file)
            wb.close()
            logger.success(f"导出完成: {output_file} ({count} 条)")
            return count

    except pymysql.Error as e:
        logger.error(f"查询失败: {e}")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
```

- [ ] **Step 3: 重写 export_month_to_csv → export_month_to_xlsx，添加 progress_callback 和 cancel_event**

```python
def export_month_to_xlsx(
    target_month: str,
    stepno_filter: list[int],
    output_dir: Path,
    db_host: str | None = None,
    progress_callback: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> int:
    """
    导出数据（自动识别月份或日期），仅保留 StepNo 在筛选列表中的记录

    - "YYYYY-MM"（如 "2026-02"）：导出整月，合并为单个 XLSX 文件
    - "YYYYY-MM-DD"（如 "2026-02-20"）：导出单日

    Args:
        target_month: 目标月份 "YYYYY-MM" 或具体日期 "YYYYY-MM-DD"
        stepno_filter: StepNo 筛选值列表
        output_dir: 输出目录
        db_host: 数据库主机地址
        progress_callback: 进度回调
        cancel_event: 取消事件

    Returns:
        int: 导出的总记录数（取消时为负数）
    """
    parts = target_month.split("-")
    stepno_str = "_".join(str(s) for s in stepno_filter)

    if len(parts) == 3:
        target_date = datetime.strptime(target_month, "%Y-%m-%d").date()
        logger.info(f"日期导出模式: {target_date}, StepNo in {stepno_filter}")

        return export_to_xlsx(
            target_date=target_date,
            output_dir=output_dir,
            stepno_filter=stepno_filter,
            file_prefix=f"pytckreg3_{target_date.strftime('%Y%m%d')}_step{stepno_str}",
            db_host=db_host,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    elif len(parts) == 2:
        year, month = map(int, parts)
        _, last_day = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        logger.info(f"月份导出模式: {target_month} ({start_date} ~ {end_date}), StepNo in {stepno_filter}")

        config = get_db_config(db_host)
        try:
            conn = pymysql.connect(**config, cursorclass=SSCursor)
        except pymysql.Error as e:
            logger.error(f"连接失败: {e}")
            return 0

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT TicketNo, SeqNo, WrkOrder, BundleNo, StepNo, Qty, "
                    "RegPerSysID, RegDate, RegTime, RFID, Flow, PO, "
                    "TimeCost, SysSource, AccBundleNo, MtrType, Color, Sizx, "
                    "SerialNum, StationID FROM pytckreg3 LIMIT 0"
                )
                columns = [d[0] for d in cursor.description]

                output_dir.mkdir(parents=True, exist_ok=True)
                month_str = target_month.replace("-", "")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = output_dir / f"pytckreg3_{month_str}_step{stepno_str}_{timestamp}.xlsx"

                wb = Workbook(write_only=True)
                ws = wb.create_sheet()
                ws.append(columns)

                total = 0
                current = start_date
                while current <= end_date:
                    if cancel_event and cancel_event.is_set():
                        logger.warning("用户取消导出")
                        ws.append(["导出已取消"])
                        wb.save(output_file)
                        wb.close()
                        logger.warning(f"已取消，部分数据已保存: {output_file} ({total} 条)")
                        return -total

                    sql = """
                        SELECT TicketNo, SeqNo, WrkOrder, BundleNo, StepNo, Qty,
                               RegPerSysID, RegDate, RegTime, RFID, Flow, PO,
                               TimeCost, SysSource, AccBundleNo, MtrType, Color, Sizx,
                               SerialNum, StationID
                        FROM pytckreg3
                        WHERE RegDate >= %s AND RegDate < %s + INTERVAL 1 DAY
                    """
                    params: list = [current, current]

                    if stepno_filter:
                        placeholders = ",".join(["%s"] * len(stepno_filter))
                        sql += f" AND StepNo IN ({placeholders})"
                        params.extend(stepno_filter)

                    cursor.execute(sql, params)
                    daily_count = 0
                    for row in cursor:
                        if cancel_event and cancel_event.is_set():
                            ws.append(["导出已取消"])
                            wb.save(output_file)
                            wb.close()
                            logger.warning(f"已取消，部分数据已保存: {output_file} ({total} 条)")
                            return -total

                        ws.append(row)
                        total += 1
                        daily_count += 1
                        if total % CHUNK_SIZE == 0:
                            logger.info(f"已写入 {total} 条")
                            if progress_callback:
                                progress_callback(total)

                    logger.info(f"  {current}: {daily_count} 条 (累计 {total})")
                    current = date.fromordinal(current.toordinal() + 1)

                wb.save(output_file)
                wb.close()
                logger.success(f"月份导出完成: {output_file} ({total} 条)")
                return total

        except pymysql.Error as e:
            logger.error(f"查询失败: {e}")
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    else:
        logger.error(f"无法识别的格式: {target_month}，请使用 YYYYY-MM 或 YYYYY-MM-DD")
        return 0
```

- [ ] **Step 4: 保留 main() 函数兼容性（不改签名，但使用新函数）**

```python
def main():
    if MODE == "export_date":
        if TARGET_DATE:
            target_date = datetime.strptime(TARGET_DATE, "%Y-%m-%d").date()
        else:
            target_date = date.today()
        export_to_xlsx(target_date, OUTPUT_DIR)

    elif MODE == "export_month":
        export_month_to_xlsx(TARGET_MONTH, STEPNO_FILTER, OUTPUT_DIR)

    else:
        logger.error(f"未知模式: {MODE}，可选值: export_date / export_month")
```

- [ ] **Step 5: 运行脚本验证单日导出**

```powershell
chcp 65001 && python -c "from pathlib import Path; from scripts.export_pytckreg3 import export_to_xlsx; from datetime import date; r = export_to_xlsx(date.today(), Path('scripts/output')); print(f'结果: {r}')"
```

- [ ] **Step 6: 提交**

```bash
git add scripts/export_pytckreg3.py
git commit -m "[2026-06-27][REFACTOR] 导出脚本 CSV → XLSX，新增进度回调与取消支持"
```

---

### Task 2: 创建 gui 包骨架

**Files:**
- Create: `scripts/gui/__init__.py`

- [ ] **Step 1: 创建 __init__.py**

```python
"""pytckreg3 数据导出工具 GUI"""
```

- [ ] **Step 2: 提交**

```bash
git add scripts/gui/__init__.py
git commit -m "[2026-06-27][FEAT] 创建导出工具 GUI 包骨架"
```

---

### Task 3: 构建主窗口 + 标签页布局

**Files:**
- Create: `scripts/gui/main.py`

**Interfaces:**
- Produces: `ExportApp(ctk.CTk)` — 主窗口类

- [ ] **Step 1: 创建主窗口和标签页框架**

```python
"""
pytckreg3 数据导出工具 GUI
使用 customtkinter 构建，供非技术人员使用
"""

import sys
import threading
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import customtkinter as ctk
from tkinter import filedialog, messagebox

from export_pytckreg3 import (
    export_to_xlsx,
    export_month_to_xlsx,
    OUTPUT_DIR,
)

# ===== 窗口配置 =====
WINDOW_WIDTH = 550
WINDOW_HEIGHT = 480
WINDOW_TITLE = "pytckreg3 数据导出工具"

# ===== 数据库选项 =====
DB_HOST_LABELS = {
    "VCO (192.168.3.15)": "192.168.3.15",
    "EST (192.168.4.19)": "192.168.4.19",
}


class ExportApp(ctk.CTk):
    """主窗口"""

    def __init__(self):
        super().__init__()

        self.title(WINDOW_TITLE)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.resizable(False, False)

        # 线程控制
        self._worker: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._progress_count = 0
        self._running = False

        # 默认输出目录
        self._output_dir = Path(sys.executable).parent / "output" if getattr(sys, 'frozen', False) else OUTPUT_DIR

        self._build_ui()
        self._bind_close_handler()

    def _build_ui(self):
        """构建界面"""
        # 标签页
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="x", padx=15, pady=(15, 5))

        self.date_tab = self.tabview.add("按日期导出")
        self.month_tab = self.tabview.add("按月份导出")
        self.tabview.set("按日期导出")

        self._build_date_tab()
        self._build_month_tab()
        self._build_shared_frame()
        self._build_progress_frame()
        self._build_action_frame()

    def _build_date_tab(self):
        """按日期导出标签页"""
        frame = ctk.CTkFrame(self.date_tab)
        frame.pack(fill="x", padx=5, pady=10)

        ctk.CTkLabel(frame, text="目标日期:", width=120, anchor="w").grid(
            row=0, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        today_str = date.today().strftime("%Y-%m-%d")
        self.date_entry = ctk.CTkEntry(frame, width=200, placeholder_text="YYYYY-MM-DD")
        self.date_entry.insert(0, today_str)
        self.date_entry.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="工序号筛选:", width=120, anchor="w").grid(
            row=1, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.date_stepno_entry = ctk.CTkEntry(frame, width=200, placeholder_text="可选，如 69,70")
        self.date_stepno_entry.grid(row=1, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(
            frame, text="逗号分隔多个工序号，留空则导出全部",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 5), sticky="w")

    def _build_month_tab(self):
        """按月份导出标签页"""
        frame = ctk.CTkFrame(self.month_tab)
        frame.pack(fill="x", padx=5, pady=10)

        ctk.CTkLabel(frame, text="目标月份/日期:", width=120, anchor="w").grid(
            row=0, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.month_entry = ctk.CTkEntry(frame, width=200, placeholder_text="YYYYY-MM 或 YYYYY-MM-DD")
        self.month_entry.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="工序号筛选:", width=120, anchor="w").grid(
            row=1, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.month_stepno_entry = ctk.CTkEntry(frame, width=200, placeholder_text="必填，如 69,70")
        self.month_stepno_entry.grid(row=1, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(
            frame, text="YYYYY-MM 导出整月，YYYYY-MM-DD 导出单日",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 5), sticky="w")

    def _bind_close_handler(self):
        """绑定窗口关闭事件"""
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """窗口关闭处理"""
        if self._running:
            result = messagebox.askyesno(
                "确认退出",
                "正在导出数据，确定要退出吗？\n\n已导出的数据会保留。"
            )
            if result:
                self._cancel_event.set()
                self.destroy()
        else:
            self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = ExportApp()
    app.mainloop()
```

- [ ] **Step 2: 运行 GUI 确认窗口和标签页正常显示**

```powershell
chcp 65001 && python scripts/gui/main.py
```
预期：窗口显示，两个标签页可切换，关闭窗口正常退出。

- [ ] **Step 3: 提交**

```bash
git add scripts/gui/main.py
git commit -m "[2026-06-27][FEAT] 创建导出工具主窗口与标签页布局"
```

---

### Task 4: 构建共享配置区（数据库 + 输出目录）

**Files:**
- Modify: `scripts/gui/main.py` — 添加 `_build_shared_frame` 方法

- [ ] **Step 1: 添加共享配置 frame**

```python
    def _build_shared_frame(self):
        """共享配置区：数据库选择 + 输出目录"""
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=15, pady=5)

        # 数据库选择
        ctk.CTkLabel(frame, text="数据库:", width=80, anchor="w").grid(
            row=0, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.db_combo = ctk.CTkComboBox(
            frame,
            values=list(DB_HOST_LABELS.keys()),
            width=200,
            state="readonly",
        )
        # 默认选中 EST
        self.db_combo.set("EST (192.168.4.19)")
        self.db_combo.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        # 输出目录
        ctk.CTkLabel(frame, text="输出目录:", width=80, anchor="w").grid(
            row=1, column=0, padx=(15, 5), pady=(5, 15), sticky="w"
        )
        self.output_entry = ctk.CTkEntry(frame, width=320)
        self.output_entry.insert(0, str(self._output_dir))
        self.output_entry.grid(row=1, column=1, padx=5, pady=(5, 15), sticky="w")

        self.browse_btn = ctk.CTkButton(
            frame, text="浏览...", width=70,
            command=self._browse_output_dir,
        )
        self.browse_btn.grid(row=1, column=2, padx=(0, 15), pady=(5, 15), sticky="e")

    def _browse_output_dir(self):
        """选择输出目录"""
        selected = filedialog.askdirectory(initialdir=self._output_dir)
        if selected:
            self._output_dir = Path(selected)
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, str(self._output_dir))
```

- [ ] **Step 2: 运行 GUI 确认数据库下拉和目录选择正常**

```powershell
chcp 65001 && python scripts/gui/main.py
```
预期：数据库下拉可切换 VCO/EST，浏览按钮弹出系统目录选择对话框，选中后路径回填到输入框。

- [ ] **Step 3: 提交**

```bash
git add scripts/gui/main.py
git commit -m "[2026-06-27][FEAT] 添加共享配置区（数据库选择 + 输出目录）"
```

---

### Task 5: 构建进度区和操作按钮

**Files:**
- Modify: `scripts/gui/main.py` — 添加 `_build_progress_frame` 和 `_build_action_frame`

- [ ] **Step 1: 添加进度区和按钮区**

```python
    def _build_progress_frame(self):
        """进度展示区"""
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=15, pady=5)

        self.status_label = ctk.CTkLabel(frame, text="状态: 就绪", anchor="w")
        self.status_label.pack(padx=15, pady=(10, 5), fill="x")

        self.progress_bar = ctk.CTkProgressBar(frame, width=500)
        self.progress_bar.pack(padx=15, pady=5, fill="x")
        self.progress_bar.set(0)

        self.count_label = ctk.CTkLabel(frame, text="", anchor="w")
        self.count_label.pack(padx=15, pady=(5, 10), fill="x")

    def _build_action_frame(self):
        """操作按钮区"""
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=15, pady=(5, 15))

        self.start_btn = ctk.CTkButton(
            frame, text="开始导出", width=120,
            command=self._start_export,
        )
        self.start_btn.pack(side="left", padx=(80, 10), pady=10)

        self.cancel_btn = ctk.CTkButton(
            frame, text="取消", width=80,
            fg_color="transparent", border_width=1,
            command=self._cancel_export,
            state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=10, pady=10)
```

- [ ] **Step 2: 提交**

```bash
git add scripts/gui/main.py
git commit -m "[2026-06-27][FEAT] 添加进度展示区和操作按钮"
```

---

### Task 6: 实现线程模型和导出执行

**Files:**
- Modify: `scripts/gui/main.py` — 添加 `_start_export`、`_cancel_export`、`_poll_progress`、`_export_finished`

- [ ] **Step 1: 添加输入解析辅助方法**

```python
    def _parse_stepno(self, text: str) -> list[int] | None:
        """解析工序号输入"""
        text = text.strip()
        if not text:
            return None
        try:
            return [int(s.strip()) for s in text.split(",") if s.strip()]
        except ValueError:
            raise ValueError(f"工序号格式错误: {text}\n请使用逗号分隔的数字，如: 69,70")

    def _get_db_host(self) -> str:
        """获取选中的数据库主机地址"""
        label = self.db_combo.get()
        return DB_HOST_LABELS.get(label, "192.168.4.19")
```

- [ ] **Step 2: 添加导出启动方法**

```python
    def _start_export(self):
        """开始导出"""
        # 输入校验
        current_tab = self.tabview.get()

        if current_tab == "按日期导出":
            date_str = self.date_entry.get().strip()
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                messagebox.showerror("格式错误", f"日期格式错误: {date_str}\n请使用 YYYYY-MM-DD 格式，如: 2026-06-26")
                return

            stepno_text = self.date_stepno_entry.get()
            try:
                stepno_filter = self._parse_stepno(stepno_text)
            except ValueError as e:
                messagebox.showerror("格式错误", str(e))
                return

            target_func = export_to_xlsx
            kwargs = {
                "target_date": target_date,
                "output_dir": self._output_dir,
                "stepno_filter": stepno_filter,
                "db_host": self._get_db_host(),
                "progress_callback": self._on_progress,
                "cancel_event": self._cancel_event,
            }

        else:  # 按月份导出
            month_str = self.month_entry.get().strip()
            parts = month_str.split("-")
            if len(parts) not in (2, 3):
                messagebox.showerror(
                    "格式错误",
                    f"月份/日期格式错误: {month_str}\n请使用 YYYYY-MM 或 YYYYY-MM-DD 格式"
                )
                return
            if len(parts) == 3:
                try:
                    datetime.strptime(month_str, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("格式错误", f"日期格式错误: {month_str}\n请使用 YYYYY-MM-DD 格式")
                    return
            if len(parts) == 2:
                year, month = parts
                if not (year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
                    messagebox.showerror("格式错误", f"月份格式错误: {month_str}\n请使用 YYYYY-MM 格式")
                    return

            stepno_text = self.month_stepno_entry.get()
            try:
                stepno_filter = self._parse_stepno(stepno_text)
            except ValueError as e:
                messagebox.showerror("格式错误", str(e))
                return

            if not stepno_filter:
                messagebox.showerror("参数缺失", "按月份导出时，工序号筛选为必填项")
                return

            target_func = export_month_to_xlsx
            kwargs = {
                "target_month": month_str,
                "stepno_filter": stepno_filter,
                "output_dir": self._output_dir,
                "db_host": self._get_db_host(),
                "progress_callback": self._on_progress,
                "cancel_event": self._cancel_event,
            }

        # 启动导出线程
        self._cancel_event.clear()
        self._progress_count = 0
        self._running = True
        self._set_controls_state("disabled")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.status_label.configure(text="状态: 正在连接数据库...")
        self.count_label.configure(text="")

        self._worker = threading.Thread(
            target=self._run_export,
            args=(target_func, kwargs),
            daemon=True,
        )
        self._worker.start()
        self._poll_progress()
```

- [ ] **Step 3: 添加后台线程、进度轮询、取消和完成处理**

```python
    def _run_export(self, func, kwargs):
        """后台执行导出"""
        try:
            self._result = func(**kwargs)
        except Exception as e:
            self._error = str(e)
            self._result = None
        else:
            self._error = None

    def _on_progress(self, count: int):
        """进度回调（在后台线程中调用）"""
        self._progress_count = count

    def _poll_progress(self):
        """轮询进度（在主线程中通过 after 调度）"""
        if not self._running:
            return

        if self._worker and self._worker.is_alive():
            if self._progress_count > 0:
                self.status_label.configure(text=f"状态: 导出中...")
                self.count_label.configure(text=f"已导出: {self._progress_count:,} 条")
            self.after(100, self._poll_progress)
        else:
            self._export_finished()

    def _export_finished(self):
        """导出完成"""
        self._running = False
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(1)
        self._set_controls_state("normal")

        if self._error:
            self.status_label.configure(text=f"状态: 导出失败", text_color="red")
            self.count_label.configure(text="")
            messagebox.showerror("导出失败", f"数据库错误:\n{self._error}")
        elif self._result is None:
            self.status_label.configure(text="状态: 未执行", text_color="gray")
        elif self._result < 0:
            count = -self._result
            self.status_label.configure(text=f"状态: 已取消 ({count:,} 条)", text_color="orange")
            self.count_label.configure(text=f"已导出: {count:,} 条（部分数据已保存）")
        elif self._result == 0:
            self.status_label.configure(text="状态: 无数据或连接失败", text_color="orange")
            self.count_label.configure(text="")
            messagebox.showwarning("提示", "未查询到数据，请检查日期是否正确。")
        else:
            self.status_label.configure(text=f"状态: 导出完成", text_color="green")
            self.count_label.configure(text=f"共导出: {self._result:,} 条")
            messagebox.showinfo("导出完成", f"数据已导出成功！\n\n共 {self._result:,} 条记录")

    def _cancel_export(self):
        """取消导出"""
        if self._running:
            self._cancel_event.set()
            self.status_label.configure(text="状态: 正在取消...")
            self.cancel_btn.configure(state="disabled")

    def _set_controls_state(self, state: str):
        """批量设置控件状态"""
        self.date_entry.configure(state=state)
        self.date_stepno_entry.configure(state=state)
        self.month_entry.configure(state=state)
        self.month_stepno_entry.configure(state=state)
        self.db_combo.configure(state=state)
        self.output_entry.configure(state=state)
        self.browse_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if state == "disabled" else "disabled")
        if state == "disabled":
            self.status_label.configure(text_color="white")
```

- [ ] **Step 4: 运行 GUI 进行快速功能测试**

```powershell
chcp 65001 && python scripts/gui/main.py
```
预期：输入合法日期 → 点"开始导出" → 控件禁用 → 进度条滚动 → 行数更新 → 完成后弹窗提示。

- [ ] **Step 5: 提交**

```bash
git add scripts/gui/main.py
git commit -m "[2026-06-27][FEAT] 实现后台线程导出、进度轮询与取消机制"
```

---

### Task 7: 打包脚本

**Files:**
- Create: `scripts/gui/pack.py`

- [ ] **Step 1: 创建打包脚本**

```python
"""
PyInstaller 打包脚本
用法: python pack.py
"""

import subprocess
import sys
from pathlib import Path


def main():
    gui_dir = Path(__file__).parent
    main_file = gui_dir / "main.py"
    script_dir = gui_dir.parent
    icon_file = gui_dir / "icon.ico"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "pytckreg3导出工具",
        "--add-data", f"{script_dir / 'export_pytckreg3.py'};.",
        str(main_file),
    ]

    if icon_file.exists():
        cmd.insert(4, f"--icon={icon_file}")

    print(f"执行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("打包完成，输出目录: dist/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 添加 pyinstaller 到依赖**

在 `requirements.txt` 末尾添加一行 `pyinstaller>=6.0.0`。

- [ ] **Step 3: 提交**

```bash
git add scripts/gui/pack.py requirements.txt
git commit -m "[2026-06-27][FEAT] 添加 PyInstaller 打包脚本"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 完整测试 — 按日期导出（无筛选）**

```powershell
chcp 65001 && python -c "
from pathlib import Path
from scripts.export_pytckreg3 import export_to_xlsx
from datetime import date
r = export_to_xlsx(date.today(), Path('scripts/output'))
print(f'结果: {r}')
assert r > 0, '导出记录数应为正'
"
```
预期：PASS

- [ ] **Step 2: 完整测试 — 按月份导出（含筛选）**

```powershell
chcp 65001 && python -c "
from pathlib import Path
from scripts.export_pytckreg3 import export_month_to_xlsx
r = export_month_to_xlsx(date.today().strftime('%Y-%m-%d'), [70], Path('scripts/output'))
print(f'结果: {r}')
assert r != 0, '导出结果不应为0'
"
```
预期：PASS

- [ ] **Step 3: 提交**

```bash
git commit --allow-empty -m "[2026-06-27][TEST] 端到端导出验证通过"
```
