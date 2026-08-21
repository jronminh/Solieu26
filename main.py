"""
main.py: Tkinter GUI entry point, holding the App class (main window, logging,
info panel, embedded "Tải số liệu theo khoảng" panel) and wiring up runner.Runner,
auto_query.AutoQuery, viewer.HistoryViewer, dialogs.SettingsDialog,
forecast_editor.ForecastEditor, and score_viewer.ScoreViewer. Run:
python main.py [config.ini path].

Tác giả: congminh9981 (congminh9981@gmail.com); Claude (Anthropic), đồng tác giả.
"""

import datetime
import os
import sys

import tkinter as tk
from tkinter import ttk, scrolledtext

from utils import config_utils as config
from common import LOG_COLORS
from runner import Runner
from auto_query import AutoQuery
from viewer import HistoryViewer
from dialogs import SettingsDialog
from forecast_editor import ForecastEditor
from score_viewer import ScoreViewer

MAX_LOG_LINES = 2000   # oldest lines get trimmed past this (see _log())


class App:
    def __init__(self, root: tk.Tk, config_path: str = None):
        self.root = root
        self._dialogs = {}          # keeps references to open dialogs (avoids reopening duplicates)
        self.runner = Runner(self)
        self.auto_query = AutoQuery(self)

        # Load the external config (if any) BEFORE prefilling the form. The log
        # widget doesn't exist yet at this point, so buffer any per-key WARNs
        # (bad config.ini values) and flush them into it once _build_ui() runs
        # below, otherwise they'd only reach stdout, which a windowed build
        # (console=False) has no visible console for at all.
        config_log_buffer = []
        self.cfg_path, self.cfg_overrides = config.apply_config_file(
            config_path, log=lambda level, msg: config_log_buffer.append((level, msg)))

        root.title("Solieu26")
        root.minsize(200, 150)   # temporary low floor, replaced below once real content is laid out
        icon_path = os.path.join(config.SCRIPT_DIR, "icon.ico")
        if os.path.isfile(icon_path):
            try:
                root.iconbitmap(icon_path)
            except tk.TclError:
                pass   # e.g. platform without .ico support, window just keeps the default icon

        # CSV viewer Treeview look: taller rows + bold headings read better than
        # the ttk defaults across the many columns a data row can have.
        style = ttk.Style(root)
        style.configure("Treeview", rowheight=22)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        d = config.CONFIG
        today = datetime.date.today()

        self.v = {
            "ftp_host":    tk.StringVar(value=d.get("ftp_host", "")),
            "ftp_user":    tk.StringVar(value=d.get("ftp_user", "")),
            "ftp_pass":    tk.StringVar(value=d.get("ftp_pass", "")),
            "remote_dir":  tk.StringVar(value=d.get("remote_dir", "/Quantrac")),
            "output_dir":  tk.StringVar(value=d.get("output_dir") or config.DEFAULT_OUTPUT_DIR),
            # "Tải số liệu theo khoảng" panel's date range, defaults to today so
            # "Bắt đầu" with no changes behaves like a plain current-day fetch.
            "start_date":  tk.StringVar(value=today.strftime("%Y-%m-%d")),
            "end_date":    tk.StringVar(value=today.strftime("%Y-%m-%d")),
            "auto_value":  tk.StringVar(value=str(d.get("auto_query_value", 15))),
            "auto_unit":   tk.StringVar(value="Giờ" if d.get("auto_query_unit", "minutes") == "hours" else "Phút"),
            "auto_on_startup": tk.BooleanVar(value=bool(d.get("auto_query_on_startup", True))),
        }

        # Read-only labels in the "Thông tin truy vấn" panel, recomputed by
        # _refresh_info_panel() whenever the underlying state changes.
        self.info = {
            "csv_result":    tk.StringVar(value="-"),
            "data_status":   tk.StringVar(value="Chưa có dữ liệu"),
            "auto_status":   tk.StringVar(value="-"),
            "missing":       tk.StringVar(value="-"),
        }

        # The 3 heavier UI pieces, constructed once and kept for the app's
        # lifetime, so each one's own state (HistoryViewer.hidden_cols,
        # AdvancedDialog's widget refs...) survives across open/close cycles.
        self.history_viewer = HistoryViewer(self)
        self.settings_dialog = SettingsDialog(self)
        self.forecast_editor = ForecastEditor(self)
        self.score_viewer = ScoreViewer(self)

        self._build_ui()
        self._fit_window_to_content()
        # Floor = the natural size with every field + the log shown.
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.after(100, self.runner._poll)
        for level, msg in config_log_buffer:
            self._log(level, msg)
        self._log("INFO", "Khởi động xong, sẵn sàng. Điền thông tin rồi bấm 'Bắt đầu'.")
        if self.cfg_overrides:
            self._log("OK", f"Đã nạp {len(self.cfg_overrides)} thiết lập từ config: {self.cfg_path}")
        else:
            self._log("INFO", f"Không thấy config ({self.cfg_path}), dùng mặc định trong mã.")
        self.auto_query._schedule_auto_tick()   # also refreshes the info panel's auto-query status

        if self.v["auto_on_startup"].get():
            self._log("ACT", "Tự động truy vấn khi khởi động")
            self.root.after(300, self.runner._on_run)   # small delay so the window renders first

    # ----- UI construction ---------------------------------------------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # Banner: shown only while a fetch is running (see refresh_range_panel_state).
        # Packed/unpacked dynamically with before=content_row so it always sits
        # above the info panel when visible, never appended after it.
        self.pause_banner = ttk.Label(
            frm, text="Tự động: Tạm dừng — đang tải số liệu",
            background="#fbeed9", foreground="#b45309", padding=(8, 4), anchor="w")

        # --- Hàng nội dung chính: Thông tin truy vấn + panel khoảng ngày (trái) + cột nút (phải) ---
        content_row = ttk.Frame(frm)
        content_row.pack(fill="x")
        self._content_row = content_row

        left_col = ttk.Frame(content_row)
        left_col.pack(side="left", fill="both", expand=True)

        # --- Thông tin truy vấn --- (read-only status; recomputed by _refresh_info_panel)
        top = ttk.Frame(left_col)
        top.pack(fill="x")

        def info_row(r, caption, var=None, widget=None):
            """One grid row: caption label + either a read-only value (var, as a
            Label) or an editable/composite widget passed in directly."""
            cap = ttk.Label(top, text=caption)
            val = widget if widget is not None else ttk.Label(top, textvariable=var)
            cap.grid(row=r, column=0, sticky="w", padx=6, pady=2)
            val.grid(row=r, column=1, sticky="ew" if widget is not None else "w", padx=6, pady=2)

        info_row(0, "Máy chủ:", self.v["ftp_host"])
        info_row(1, "Xuất CSV:", self.info["csv_result"])
        info_row(2, "Dữ liệu:", self.info["data_status"])
        info_row(3, "Tự động:", self.info["auto_status"])
        info_row(4, "File thiếu:", self.info["missing"])
        top.columnconfigure(1, weight=1)

        # --- Tải số liệu theo khoảng: nhúng thẳng, luôn hiện (không còn dialog riêng) ---
        range_box = ttk.LabelFrame(left_col, text="Tải số liệu theo khoảng", padding=8)
        range_box.pack(fill="x", pady=(10, 0))
        ttk.Label(range_box, text="Từ ngày:").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.start_date_entry = ttk.Entry(range_box, textvariable=self.v["start_date"], width=12)
        self.start_date_entry.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(range_box, text="Đến ngày:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.end_date_entry = ttk.Entry(range_box, textvariable=self.v["end_date"], width=12)
        self.end_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        range_btn_row = ttk.Frame(range_box)
        range_btn_row.grid(row=2, column=0, columnspan=2, sticky="e", pady=(6, 0))
        self.now_btn = ttk.Button(range_btn_row, text="Về hiện tại", command=self._on_range_now)
        self.now_btn.pack(side="left", padx=(0, 6))
        self.start_btn = ttk.Button(range_btn_row, text="Bắt đầu", command=self._on_range_start)
        self.start_btn.pack(side="left")

        # --- Tiến trình: text "Tải n/m" + progress bar % ---
        progress_box = ttk.LabelFrame(left_col, text="Tiến trình", padding=8)
        progress_box.pack(fill="x", pady=(10, 0))
        self.progress_label = ttk.Label(progress_box, text="Tải 0/0")
        self.progress_label.pack(side="left")
        self.progress_bar = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=8)
        self.progress_pct_label = ttk.Label(progress_box, text="0%", width=5, anchor="e")
        self.progress_pct_label.pack(side="left")

        # --- Cột nút, bên phải, xếp dọc theo thứ tự: Xem số liệu, Dự báo, Xem
        # chấm điểm, Thiết lập.
        btn_col = ttk.Frame(content_row)
        btn_col.pack(side="left", padx=(12, 0), anchor="n")
        ttk.Button(btn_col, text="Xem số liệu",
                  command=self.history_viewer.open_latest).pack(fill="x")
        self.forecast_btn = ttk.Button(btn_col, text="Dự báo", command=self.forecast_editor.open)
        self.forecast_btn.pack(fill="x", pady=(4, 0))
        self.score_btn = ttk.Button(btn_col, text="Xem chấm điểm", command=self.score_viewer.open)
        self.score_btn.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="Thiết lập...",
                  command=self.settings_dialog.open).pack(fill="x", pady=(4, 0))

        # --- Status bar at the BOTTOM ---
        statusbar = ttk.Frame(frm)
        statusbar.pack(side="bottom", fill="x", pady=(6, 0))
        self.status = ttk.Label(statusbar, text="Sẵn sàng", anchor="e")
        self.status.pack(side="right")

        # --- Log (fills the middle, sits above the status bar) ---
        log_frame = ttk.Frame(frm)
        log_frame.pack(side="top", fill="both", expand=True, pady=(8, 0))
        self.log_count_label = ttk.Label(log_frame, text=f"0 / {MAX_LOG_LINES} dòng",
                                         foreground="#6b7280", anchor="e")
        self.log_count_label.pack(side="bottom", fill="x")
        self.log = scrolledtext.ScrolledText(log_frame, height=12, state="disabled",
                                             wrap="word", font=("Consolas", 9))
        self.log.pack(side="top", fill="both", expand=True)

        # Color tags for each part of a log line
        self.log.tag_config("ts", foreground="#9ca3af")          # timestamp (light gray)
        for lvl, color in LOG_COLORS.items():                    # level
            self.log.tag_config("lvl_" + lvl, foreground=color)

        self.refresh_range_panel_state()

    def _fit_window_to_content(self):
        """Shrink/grow the main window to fit its currently packed widgets (e.g. after
        showing/hiding the log frame) instead of leaving stale empty space."""
        self.root.update_idletasks()
        self.root.geometry("")

    # ----- Logging -------------------------------------------------------
    def _log(self, level: str, msg: str):
        """Write one log line in the standard format:  HH:MM:SS  LEVEL  message.

        Inserts 3 separately-tagged chunks (time / level / content) so each part
        gets its own color. ONLY call from the main thread; the worker must push
        onto the queue and let _poll call this on its behalf.
        """
        level = level.upper()
        if level not in LOG_COLORS:
            level = "INFO"
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", ts + "  ", "ts")
        self.log.insert("end", f"{level:<4}", "lvl_" + level)
        self.log.insert("end", "  " + msg + "\n")
        self._trim_log()
        self.log.see("end")
        self.log.config(state="disabled")

    def _divider(self):
        """Draw a faint separator line between runs for readability."""
        self.log.config(state="normal")
        self.log.insert("end", "─" * 60 + "\n", "ts")
        self._trim_log()
        self.log.see("end")
        self.log.config(state="disabled")

    def _trim_log(self):
        """Xoá dòng cũ nhất nếu log vượt MAX_LOG_LINES, cập nhật label đếm dòng.
        Gọi trong lúc self.log đang state="normal" (giữa 2 lần config ở _log/_divider)."""
        line_count = int(self.log.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self.log.delete("1.0", f"{line_count - MAX_LOG_LINES + 1}.0")
            line_count = MAX_LOG_LINES
        self.log_count_label.config(text=f"{line_count} / {MAX_LOG_LINES} dòng")

    # ----- Info panel ("Thông tin truy vấn") --------------------------
    def _refresh_info_panel(self):
        """Recompute every label in the info panel from current state (last run result,
        auto-query schedule). Cheap: just StringVar.set() calls, safe to call often."""
        result = self.runner.last_result or {}

        if self.runner.last_result is not None:
            hr = result.get("history_records", 0)
            history_files = result.get("history_files") or {}
            self.info["csv_result"].set(f"{hr} record · {len(history_files)} ngày (history_*.csv)")
            missing = len(result.get("missing") or [])
            self.info["missing"].set("Không thiếu" if missing == 0 else f"{missing} file")
        else:
            self.info["csv_result"].set("-")
            self.info["missing"].set("-")

        if self.runner.last_cfg and self.runner.last_updated_at:
            start, end = self.runner.last_cfg["start_date"], self.runner.last_cfg["end_date"]
            if start.date() == end.date():
                rng = f"Ngày {start:%Y-%m-%d}"
            else:
                rng = f"{start:%Y-%m-%d} → {end:%Y-%m-%d}"
            self.info["data_status"].set(f"{rng}, cập nhật lúc {self.runner.last_updated_at:%H:%M:%S}")
        else:
            self.info["data_status"].set("Chưa có dữ liệu")

        if self.runner._run_in_progress:
            self.info["auto_status"].set("Tạm dừng, đang tải số liệu")
            return

        if self.auto_query._auto_effective_minutes() <= 0:
            self.info["auto_status"].set("Tắt")
        else:
            v, unit = self.v["auto_value"].get(), self.v["auto_unit"].get().lower()
            next_run = self.auto_query.auto_next_run
            next_run_txt = f" (tiếp theo: {next_run:%H:%M:%S})" if next_run else ""
            self.info["auto_status"].set(f"Bật, mỗi {v} {unit}{next_run_txt}")

    # ----- Panel "Tải số liệu theo khoảng" + banner tạm dừng ------------
    def refresh_range_panel_state(self):
        """Khóa 'Bắt đầu' + hiện/ẩn banner tạm dừng theo runner._run_in_progress.
        Gọi từ Runner._set_actions_enabled() ở cả 2 đầu (bắt đầu chạy/chạy xong)."""
        running = self.runner._run_in_progress
        self.start_btn.config(state="disabled" if running else "normal")
        if running:
            self.pause_banner.pack(fill="x", pady=(0, 8), before=self._content_row)
        else:
            self.pause_banner.pack_forget()
        self._refresh_info_panel()

    def _on_range_now(self):
        """'Về hiện tại': ép Từ ngày/Đến ngày về hôm nay."""
        now = datetime.datetime.now()
        self.v["start_date"].set(now.strftime("%Y-%m-%d"))
        self.v["end_date"].set(now.strftime("%Y-%m-%d"))
        self._log("ACT", f"Về hiện tại: ngày {now:%Y-%m-%d}")

    def _on_range_start(self):
        """'Bắt đầu': chạy truy vấn theo khoảng ngày đang nhập trong panel."""
        self.runner._on_run()

    def _set_download_progress(self, done: int, total: int):
        self.progress_label.config(text=f"Tải {done}/{total}")
        pct = (done / total * 100) if total else 0
        self.progress_bar["value"] = pct
        self.progress_pct_label.config(text=f"{pct:.0f}%")


def main():
    # Allows: python main.py [config_ini_path]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    App(root, config_path=config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
