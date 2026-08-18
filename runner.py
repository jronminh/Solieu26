"""
runner.py
====================
Drives one pipeline run: builds cfg from the form, starts the worker thread
(pipeline_fetch -> pipeline_csv), and polls its queue.Queue() back into the UI.

Runner is a standalone class (not a mixin) — like SettingsDialog/AdvancedDialog
in dialogs.py, it takes the App instance in its constructor and reaches back
into it (self.app...) for shared state (the form variables in app.v, the log
helper, the "Làm mới" button). gui.py creates ONE instance per App, kept for
the app's lifetime, and starts its poll loop from App.__init__.

Anti-freeze contract: _work() runs on a worker thread and never touches
widgets — it only pushes events onto self.q; the main thread's _poll() reads
them back via root.after() and applies UI updates itself. It is the ONLY
place that ties the 2 independent pipeline modules together —
pipeline_fetch.py (FTP download) and pipeline_csv.py (decode + CSV export)
don't import each other and neither knows about the other; a decode failure
can't take down a download already in progress. It runs them as 2 stages and
reports them as 2 separate outcomes: 'fetch_done' (always, once download
finishes) then either 'export_done' or 'export_error' (only if there were
files to process) — on top of the always-available 'log' / 'progress' /
'error' (connect/login failure) events.
"""

import datetime
import os
import queue
import threading

from tkinter import messagebox

from utils import config_utils as config
import pipeline_fetch


class Runner:
    def __init__(self, app):
        self.app = app
        self.q = queue.Queue()
        self.worker = None
        self._run_in_progress = False  # mirrors _set_actions_enabled — feeds advanced_dialog.refresh_controls_state
        self.last_output_dir = None
        self.last_result = None     # result dict from the last completed run (for the info panel)
        self.last_cfg = None        # cfg dict from the last _on_run (carries the queried date)
        self.last_updated_at = None # datetime the last run finished (success or not)

    # ----- Run pipeline ("Làm mới" / "Bắt đầu") ----------------------------
    def _build_cfg(self) -> dict:
        """Read the form → cfg dict; local_dir/timeout/retry come from config's fixed constants.

        Always sets start_date/end_date — pipeline_fetch.download_files() takes the fast
        single-day path when they're equal. Normal mode: always "today", no date
        field to read. Advanced mode (self.app.v["advanced_mode"], on while the "Tải
        số liệu" dialog is open): reads them from that dialog's fields instead.
        """
        app = self.app
        cfg = {
            "ftp_host": app.v["ftp_host"].get().strip(),
            "ftp_user": app.v["ftp_user"].get().strip(),
            "ftp_pass": app.v["ftp_pass"].get(),
            "ftp_timeout": config.CONFIG.get("ftp_timeout", config.FTP_TIMEOUT),
            "retry_temp": config.CONFIG.get("retry_temp", config.RETRY_TEMP),
            "retry_wait": config.CONFIG.get("retry_wait", config.RETRY_WAIT),
            "remote_dir": app.v["remote_dir"].get().strip() or "/Quantrac",
            "local_dir":  config.TEMP_DL_DIR,
            "output_dir": app.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR,
        }

        if app.v["advanced_mode"].get():
            try:
                start = datetime.datetime.strptime(app.v["start_date"].get().strip(), "%Y-%m-%d")
                end = datetime.datetime.strptime(app.v["end_date"].get().strip(), "%Y-%m-%d")
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
        app = self.app
        self._run_in_progress = not enabled
        app.refresh_btn.config(state="normal" if enabled else "disabled")
        app.advanced_dialog.refresh_controls_state()

    def _on_run(self) -> bool:
        """Returns True iff a worker thread was actually started — False if
        skipped (a run is already in progress) or rejected (bad input). Callers
        that need to know whether the query truly started (e.g.
        AdvancedDialog._on_advanced_start, to decide whether to close the 'Tải
        số liệu' dialog) check this."""
        app = self.app
        if self.worker and self.worker.is_alive():
            app._log("WARN", "Bỏ qua: một tác vụ đang chạy")
            return False
        try:
            cfg = self._build_cfg()
            if not cfg["ftp_host"]:
                raise ValueError("Chưa nhập FTP host")
        except ValueError as e:
            app._log("ERR", f"Nhập sai: {e}")
            messagebox.showerror("Nhập sai", str(e))
            return False

        app._divider()
        if cfg["start_date"].date() == cfg["end_date"].date():
            app._log("ACT", f"Bắt đầu: ngày {cfg['start_date']:%Y-%m-%d} (00h–23h)")
        else:
            days = (cfg["end_date"].date() - cfg["start_date"].date()).days + 1
            app._log("ACT", f"Bắt đầu: {cfg['start_date']:%Y-%m-%d} → "
                             f"{cfg['end_date']:%Y-%m-%d} ({days} ngày)")
        self.last_cfg = cfg
        self._set_actions_enabled(False)
        app.status.config(text="Đang chạy...")

        self.worker = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker.start()
        return True

    def _work(self, cfg):
        """
        Worker thread — only pushes events onto the queue, never touches widgets.

        2 giai đoạn ĐỘC LẬP, khớp với việc pipeline_fetch.py và pipeline_csv.py
        không import lẫn nhau: fetch (luôn chạy, không phụ thuộc gì ở khối 2)
        rồi export (chỉ cần biết khối 1 có để lại file hay không, không quan
        tâm khối 1 "thành công" theo nghĩa nào khác). pipeline_csv được import
        TRỄ, ngay ở đây — một lỗi decode (import lỗi hay exception lúc chạy)
        chỉ làm hỏng giai đoạn export, không đụng tới giai đoạn fetch đã báo
        xong lẫn việc gui.py tự khởi động.
        """
        q = self.q
        def log(level, msg): q.put(("log", level, msg))
        def progress(done, total, status): q.put(("progress", done, total))

        try:
            dl = pipeline_fetch.fetch_files(cfg, log=log, progress=progress)
        except Exception as e:
            q.put(("error", f"{type(e).__name__}: {e}"))
            return

        q.put(("fetch_done", dl))
        if not dl["files"]:
            return

        try:
            import pipeline_csv
            output_dir = os.path.abspath(cfg.get("output_dir") or config.DEFAULT_OUTPUT_DIR)
            os.makedirs(output_dir, exist_ok=True)
            history_files = pipeline_csv.export_history_by_date(sorted(dl["files"]), output_dir)
            q.put(("export_done", {"output_dir": output_dir, "history_files": history_files}))
        except Exception as e:
            q.put(("export_error", f"{type(e).__name__}: {e}"))

    def _poll(self):
        app = self.app
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    app._log(item[1], item[2])
                elif kind == "progress":
                    _, done, total = item
                    app.status.config(text=f"Tải {done}/{total}")
                elif kind == "fetch_done":
                    self._on_fetch_done(item[1])
                elif kind == "export_done":
                    self._on_export_done(item[1])
                elif kind == "export_error":
                    self._on_export_error(item[1])
                elif kind == "error":
                    app._log("ERR", item[1])
                    app.status.config(text="Lỗi")
                    self._set_actions_enabled(True)
                    messagebox.showerror("Lỗi", item[1])
        except queue.Empty:
            pass
        app.root.after(100, self._poll)

    def _on_fetch_done(self, dl: dict):
        """Giai đoạn 1 (fetch) xong — LUÔN cập nhật files/missing bất kể giai
        đoạn 2 sau đó thế nào. Giữ đúng hình dạng dict cũ (ok/history_files/
        history_records) để _refresh_info_panel() không phải sửa; _on_export_done()/
        _on_export_error() sẽ cập nhật tiếp lên self.last_result này."""
        app = self.app
        self.last_result = {"ok": False, "files": dl["files"], "missing": dl["missing"],
                             "history_files": {}, "history_records": 0}
        self.last_updated_at = datetime.datetime.now()
        app._refresh_info_panel()

        miss = dl.get("missing") or []
        if miss:
            app._log("WARN", f"Thiếu {len(miss)} file trên server")

        if not dl["files"]:
            self._set_actions_enabled(True)
            app.status.config(text="Không có dữ liệu")

    def _on_export_done(self, info: dict):
        app = self.app
        self._set_actions_enabled(True)
        self.last_output_dir = info["output_dir"]

        history_files = info["history_files"]
        self.last_result.update(
            ok=True, output_dir=info["output_dir"], history_files=history_files,
            history_records=sum(v["records"] for v in history_files.values()))
        self.last_updated_at = datetime.datetime.now()
        app._refresh_info_panel()

        app.status.config(text="Hoàn tất")
        parts = [f"{os.path.basename(hinfo['csv'])} ({hinfo['records']} record)"
                 for _, hinfo in sorted(history_files.items())]
        app._log("OK", "Hoàn tất — đã xuất: " + (", ".join(parts) if parts else "(không có)"))

    def _on_export_error(self, msg: str):
        """Khối 1 đã xong (self.last_result đã có files/missing từ _on_fetch_done)
        — lỗi ở đây chỉ là khối 2 (xử lý readable), không xoá kết quả tải đã có."""
        app = self.app
        self._set_actions_enabled(True)
        app._log("ERR", f"Xử lý số liệu thất bại (đã tải xong file, chỉ bước xử lý lỗi): {msg}")
        app.status.config(text="Tải xong, xử lý lỗi")
        messagebox.showerror("Lỗi xử lý", msg)
