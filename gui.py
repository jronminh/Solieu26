"""
gui.py
===================
Tkinter GUI entry point + the App class (the spine): main window, worker
thread, run-pipeline glue, logging, auto-query timer, info panel.

The three heavier UI pieces live in their own modules as standalone classes —
history_viewer.HistoryViewer ("Xem số liệu"), dialogs.SettingsDialog
("Thiết lập") and dialogs.AdvancedDialog ("Tải số liệu") — each constructed
once in App.__init__ and holding the `app` instance so it can reach back into
shared state (self.app.v, self.app._log, self.app._dialogs, ...).

Run:  python gui.py [config.ini path]
Requires config.py/decode.py/csv_pipeline.py/gui_common.py/history_viewer.py/dialogs.py
in the same folder.

Anti-freeze architecture: heavy work (FTP + decode + CSV export, all in csv_pipeline.py)
runs on a worker thread that never touches widgets — it only pushes ('log' /
'progress' / 'done' / 'error') events onto a queue.Queue(); the main thread
polls the queue every 100ms via root.after() and applies the UI updates itself.

Tác giả: congminh9981 (congminh9981@gmail.com); Claude (Anthropic) — đồng tác giả.
"""

import datetime
import os
import queue
import sys
import threading

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

import config
import csv_pipeline
from gui_common import LOG_COLORS
from history_viewer import HistoryViewer
from dialogs import SettingsDialog, AdvancedDialog


class App:
    def __init__(self, root: tk.Tk, config_path: str = None):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self._run_in_progress = False  # mirrors _set_actions_enabled — feeds advanced_dialog.refresh_controls_state
        self.last_output_dir = None
        self.auto_job = None        # root.after() id for the pending auto-query tick
        self.auto_next_run = None   # datetime of the next scheduled auto-query tick (None = off)
        self.last_result = None     # result dict from the last completed run (for the info panel)
        self.last_cfg = None        # cfg dict from the last _on_run (carries the queried date)
        self.last_updated_at = None # datetime the last run finished (success or not)
        self._dialogs = {}          # keeps references to open dialogs (avoids reopening duplicates)

        # Load the external config (if any) BEFORE prefilling the form. The log
        # widget doesn't exist yet at this point, so buffer any per-key WARNs
        # (bad config.ini values) and flush them into it once _build_ui() runs
        # below — otherwise they'd only reach stdout, which a windowed build
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
                pass   # e.g. platform without .ico support — window just keeps the default icon

        # CSV viewer Treeview look — taller rows + bold headings read better than
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
            # Advanced mode (date-range query) — off by default; normal mode always
            # queries "today", no date field shown.
            "advanced_mode": tk.BooleanVar(value=False),
            "start_date":  tk.StringVar(value=today.strftime("%Y-%m-%d")),
            "end_date":    tk.StringVar(value=today.strftime("%Y-%m-%d")),
            "auto_value":  tk.StringVar(value=str(d.get("auto_query_value", 15))),
            "auto_unit":   tk.StringVar(value="Giờ" if d.get("auto_query_unit", "minutes") == "hours" else "Phút"),
            "auto_on_startup": tk.BooleanVar(value=bool(d.get("auto_query_on_startup", True))),
        }

        # Read-only labels in the "Thông tin truy vấn" panel — recomputed by
        # _refresh_info_panel() whenever the underlying state changes.
        self.info = {
            "csv_result":    tk.StringVar(value="—"),
            "data_status":   tk.StringVar(value="Chưa có dữ liệu"),
            "auto_status":   tk.StringVar(value="—"),
            "missing":       tk.StringVar(value="—"),
        }

        # The 3 heavier UI pieces — constructed once and kept for the app's
        # lifetime, so each one's own state (HistoryViewer.hidden_cols,
        # AdvancedDialog's widget refs...) survives across open/close cycles.
        self.history_viewer = HistoryViewer(self)
        self.settings_dialog = SettingsDialog(self)
        self.advanced_dialog = AdvancedDialog(self)

        self._build_ui()
        self._fit_window_to_content()
        # Floor = the natural size with every field + the log shown.
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.after(100, self._poll)
        for level, msg in config_log_buffer:
            self._log(level, msg)
        self._log("INFO", "Khởi động xong — sẵn sàng. Điền thông tin rồi bấm 'Làm mới'.")
        if self.cfg_overrides:
            self._log("OK", f"Đã nạp {len(self.cfg_overrides)} thiết lập từ config: {self.cfg_path}")
        else:
            self._log("INFO", f"Không thấy config ({self.cfg_path}) — dùng mặc định trong mã.")
        self._schedule_auto_tick()   # also refreshes the info panel's auto-query status

        if self.v["auto_on_startup"].get():
            self._log("ACT", "Tự động truy vấn khi khởi động")
            self.root.after(300, self._on_run)   # small delay so the window renders first

    # ----- UI construction ---------------------------------------------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # --- Hàng nội dung chính: Thông tin truy vấn (trái) + cột nút (phải) ---
        content_row = ttk.Frame(frm)
        content_row.pack(fill="x")

        # --- Thông tin truy vấn --- (read-only status; recomputed by _refresh_info_panel)
        # No LabelFrame border — laid directly on content_row.
        top = ttk.Frame(content_row)
        top.pack(side="left", fill="both", expand=True)

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

        # --- Cột nút, bên phải khung Thông tin truy vấn, xếp dọc theo thứ tự:
        # Làm mới, Tải số liệu, Xem số liệu, Thiết lập.
        btn_col = ttk.Frame(content_row)
        btn_col.pack(side="left", padx=(12, 0))
        self.refresh_btn = ttk.Button(btn_col, text="Làm mới", command=self._on_run)
        self.refresh_btn.pack(fill="x")
        ttk.Button(btn_col, text="Tải số liệu",
                  command=self.advanced_dialog.open).pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="Xem số liệu",
                  command=self.history_viewer.open_latest).pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="Thiết lập...",
                  command=self.settings_dialog.open).pack(fill="x", pady=(4, 0))

        # --- Status bar at the BOTTOM ---
        statusbar = ttk.Frame(frm)
        statusbar.pack(side="bottom", fill="x", pady=(6, 0))
        self.status = ttk.Label(statusbar, text="Sẵn sàng", anchor="e")
        self.status.pack(side="right")

        # --- Log (fills the middle, sits above the status bar) ---
        # No LabelFrame border — built regardless.
        self.log = scrolledtext.ScrolledText(frm, height=12, state="disabled",
                                             wrap="word", font=("Consolas", 9))
        self.log.pack(side="top", fill="both", expand=True, pady=(8, 0))

        # Color tags for each part of a log line
        self.log.tag_config("ts", foreground="#9ca3af")          # timestamp (light gray)
        for lvl, color in LOG_COLORS.items():                    # level
            self.log.tag_config("lvl_" + lvl, foreground=color)

        self.advanced_dialog.refresh_controls_state()

    def _fit_window_to_content(self):
        """Shrink/grow the main window to fit its currently packed widgets (e.g. after
        showing/hiding the log frame) instead of leaving stale empty space."""
        self.root.update_idletasks()
        self.root.geometry("")

    # ----- Logging -------------------------------------------------------
    def _log(self, level: str, msg: str):
        """Write one log line in the standard format:  HH:MM:SS  LEVEL  message.

        Inserts 3 separately-tagged chunks (time / level / content) so each part
        gets its own color. ONLY call from the main thread — the worker must push
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
        self.log.see("end")
        self.log.config(state="disabled")

    def _divider(self):
        """Draw a faint separator line between runs for readability."""
        self.log.config(state="normal")
        self.log.insert("end", "─" * 60 + "\n", "ts")
        self.log.see("end")
        self.log.config(state="disabled")

    # ----- Dialog helpers (generic) ---------------------------------------
    # Shared singleton-dialog helpers used by every popup window in the app.
    # App owns self._dialogs (the singleton registry), so it owns these too.
    def _make_dialog(self, key: str, title: str):
        """Create a singleton Toplevel: if already open, bring it to front and return None."""
        existing = self._dialogs.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify(); existing.lift(); existing.focus_set()
            return None
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        self._dialogs[key] = win
        return win

    def _center_over_root(self, win):
        """Position the dialog roughly centered over the main window for visibility."""
        win.update_idletasks()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{max(rx + (rw - ww)//2, 0)}+{max(ry + (rh - wh)//3, 0)}")

    # ----- Info panel ("Thông tin truy vấn") --------------------------
    def _refresh_info_panel(self):
        """Recompute every label in the info panel from current state (last run result,
        auto-query schedule). Cheap — just StringVar.set() calls — safe to call often."""
        result = self.last_result or {}

        if self.last_result is not None:
            hr = result.get("history_records", 0)
            history_files = result.get("history_files") or {}
            self.info["csv_result"].set(f"{hr} record · {len(history_files)} ngày (history_*.csv)")
            missing = len(result.get("missing") or [])
            self.info["missing"].set("Không thiếu" if missing == 0 else f"{missing} file")
        else:
            self.info["csv_result"].set("—")
            self.info["missing"].set("—")

        if self.last_cfg and self.last_updated_at:
            start, end = self.last_cfg["start_date"], self.last_cfg["end_date"]
            if start.date() == end.date():
                rng = f"Ngày {start:%Y-%m-%d}"
            else:
                rng = f"{start:%Y-%m-%d} → {end:%Y-%m-%d}"
            self.info["data_status"].set(f"{rng} — cập nhật lúc {self.last_updated_at:%H:%M:%S}")
        else:
            self.info["data_status"].set("Chưa có dữ liệu")

        if self.v["advanced_mode"].get():
            self.info["auto_status"].set("Tạm dừng — đang tải số liệu")
            return

        if self._auto_effective_minutes() <= 0:
            self.info["auto_status"].set("Tắt")
        else:
            v, unit = self.v["auto_value"].get(), self.v["auto_unit"].get().lower()
            next_run = f" (tiếp theo: {self.auto_next_run:%H:%M:%S})" if self.auto_next_run else ""
            self.info["auto_status"].set(f"Bật — mỗi {v} {unit}{next_run}")

    # ----- Auto-query (timer) ----------------------------------------
    def _auto_effective_minutes(self) -> int:
        """Current interval in minutes; 0 means auto-query is off."""
        try:
            v = int(self.v["auto_value"].get().strip())
        except ValueError:
            v = 0
        v = max(v, 0)
        return v * 60 if self.v["auto_unit"].get() == "Giờ" else v

    def _schedule_auto_tick(self):
        """(Re)schedule the next auto-query tick from the current value/unit; cancels any pending
        one first. Also tracks auto_next_run and refreshes the info panel's auto-query status."""
        if self.auto_job is not None:
            self.root.after_cancel(self.auto_job)
            self.auto_job = None
        minutes = self._auto_effective_minutes()
        if minutes <= 0:
            self.auto_next_run = None
        else:
            self.auto_next_run = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
            self.auto_job = self.root.after(minutes * 60 * 1000, self._on_auto_tick)
        self._refresh_info_panel()

    def _on_auto_tick(self):
        self.auto_job = None
        if self.worker and self.worker.is_alive():
            self._log("SKIP", "Tự động truy vấn: bỏ qua vì đang có tác vụ chạy")
        else:
            self._log("ACT", "Tự động truy vấn: chạy truy vấn")
            self._on_run()
        self._schedule_auto_tick()

    def _on_auto_change(self, event=None):
        """Entry/dropdown changed: normalize the value and reschedule the timer right away
        (takes effect immediately); persisting to config.ini happens via 'Lưu thiết lập'."""
        v = self._auto_effective_value()
        self.v["auto_value"].set(str(v))
        unit = self.v["auto_unit"].get()
        state = "tắt" if v == 0 else f"mỗi {v} {unit.lower()}"
        self._log("ACT", f"Tùy chọn 'Tự động truy vấn': {state}")
        self._schedule_auto_tick()

    def _auto_effective_value(self) -> int:
        try:
            return max(int(self.v["auto_value"].get().strip()), 0)
        except ValueError:
            return 0

    # ----- Run pipeline ("Làm mới" / "Bắt đầu") ----------------------------
    def _build_cfg(self) -> dict:
        """Read the form → cfg dict; local_dir/timeout/retry come from config's fixed constants.

        Always sets start_date/end_date — csv_pipeline.download_files() takes the fast
        single-day path when they're equal. Normal mode: always "today", no date
        field to read. Advanced mode (self.v["advanced_mode"], on while the "Tải
        số liệu" dialog is open): reads them from that dialog's fields instead.
        """
        cfg = {
            "ftp_host": self.v["ftp_host"].get().strip(),
            "ftp_user": self.v["ftp_user"].get().strip(),
            "ftp_pass": self.v["ftp_pass"].get(),
            "ftp_timeout": config.CONFIG.get("ftp_timeout", config.FTP_TIMEOUT),
            "retry_temp": config.CONFIG.get("retry_temp", config.RETRY_TEMP),
            "retry_wait": config.CONFIG.get("retry_wait", config.RETRY_WAIT),
            "remote_dir": self.v["remote_dir"].get().strip() or "/Quantrac",
            "local_dir":  config.TEMP_DL_DIR,
            "output_dir": self.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR,
        }

        if self.v["advanced_mode"].get():
            try:
                start = datetime.datetime.strptime(self.v["start_date"].get().strip(), "%Y-%m-%d")
                end = datetime.datetime.strptime(self.v["end_date"].get().strip(), "%Y-%m-%d")
            except ValueError:
                raise ValueError("Ngày bắt đầu/kết thúc phải theo định dạng YYYY-MM-DD, vd 2026-08-10")
            if end < start:
                raise ValueError("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu")
            cfg["start_date"] = start
            cfg["end_date"] = end
        else:
            today = datetime.datetime.combine(datetime.date.today(), datetime.time())
            cfg["start_date"] = cfg["end_date"] = today

        return cfg

    def _set_actions_enabled(self, enabled: bool):
        """Toggle 'Làm mới' — locked while a run is in progress. 'Bắt đầu' (trong
        dialog 'Tải số liệu', nếu đang mở) khóa/mở theo cùng trạng thái qua
        advanced_dialog.refresh_controls_state()."""
        self._run_in_progress = not enabled
        self.refresh_btn.config(state="normal" if enabled else "disabled")
        self.advanced_dialog.refresh_controls_state()

    def _on_run(self) -> bool:
        """Returns True iff a worker thread was actually started — False if
        skipped (a run is already in progress) or rejected (bad input). Callers
        that need to know whether the query truly started (e.g.
        AdvancedDialog._on_advanced_start, to decide whether to close the 'Tải
        số liệu' dialog) check this."""
        if self.worker and self.worker.is_alive():
            self._log("WARN", "Bỏ qua: một tác vụ đang chạy")
            return False
        try:
            cfg = self._build_cfg()
            if not cfg["ftp_host"]:
                raise ValueError("Chưa nhập FTP host")
        except ValueError as e:
            self._log("ERR", f"Nhập sai: {e}")
            messagebox.showerror("Nhập sai", str(e))
            return False

        self._divider()
        if cfg["start_date"].date() == cfg["end_date"].date():
            self._log("ACT", f"Bắt đầu: ngày {cfg['start_date']:%Y-%m-%d} (00h–23h)")
        else:
            days = (cfg["end_date"].date() - cfg["start_date"].date()).days + 1
            self._log("ACT", f"Bắt đầu: {cfg['start_date']:%Y-%m-%d} → "
                             f"{cfg['end_date']:%Y-%m-%d} ({days} ngày)")
        self.last_cfg = cfg
        self._set_actions_enabled(False)
        self.status.config(text="Đang chạy...")

        self.worker = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker.start()
        return True

    def _work(self, cfg):
        """Worker thread — only pushes events onto the queue, never touches widgets."""
        q = self.q
        def log(level, msg): q.put(("log", level, msg))
        def progress(done, total, status): q.put(("progress", done, total))
        try:
            result = csv_pipeline.run_pipeline(cfg, log=log, progress=progress)
            q.put(("done", result))
        except Exception as e:
            q.put(("error", f"{type(e).__name__}: {e}"))

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1], item[2])
                elif kind == "progress":
                    _, done, total = item
                    self.status.config(text=f"Tải {done}/{total}")
                elif kind == "done":
                    self._on_done(item[1])
                elif kind == "error":
                    self._log("ERR", item[1])
                    self.status.config(text="Lỗi")
                    self._set_actions_enabled(True)
                    messagebox.showerror("Lỗi", item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_done(self, result: dict):
        self._set_actions_enabled(True)
        self.last_output_dir = result.get("output_dir")

        self.last_result = result
        self.last_updated_at = datetime.datetime.now()
        self._refresh_info_panel()

        if not result.get("ok"):
            self.status.config(text="Không có dữ liệu")
            miss = result.get("missing") or []
            if miss:
                self._log("WARN", f"Thiếu {len(miss)} file trên server")
            return

        self.status.config(text="Hoàn tất")
        history_files = result.get("history_files") or {}
        parts = [f"{os.path.basename(info['csv'])} ({info['records']} record)"
                 for _, info in sorted(history_files.items())]
        self._log("OK", "Hoàn tất — đã xuất: " + (", ".join(parts) if parts else "(không có)"))


def main():
    # Allows: python gui.py [config_ini_path]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    App(root, config_path=config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
