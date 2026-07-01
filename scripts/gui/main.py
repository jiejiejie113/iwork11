"""
pytckreg3 数据导出工具 GUI
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

# ===== 配色 =====
C_ACCENT = "#059669"
C_ACCENT_HOVER = "#047857"
C_ACCENT_TEXT = "#ffffff"
C_BG = "#f3f4f6"
C_CARD = "#ffffff"
C_TEXT = "#111827"
C_TEXT_DIM = "#4b5563"
C_TEXT_MUTED = "#9ca3af"
C_BORDER = "#e5e7eb"
C_INPUT = "#f3f4f6"
C_DANGER = "#dc2626"
C_WARNING = "#d97706"
C_SUCCESS = "#16a34a"
C_ORANGE = "#ea580c"
C_COMBO_BTN = "#e5e7eb"
C_COMBO_HOVER = "#d1d5db"

# ===== 数据库选项 =====
DB_HOST_LABELS = {
    "VCO (192.168.3.15)": "192.168.3.15",
    "EST (192.168.4.19)": "192.168.4.19",
}

WINDOW_WIDTH = 520
WINDOW_HEIGHT = 420


class ExportApp(ctk.CTk):
    """主窗口"""

    def __init__(self):
        super().__init__()

        self.title("pytckreg3 数据导出工具")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.resizable(False, True)
        self.configure(fg_color=C_BG)

        # 线程控制
        self._worker: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._progress_count = 0
        self._running = False
        self._result: int | None = None
        self._error: str | None = None

        self._output_dir = (
            Path(sys.executable).parent / "output"
            if getattr(sys, "frozen", False)
            else OUTPUT_DIR
        )

        self._build_ui()
        self._bind_close_handler()

    def _build_ui(self):
        """构建界面"""
        # ---- 标签页 ----
        self.tabview = ctk.CTkTabview(
            self, corner_radius=8, height=120,
            fg_color=C_INPUT,
            segmented_button_fg_color=C_INPUT,
            segmented_button_selected_color=C_ACCENT,
            segmented_button_selected_hover_color=C_ACCENT_HOVER,
            segmented_button_unselected_color=C_CARD,
            segmented_button_unselected_hover_color=C_INPUT,
            text_color=C_TEXT,
        )
        self.tabview.pack(fill="x", padx=15, pady=(2, 0))

        self.date_tab_name = " 按日期导出 "
        self.month_tab_name = " 按月份导出 "
        self.date_tab = self.tabview.add(self.date_tab_name)
        self.month_tab = self.tabview.add(self.month_tab_name)
        self.tabview.set(self.date_tab_name)
        self.tabview.configure(command=self._on_tab_change)

        self._build_date_tab()
        self._build_month_tab()

        # ---- 配置区 ----
        self._cfg_frame = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        self._cfg_frame.pack(fill="x", padx=15, pady=(2, 0))

        self._build_config()

        # ---- 进度区 ----
        self._prog_frame = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        self._prog_frame.pack(fill="x", padx=15, pady=(8, 0))

        self.status_label = ctk.CTkLabel(
            self._prog_frame, text="就绪", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C_TEXT_DIM, anchor="w",
        )
        self.status_label.pack(fill="x", padx=14, pady=(10, 4))

        self.progress_bar = ctk.CTkProgressBar(
            self._prog_frame, height=6, corner_radius=3,
            fg_color=C_BORDER, progress_color=C_ACCENT,
        )
        self.progress_bar.pack(fill="x", padx=14, pady=(0, 6))
        self.progress_bar.set(0)

        self.count_label = ctk.CTkLabel(
            self._prog_frame, text="", font=ctk.CTkFont(size=12),
            text_color=C_TEXT_MUTED, anchor="w",
        )
        self.count_label.pack(fill="x", padx=14, pady=(0, 8))

        # ---- 操作按钮 ----
        self._btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._btn_frame.pack(fill="x", padx=15, pady=(10, 12))

        self.start_btn = ctk.CTkButton(
            self._btn_frame, text="开始导出", height=40, corner_radius=8,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER, text_color=C_ACCENT_TEXT,
            command=self._start_export,
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.cancel_btn = ctk.CTkButton(
            self._btn_frame, text="取消", width=80, height=40, corner_radius=8,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", border_width=1, border_color=C_DANGER,
            text_color=C_DANGER, hover_color="#fef2f2",
            command=self._cancel_export, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(6, 0))

    def _build_date_tab(self):
        """按日期导出标签页"""
        self.date_tab.configure(fg_color="transparent")
        inner = ctk.CTkFrame(self.date_tab, fg_color="transparent")
        inner.pack(fill="x", padx=6, pady=(8, 0))

        ctk.CTkLabel(inner, text="目标日期", width=80, anchor="w", text_color=C_TEXT_DIM).grid(
            row=0, column=0, padx=(4, 8), pady=4, sticky="w"
        )
        self.date_entry = ctk.CTkEntry(
            inner, width=220, placeholder_text="YYYY-MM-DD",
            fg_color=C_INPUT, border_color=C_BORDER, text_color=C_TEXT,
            placeholder_text_color=C_TEXT_MUTED,
        )
        self.date_entry.insert(0, date.today().strftime("%Y-%m-%d"))
        self.date_entry.grid(row=0, column=1, padx=5, pady=4, sticky="w")

        ctk.CTkLabel(inner, text="工序号筛选", width=80, anchor="w", text_color=C_TEXT_DIM).grid(
            row=1, column=0, padx=(4, 8), pady=4, sticky="w"
        )
        self.date_stepno_entry = ctk.CTkEntry(
            inner, width=220, placeholder_text="可选，如 69,70",
            fg_color=C_INPUT, border_color=C_BORDER, text_color=C_TEXT,
            placeholder_text_color=C_TEXT_MUTED,
        )
        self.date_stepno_entry.grid(row=1, column=1, padx=5, pady=4, sticky="w")

        ctk.CTkLabel(
            inner, text="逗号分隔，留空导出全部", font=ctk.CTkFont(size=11),
            text_color=C_TEXT_MUTED, anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 2), sticky="w")

    def _build_month_tab(self):
        """按月份导出标签页"""
        self.month_tab.configure(fg_color="transparent")
        inner = ctk.CTkFrame(self.month_tab, fg_color="transparent")
        inner.pack(fill="x", padx=6, pady=(8, 0))

        ctk.CTkLabel(inner, text="目标月份/日期", width=80, anchor="w", text_color=C_TEXT_DIM).grid(
            row=0, column=0, padx=(4, 8), pady=4, sticky="w"
        )
        self.month_entry = ctk.CTkEntry(
            inner, width=220, placeholder_text="YYYY-MM 或 YYYY-MM-DD",
            fg_color=C_INPUT, border_color=C_BORDER, text_color=C_TEXT,
            placeholder_text_color=C_TEXT_MUTED,
        )
        self.month_entry.grid(row=0, column=1, padx=5, pady=4, sticky="w")

        ctk.CTkLabel(inner, text="工序号筛选", width=80, anchor="w", text_color=C_TEXT_DIM).grid(
            row=1, column=0, padx=(4, 8), pady=4, sticky="w"
        )
        self.month_stepno_entry = ctk.CTkEntry(
            inner, width=220, placeholder_text="可选，如 69,70",
            fg_color=C_INPUT, border_color=C_BORDER, text_color=C_TEXT,
            placeholder_text_color=C_TEXT_MUTED,
        )
        self.month_stepno_entry.grid(row=1, column=1, padx=5, pady=4, sticky="w")

        ctk.CTkLabel(
            inner, text="YYYY-MM 整月  |  YYYY-MM-DD 单日  |  逗号分隔，留空导出全部",
            font=ctk.CTkFont(size=11), text_color=C_TEXT_MUTED, anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 2), sticky="w")

    def _build_config(self):
        """配置区"""
        inner = ctk.CTkFrame(self._cfg_frame, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(inner, text="数据库", width=65, anchor="w", text_color=C_TEXT_DIM).grid(
            row=0, column=0, padx=(4, 8), pady=3, sticky="w"
        )
        self.db_combo = ctk.CTkComboBox(
            inner, values=list(DB_HOST_LABELS.keys()), width=200, state="readonly",
            corner_radius=8, font=ctk.CTkFont(size=13),
            fg_color=C_INPUT, border_color=C_BORDER, text_color=C_TEXT,
            button_color=C_COMBO_BTN, button_hover_color=C_COMBO_HOVER,
            dropdown_fg_color=C_CARD, dropdown_hover_color=C_INPUT,
        )
        self.db_combo.set("EST (192.168.4.19)")
        self.db_combo.grid(row=0, column=1, padx=5, pady=3, sticky="w")

        ctk.CTkLabel(inner, text="输出目录", width=65, anchor="w", text_color=C_TEXT_DIM).grid(
            row=1, column=0, padx=(4, 8), pady=3, sticky="w"
        )
        self.output_entry = ctk.CTkEntry(
            inner, width=300, fg_color=C_INPUT, border_color=C_BORDER,
            text_color=C_TEXT, placeholder_text_color=C_TEXT_MUTED,
        )
        self.output_entry.insert(0, str(self._output_dir))
        self.output_entry.grid(row=1, column=1, padx=5, pady=3, sticky="w")

        self.browse_btn = ctk.CTkButton(
            inner, text="浏览", width=56, height=30, corner_radius=8,
            font=ctk.CTkFont(size=12), fg_color=C_INPUT, hover_color=C_COMBO_HOVER,
            text_color=C_TEXT, command=self._browse_output_dir,
        )
        self.browse_btn.grid(row=1, column=2, padx=(6, 4), pady=3)

    # ============================================================
    # 交互逻辑
    # ============================================================

    def _on_tab_change(self):
        """切换标签页时清空另一页的工序号输入"""
        current = self.tabview.get()
        if current == self.date_tab_name:
            self.month_stepno_entry.delete(0, "end")
        else:
            self.date_stepno_entry.delete(0, "end")

    def _browse_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self._output_dir)
        if selected:
            self._output_dir = Path(selected)
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, str(self._output_dir))

    def _bind_close_handler(self):
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self._running:
            result = messagebox.askyesno(
                "确认退出", "正在导出数据，确定要退出吗？\n\n已导出的数据会保留。",
            )
            if result:
                self._cancel_event.set()
                self.destroy()
        else:
            self.destroy()

    def _parse_stepno(self, text: str) -> list[int] | None:
        text = text.strip()
        if not text:
            return None
        try:
            return [int(s.strip()) for s in text.split(",") if s.strip()]
        except ValueError:
            raise ValueError(f"工序号格式错误: {text}\n请使用逗号分隔的数字，如: 69,70")

    def _get_db_host(self) -> str:
        return DB_HOST_LABELS.get(self.db_combo.get(), "192.168.4.19")

    # ============================================================
    # 导出控制
    # ============================================================

    def _start_export(self):
        current_tab = self.tabview.get()

        if current_tab == self.date_tab_name:
            date_str = self.date_entry.get().strip()
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                messagebox.showerror("格式错误", f"日期格式错误: {date_str}\n请使用 YYYY-MM-DD 格式")
                return

            try:
                stepno_filter = self._parse_stepno(self.date_stepno_entry.get())
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

        else:
            month_str = self.month_entry.get().strip()
            parts = month_str.split("-")
            if len(parts) not in (2, 3):
                messagebox.showerror("格式错误", f"月份/日期格式错误: {month_str}\n请使用 YYYY-MM 或 YYYY-MM-DD")
                return
            if len(parts) == 3:
                try:
                    datetime.strptime(month_str, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("格式错误", f"日期格式错误: {month_str}")
                    return
            if len(parts) == 2:
                y, m = parts
                if not (y.isdigit() and m.isdigit() and 1 <= int(m) <= 12):
                    messagebox.showerror("格式错误", f"月份格式错误: {month_str}")
                    return

            try:
                stepno_filter = self._parse_stepno(self.month_stepno_entry.get())
            except ValueError as e:
                messagebox.showerror("格式错误", str(e))
                return

            target_func = export_month_to_xlsx
            kwargs = {
                "target_month": month_str,
                "output_dir": self._output_dir,
                "stepno_filter": stepno_filter,
                "db_host": self._get_db_host(),
                "progress_callback": self._on_progress,
                "cancel_event": self._cancel_event,
            }

        self._cancel_event.clear()
        self._progress_count = 0
        self._running = True
        self._set_controls_state("disabled")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self._update_status("正在连接数据库...", C_TEXT_DIM)

        self._worker = threading.Thread(target=self._run_export, args=(target_func, kwargs), daemon=True)
        self._worker.start()
        self._poll_progress()

    def _run_export(self, func, kwargs):
        try:
            self._result = func(**kwargs)
        except Exception as e:
            self._error = str(e)
            self._result = None
        else:
            self._error = None

    def _on_progress(self, count: int):
        self._progress_count = count

    def _poll_progress(self):
        if not self._running:
            return
        if self._worker and self._worker.is_alive():
            if self._progress_count > 0:
                self._update_status("导出中...", C_ACCENT)
                self.count_label.configure(text=f"已导出  {self._progress_count:,}  条")
            self.after(100, self._poll_progress)
        else:
            self._export_finished()

    def _export_finished(self):
        self._running = False
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(1)
        self._set_controls_state("normal")

        if self._error:
            self._update_status("导出失败", C_DANGER)
            self.count_label.configure(text="")
            messagebox.showerror("导出失败", f"数据库错误:\n{self._error}")
        elif self._result is None:
            self._update_status("未执行", C_TEXT_MUTED)
        elif self._result < 0:
            count = -self._result
            self._update_status(f"已取消 ({count:,} 条)", C_ORANGE)
            self.count_label.configure(text=f"已导出 {count:,} 条（部分数据已保存）")
        elif self._result == 0:
            self._update_status("无数据或连接失败", C_WARNING)
            self.count_label.configure(text="")
            messagebox.showwarning("提示", "未查询到数据，请检查日期是否正确。")
        else:
            self._update_status("导出完成", C_SUCCESS)
            self.count_label.configure(text=f"共导出  {self._result:,}  条记录")
            messagebox.showinfo("导出完成", f"数据已导出成功！\n\n共 {self._result:,} 条记录")

    def _update_status(self, text, color):
        self.status_label.configure(text=text, text_color=color)

    def _cancel_export(self):
        if self._running:
            self._cancel_event.set()
            self._update_status("正在取消...", C_ORANGE)
            self.cancel_btn.configure(state="disabled")

    def _set_controls_state(self, state: str):
        self.date_entry.configure(state=state)
        self.date_stepno_entry.configure(state=state)
        self.month_entry.configure(state=state)
        self.month_stepno_entry.configure(state=state)
        self.db_combo.configure(state=state)
        self.output_entry.configure(state=state)
        self.browse_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if state == "disabled" else "disabled")


if __name__ == "__main__":
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("green")
    app = ExportApp()
    app.mainloop()
