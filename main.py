"""
main.py: Tkinter GUI entry point, holding the App class (single main window with
a ttk.Notebook: Số liệu / Dự báo / Xem chấm điểm / Tải số liệu theo khoảng / Log /
Thiết lập) and wiring up runner.Runner, auto_query.AutoQuery, viewer.HistoryViewer,
dialogs.SettingsDialog, forecast_editor.ForecastEditor, score_viewer.ScoreViewer.
Run: python main.py [config.ini path].

Tác giả: congminh9981 (congminh9981@gmail.com); Claude (Anthropic), đồng tác giả.
"""

import datetime
import os
import sys

import tkinter as tk
from tkinter import ttk, scrolledtext

from utils import config_utils as config
from common import LOG_COLORS
from pipeline.fetch import expected_hours
from utils.filename_utils import quantrac_filename_at
from runner import Runner
from auto_query import AutoQuery
from viewer import HistoryViewer
from dialogs import SettingsDialog
from forecast_editor import ForecastEditor
from score_viewer import ScoreViewer

MAX_LOG_LINES = 2000   # oldest lines get trimmed past this (see _log())

# Hàng đợi status codes from pipeline.fetch's progress callback (see utils/ftp_utils.py).
_QUEUE_STATUS_LABEL = {0: "Đã tải", 1: "Đã có sẵn", 2: "Không tải được"}


class App:
    def __init__(self, root: tk.Tk, config_path: str = None):
        self.root = root
        self._dialogs = {}          # keeps references to small aux popups (column pickers, etc.)
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
            # "Tải số liệu theo khoảng" tab's date range, defaults to today so
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

        # The 4 tab controllers, constructed once and kept for the app's
        # lifetime alongside their tab's widgets (hidden_cols, loaded records...).
        self.history_viewer = HistoryViewer(self)
        self.settings_dialog = SettingsDialog(self)
        self.forecast_editor = ForecastEditor(self)
        self.score_viewer = ScoreViewer(self)

        self._queue_rows = {}   # Hàng đợi: filename -> Treeview iid, rebuilt each "Bắt đầu"

        self._build_ui()
        self._fit_window_to_content()
        # Floor well below the default size, so the window stays freely
        # resizable/shrinkable instead of getting stuck at its startup size.
        self.root.minsize(800, 500)
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

        # Status bar packed FIRST (reserves its space at the bottom) so the
        # Notebook below can still fill+expand into the remaining room.
        statusbar = ttk.Frame(frm)
        statusbar.pack(side="bottom", fill="x", pady=(6, 0))
        self.status = ttk.Label(statusbar, text="Sẵn sàng", anchor="e")
        self.status.pack(side="right")

        notebook = ttk.Notebook(frm)
        notebook.pack(fill="both", expand=True)
        self.notebook = notebook

        tab_main = ttk.Frame(notebook, padding=10)
        tab_forecast = ttk.Frame(notebook, padding=10)
        tab_score = ttk.Frame(notebook, padding=10)
        tab_load = ttk.Frame(notebook, padding=10)
        tab_log = ttk.Frame(notebook, padding=10)
        tab_settings = ttk.Frame(notebook, padding=10)

        notebook.add(tab_main, text="Số liệu")
        notebook.add(tab_forecast, text="Dự báo")
        notebook.add(tab_score, text="Xem chấm điểm")
        notebook.add(tab_load, text="Tải số liệu theo khoảng")
        notebook.add(tab_log, text="Log")
        notebook.add(tab_settings, text="Thiết lập")

        # Log tab built FIRST: the other tabs auto-load a file as part of
        # build() (e.g. Số liệu/Dự báo load today's data right away) and that
        # logs through self.log, which must exist before they run.
        self._build_log_tab(tab_log)
        self.history_viewer.build(tab_main)
        self.forecast_editor.build(tab_forecast)
        self.score_viewer.build(tab_score)
        self._build_load_tab(tab_load)
        self.settings_dialog.build(tab_settings)

        self.refresh_range_panel_state()

    def _build_load_tab(self, parent):
        """Tab 'Tải số liệu theo khoảng': banner tạm dừng (chỉ hiện khi đang
        chạy) + Thông tin truy vấn + khoảng ngày + Hàng đợi + tiến trình."""
        # Banner: shown only while a fetch is running (see refresh_range_panel_state).
        self.pause_banner = ttk.Label(
            parent, text="Tác vụ này sẽ tạm dừng tự động truy vấn cho tới khi hoàn tất hoặc hủy",
            background="#fbeed9", foreground="#b45309", padding=(8, 4), anchor="w")

        # --- Thông tin truy vấn --- (read-only status; recomputed by _refresh_info_panel)
        info_box = ttk.LabelFrame(parent, text="Thông tin truy vấn", padding=8)
        info_box.pack(fill="x")
        self._load_tab_info_box = info_box   # anchor so the pause banner can pack "before" it

        def info_row(r, caption, var):
            ttk.Label(info_box, text=caption).grid(row=r, column=0, sticky="w", padx=6, pady=2)
            ttk.Label(info_box, textvariable=var).grid(row=r, column=1, sticky="w", padx=6, pady=2)

        info_row(0, "Máy chủ:", self.v["ftp_host"])
        info_row(1, "Xuất CSV:", self.info["csv_result"])
        info_row(2, "Dữ liệu:", self.info["data_status"])
        info_row(3, "Tự động:", self.info["auto_status"])
        info_row(4, "File thiếu:", self.info["missing"])
        info_box.columnconfigure(1, weight=1)

        # --- Khoảng thời gian ---
        range_box = ttk.LabelFrame(parent, text="Khoảng thời gian", padding=8)
        range_box.pack(fill="x", pady=(10, 0))
        ttk.Label(range_box, text="Từ ngày:").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.start_date_entry = ttk.Entry(range_box, textvariable=self.v["start_date"], width=12)
        self.start_date_entry.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(range_box, text="Đến ngày:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.end_date_entry = ttk.Entry(range_box, textvariable=self.v["end_date"], width=12)
        self.end_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        range_btn_row = ttk.Frame(range_box)
        range_btn_row.grid(row=2, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(range_btn_row, text="7 ngày trước",
                   command=lambda: self._on_range_days_ago(7)).pack(side="left", padx=(0, 6))
        ttk.Button(range_btn_row, text="30 ngày trước",
                   command=lambda: self._on_range_days_ago(30)).pack(side="left", padx=(0, 6))
        self.now_btn = ttk.Button(range_btn_row, text="Về hiện tại", command=self._on_range_now)
        self.now_btn.pack(side="left")

        # --- Hàng đợi: 1 dòng/file dự kiến, cập nhật Trạng thái khi tiến trình báo về ---
        self.queue_box = ttk.LabelFrame(parent, text="Hàng đợi (0 file dự kiến)", padding=8)
        self.queue_box.pack(fill="both", expand=True, pady=(10, 0))
        queue_frame = ttk.Frame(self.queue_box)
        queue_frame.pack(fill="both", expand=True)
        queue_tree = ttk.Treeview(queue_frame, columns=("date", "hour", "status"),
                                  show="headings", height=6)
        queue_tree.heading("date", text="Ngày")
        queue_tree.column("date", width=100, anchor="w")
        queue_tree.heading("hour", text="Giờ")
        queue_tree.column("hour", width=50, anchor="center")
        queue_tree.heading("status", text="Trạng thái")
        queue_tree.column("status", width=140, anchor="w")
        vsb = ttk.Scrollbar(queue_frame, orient="vertical", command=queue_tree.yview)
        queue_tree.configure(yscrollcommand=vsb.set)
        queue_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.queue_tree = queue_tree

        # --- Tiến trình: text "Tải n/m" + progress bar % ---
        progress_box = ttk.LabelFrame(parent, text="Tiến trình", padding=8)
        progress_box.pack(fill="x", pady=(10, 0))
        self.progress_label = ttk.Label(progress_box, text="Tải 0/0")
        self.progress_label.pack(side="left")
        self.progress_bar = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=8)
        self.progress_pct_label = ttk.Label(progress_box, text="0%", width=5, anchor="e")
        self.progress_pct_label.pack(side="left")

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(btn_row, text="Bắt đầu", command=self._on_range_start)
        self.start_btn.pack(side="right")

    def _build_log_tab(self, parent):
        self.log_count_label = ttk.Label(parent, text=f"0 / {MAX_LOG_LINES} dòng",
                                         foreground="#6b7280", anchor="e")
        self.log_count_label.pack(side="bottom", fill="x")
        self.log = scrolledtext.ScrolledText(parent, state="disabled",
                                             wrap="word", font=("Consolas", 9))
        self.log.pack(side="top", fill="both", expand=True)

        # Color tags for each part of a log line
        self.log.tag_config("ts", foreground="#9ca3af")          # timestamp (light gray)
        for lvl, color in LOG_COLORS.items():                    # level
            self.log.tag_config("lvl_" + lvl, foreground=color)

    def _fit_window_to_content(self):
        """Size the window to fit its content, capped so it always fits on an
        HD (1280x720) screen: the Số liệu tab's table can run to 15+ columns,
        whose natural width alone would otherwise overflow a small screen."""
        self.root.update_idletasks()
        # Content caps (window chrome + a 1280x720 screen's taskbar add ~55px
        # height / ~20px width on top of this before it's on screen).
        max_w = min(1150, self.root.winfo_screenwidth() - 40)
        max_h = min(600, self.root.winfo_screenheight() - 100)
        w = min(self.root.winfo_reqwidth(), max_w)
        h = min(self.root.winfo_reqheight(), max_h)
        self.root.geometry(f"{w}x{h}")

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

    # ----- Tab "Tải số liệu theo khoảng" + banner tạm dừng ------------
    def refresh_range_panel_state(self):
        """Khóa 'Bắt đầu' + hiện/ẩn banner tạm dừng theo runner._run_in_progress.
        Gọi từ Runner._set_actions_enabled() ở cả 2 đầu (bắt đầu chạy/chạy xong)."""
        running = self.runner._run_in_progress
        self.start_btn.config(state="disabled" if running else "normal")
        if running:
            self.pause_banner.pack(fill="x", pady=(0, 8), before=self._load_tab_info_box)
        else:
            self.pause_banner.pack_forget()
        self._refresh_info_panel()

    def _on_range_now(self):
        """'Về hiện tại': ép Từ ngày/Đến ngày về hôm nay."""
        now = datetime.datetime.now()
        self.v["start_date"].set(now.strftime("%Y-%m-%d"))
        self.v["end_date"].set(now.strftime("%Y-%m-%d"))
        self._log("ACT", f"Về hiện tại: ngày {now:%Y-%m-%d}")

    def _on_range_days_ago(self, days: int):
        """'N ngày trước': Từ ngày = hôm nay - N, Đến ngày = hôm nay."""
        now = datetime.datetime.now()
        start = now - datetime.timedelta(days=days)
        self.v["start_date"].set(start.strftime("%Y-%m-%d"))
        self.v["end_date"].set(now.strftime("%Y-%m-%d"))
        self._log("ACT", f"{days} ngày trước: {start:%Y-%m-%d} → {now:%Y-%m-%d}")

    def _on_range_start(self):
        """'Bắt đầu': chạy truy vấn theo khoảng ngày đang nhập trong tab."""
        self.runner._on_run()

    # ----- Hàng đợi ("Tải số liệu theo khoảng" tab) ----------------------
    def _reset_download_queue(self, start_date, end_date):
        """Seed the Hàng đợi table with one 'Chờ' row per file the upcoming run
        will attempt, in the exact order pipeline.fetch.download_files() visits
        them. Called by Runner._on_run() right before the worker thread starts."""
        hours = expected_hours(start_date, end_date)
        self.queue_tree.delete(*self.queue_tree.get_children())
        self._queue_rows = {}
        for ts in hours:
            filename = quantrac_filename_at(ts)
            iid = self.queue_tree.insert("", "end", values=(ts.strftime("%d/%m/%Y"), f"{ts:%H}", "Chờ"))
            self._queue_rows[filename] = iid
        self.queue_box.config(text=f"Hàng đợi ({len(hours)} file dự kiến)")

    def _set_download_progress(self, done: int, total: int, status=None, filename=None):
        self.progress_label.config(text=f"Tải {done}/{total}")
        pct = (done / total * 100) if total else 0
        self.progress_bar["value"] = pct
        self.progress_pct_label.config(text=f"{pct:.0f}%")

        if filename is not None:
            iid = self._queue_rows.get(filename)
            if iid is not None and self.queue_tree.exists(iid):
                label = _QUEUE_STATUS_LABEL.get(status, "?")
                date, hour, _ = self.queue_tree.item(iid, "values")
                self.queue_tree.item(iid, values=(date, hour, label))


def main():
    # Allows: python main.py [config_ini_path]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    App(root, config_path=config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
