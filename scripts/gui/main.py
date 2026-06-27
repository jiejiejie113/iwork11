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
        self._result: int | None = None
        self._error: str | None = None

        # 默认输出目录
        self._output_dir = (
            Path(sys.executable).parent / "output"
            if getattr(sys, 'frozen', False)
            else OUTPUT_DIR
        )

        self._build_ui()
        self._bind_close_handler()

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_ui(self):
        """构建界面"""
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
        self.date_entry = ctk.CTkEntry(frame, width=200, placeholder_text="YYYY-MM-DD")
        self.date_entry.insert(0, today_str)
        self.date_entry.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="工序号筛选:", width=120, anchor="w").grid(
            row=1, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.date_stepno_entry = ctk.CTkEntry(
            frame, width=200, placeholder_text="可选，如 69,70"
        )
        self.date_stepno_entry.grid(row=1, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(
            frame,
            text="逗号分隔多个工序号，留空则导出全部",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 5), sticky="w")

    def _build_month_tab(self):
        """按月份导出标签页"""
        frame = ctk.CTkFrame(self.month_tab)
        frame.pack(fill="x", padx=5, pady=10)

        ctk.CTkLabel(frame, text="目标月份/日期:", width=120, anchor="w").grid(
            row=0, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.month_entry = ctk.CTkEntry(
            frame, width=200, placeholder_text="YYYY-MM 或 YYYY-MM-DD"
        )
        self.month_entry.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="工序号筛选:", width=120, anchor="w").grid(
            row=1, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.month_stepno_entry = ctk.CTkEntry(
            frame, width=200, placeholder_text="必填，如 69,70"
        )
        self.month_stepno_entry.grid(row=1, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(
            frame,
            text="YYYY-MM 导出整月，YYYY-MM-DD 导出单日",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 5), sticky="w")

    def _build_shared_frame(self):
        """共享配置区：数据库选择 + 输出目录"""
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(frame, text="数据库:", width=80, anchor="w").grid(
            row=0, column=0, padx=(15, 5), pady=10, sticky="w"
        )
        self.db_combo = ctk.CTkComboBox(
            frame,
            values=list(DB_HOST_LABELS.keys()),
            width=200,
            state="readonly",
        )
        self.db_combo.set("EST (192.168.4.19)")
        self.db_combo.grid(row=0, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="输出目录:", width=80, anchor="w").grid(
            row=1, column=0, padx=(15, 5), pady=(5, 15), sticky="w"
        )
        self.output_entry = ctk.CTkEntry(frame, width=320)
        self.output_entry.insert(0, str(self._output_dir))
        self.output_entry.grid(row=1, column=1, padx=5, pady=(5, 15), sticky="w")

        self.browse_btn = ctk.CTkButton(
            frame,
            text="浏览...",
            width=70,
            command=self._browse_output_dir,
        )
        self.browse_btn.grid(row=1, column=2, padx=(0, 15), pady=(5, 15), sticky="e")

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
            frame,
            text="开始导出",
            width=120,
            command=self._start_export,
        )
        self.start_btn.pack(side="left", padx=(80, 10), pady=10)

        self.cancel_btn = ctk.CTkButton(
            frame,
            text="取消",
            width=80,
            fg_color="transparent",
            border_width=1,
            command=self._cancel_export,
            state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=10, pady=10)

    # ============================================================
    # 交互逻辑
    # ============================================================

    def _browse_output_dir(self):
        """选择输出目录"""
        selected = filedialog.askdirectory(initialdir=self._output_dir)
        if selected:
            self._output_dir = Path(selected)
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, str(self._output_dir))

    def _bind_close_handler(self):
        """绑定窗口关闭事件"""
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """窗口关闭处理"""
        if self._running:
            result = messagebox.askyesno(
                "确认退出",
                "正在导出数据，确定要退出吗？\n\n已导出的数据会保留。",
            )
            if result:
                self._cancel_event.set()
                self.destroy()
        else:
            self.destroy()

    # ============================================================
    # 输入解析
    # ============================================================

    def _parse_stepno(self, text: str) -> list[int] | None:
        """解析工序号输入"""
        text = text.strip()
        if not text:
            return None
        try:
            return [int(s.strip()) for s in text.split(",") if s.strip()]
        except ValueError:
            raise ValueError(
                f"工序号格式错误: {text}\n请使用逗号分隔的数字，如: 69,70"
            )

    def _get_db_host(self) -> str:
        """获取选中的数据库主机地址"""
        label = self.db_combo.get()
        return DB_HOST_LABELS.get(label, "192.168.4.19")

    # ============================================================
    # 导出控制
    # ============================================================

    def _start_export(self):
        """开始导出"""
        current_tab = self.tabview.get()

        if current_tab == "按日期导出":
            date_str = self.date_entry.get().strip()
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                messagebox.showerror(
                    "格式错误",
                    f"日期格式错误: {date_str}\n请使用 YYYY-MM-DD 格式，如: 2026-06-26",
                )
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
                    f"月份/日期格式错误: {month_str}\n请使用 YYYY-MM 或 YYYY-MM-DD 格式",
                )
                return
            if len(parts) == 3:
                try:
                    datetime.strptime(month_str, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror(
                        "格式错误",
                        f"日期格式错误: {month_str}\n请使用 YYYY-MM-DD 格式",
                    )
                    return
            if len(parts) == 2:
                y, m = parts
                if not (y.isdigit() and m.isdigit() and 1 <= int(m) <= 12):
                    messagebox.showerror(
                        "格式错误",
                        f"月份格式错误: {month_str}\n请使用 YYYY-MM 格式",
                    )
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
                self.status_label.configure(text="状态: 导出中...")
                self.count_label.configure(
                    text=f"已导出: {self._progress_count:,} 条"
                )
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
            self.status_label.configure(text="状态: 导出失败", text_color="red")
            self.count_label.configure(text="")
            messagebox.showerror("导出失败", f"数据库错误:\n{self._error}")
        elif self._result is None:
            self.status_label.configure(text="状态: 未执行", text_color="gray")
        elif self._result < 0:
            count = -self._result
            self.status_label.configure(
                text=f"状态: 已取消 ({count:,} 条)", text_color="orange"
            )
            self.count_label.configure(
                text=f"已导出: {count:,} 条（部分数据已保存）"
            )
        elif self._result == 0:
            self.status_label.configure(
                text="状态: 无数据或连接失败", text_color="orange"
            )
            self.count_label.configure(text="")
            messagebox.showwarning("提示", "未查询到数据，请检查日期是否正确。")
        else:
            self.status_label.configure(text="状态: 导出完成", text_color="green")
            self.count_label.configure(text=f"共导出: {self._result:,} 条")
            messagebox.showinfo(
                "导出完成", f"数据已导出成功！\n\n共 {self._result:,} 条记录"
            )

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
        self.cancel_btn.configure(
            state="normal" if state == "disabled" else "disabled"
        )


if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = ExportApp()
    app.mainloop()
