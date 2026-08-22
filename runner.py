"""
runner.py
====================
Drives one pipeline run: builds cfg from the form, starts the worker thread
(pipeline.fetch -> pipeline.decode_files), and polls its queue.Queue() back into the UI.

Reaches into the App instance (see main.py) for the form variables in app.v,
the log helper, and the "Bắt đầu" button in the "Tải số liệu theo khoảng" tab;
main.py starts its poll loop from App.__init__.

Anti-freeze contract: _work() runs on a worker thread and never touches
widgets, it only pushes events onto self.q; the main thread's _poll() reads
them back via root.after() and applies UI updates itself. It is the ONLY
place that ties the 2 independent pipeline modules together:
pipeline/fetch.py (FTP download) and pipeline/decode_files.py (decode + CSV export)
don't import each other and neither knows about the other; a decode failure
can't take down a download already in progress. It runs them as 2 stages and
reports them as 2 separate outcomes: 'fetch_done' (always, once download
finishes) then either 'export_done' or 'export_error' (only if there were
files to process), on top of the always-available 'log' / 'progress' /
'error' (connect/login failure) events.
"""

import datetime
import os
import queue
import threading

from tkinter import messagebox

from utils import config_utils as config
from utils import log_utils
from utils.ini_utils import update_ini_key
from pipeline import fetch as pipeline_fetch

CATCHUP_MARK_FMT = "%Y-%m-%d %H:%M:%S"
_logger = log_utils.get_logger("runner")


class Runner:
    def __init__(self, app):
        self.app = app
        self.q = queue.Queue()
        self.worker = None
        self._run_in_progress = False  # mirrors _set_actions_enabled, feeds refresh_range_panel_state + auto_query pause/resume
        self._on_run_done = None    # one-shot callback fired next time a run finishes (see _run_catchup_then_normal)
        self.last_output_dir = None
        self.last_result = None     # result dict from the last completed run (for the info panel)
        self.last_cfg = None        # cfg dict from the last run started (carries the queried date)
        self.last_updated_at = None # datetime the last run finished (success or not)

    # ----- Run pipeline ("Làm mới" / "Bắt đầu") ----------------------------
    def _parallel_workers(self) -> int:
        """Form value, parsed; garbage/blank/<1 falls back to 1 (tuần tự)."""
        try:
            n = int(self.app.v["parallel_workers"].get().strip())
        except ValueError:
            n = 1
        return max(n, 1)

    def _build_cfg_base(self) -> dict:
        """Cfg fields that don't depend on a date range: FTP/paths/retry, read
        from the form. Shared by _build_cfg() (UI date range) and the catch-up
        path (its own computed range, bypassing the UI's start/end fields)."""
        app = self.app
        return {
            "ftp_host": app.v["ftp_host"].get().strip(),
            "ftp_user": app.v["ftp_user"].get().strip(),
            "ftp_pass": app.v["ftp_pass"].get(),
            "ftp_timeout": config.CONFIG.get("ftp_timeout", config.FTP_TIMEOUT),
            "retry_temp": config.CONFIG.get("retry_temp", config.RETRY_TEMP),
            "retry_wait": config.CONFIG.get("retry_wait", config.RETRY_WAIT),
            "stability_check": config.CONFIG.get("stability_check", config.STABILITY_CHECK),
            "stability_wait": config.CONFIG.get("stability_wait", config.STABILITY_WAIT),
            "parallel_workers": self._parallel_workers(),
            "remote_dir": app.v["remote_dir"].get().strip() or "/Quantrac",
            "local_dir":  config.TEMP_DL_DIR,
            "output_dir": app.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR,
        }

    def _build_cfg(self) -> dict:
        """Read the form → cfg dict; local_dir/timeout/retry come from config's fixed constants.

        start_date/end_date always come from the "Tải số liệu theo khoảng" panel
        (app.v["start_date"]/["end_date"], defaults to today) — pipeline_fetch.download_files()
        takes the fast single-day path when they're equal, so a plain "hôm nay" query
        and a date-range query both go through this same one path.
        """
        app = self.app
        cfg = self._build_cfg_base()

        try:
            start = datetime.datetime.strptime(app.v["start_date"].get().strip(), "%Y-%m-%d")
            end = datetime.datetime.strptime(app.v["end_date"].get().strip(), "%Y-%m-%d")
        except ValueError:
            raise ValueError("Ngày bắt đầu/kết thúc phải theo định dạng YYYY-MM-DD, vd 2026-08-10")
        if end < start:
            raise ValueError("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu")
        cfg["start_date"] = start
        cfg["end_date"] = end

        return cfg

    def _start_worker(self, cfg: dict) -> bool:
        """Start the worker thread for an already-built cfg (start_date/end_date
        included). Shared by _on_run() (UI-driven cfg) and the catch-up path
        (explicit computed range). Returns True iff actually started."""
        if self.worker and self.worker.is_alive():
            return False
        app = self.app
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
        app._reset_download_queue(cfg["start_date"], cfg["end_date"])

        self.worker = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker.start()
        return True

    # ----- Mốc catch-up sau downtime ---------------------------------------
    def _pending_catchup_range(self, now: datetime.datetime):
        """(start, end) to backfill since the last contiguous mark, or None if
        there's no mark yet or the gap is under 1 giờ (not worth a separate run)."""
        raw = config.CONFIG.get("catchup_mark")
        if not raw:
            return None
        try:
            mark = datetime.datetime.strptime(raw, CATCHUP_MARK_FMT)
        except ValueError:
            return None
        start = mark + datetime.timedelta(hours=1)
        if now - start < datetime.timedelta(hours=1):
            return None
        return start, now

    def _run_catchup_then_normal(self):
        """Entry point for auto-triggered runs (startup + auto-query tick):
        backfill any gap since the last contiguous mark first, then run the
        normal 'hiện tại' pipeline once that finishes. Manual 'Bắt đầu' in the
        "Tải số liệu theo khoảng" tab still calls _on_run() directly and reads
        its own date-range fields — unaffected by this."""
        app = self.app
        catchup_range = self._pending_catchup_range(datetime.datetime.now())
        if catchup_range is None:
            self._on_run()
            return
        start, end = catchup_range
        try:
            cfg = self._build_cfg_base()
            if not cfg["ftp_host"]:
                raise ValueError("Chưa nhập FTP host")
        except ValueError as e:
            app._log("ERR", f"Nhập sai (bù mốc liền mạch): {e}")
            self._on_run()
            return
        cfg["start_date"] = start
        cfg["end_date"] = end
        app._log("ACT", f"Bù khoảng thiếu {start:%Y-%m-%d %H:%M} → "
                         f"{end:%Y-%m-%d %H:%M} (mốc liền mạch)")
        self._on_run_done = self._on_run
        if not self._start_worker(cfg):
            self._on_run_done = None
            self._on_run()

    def _contiguous_advance(self, start: datetime.datetime, end: datetime.datetime,
                             missing_filenames) -> datetime.datetime:
        """Latest hour, walking forward from `start`, such that every hour up to
        and including it is NOT in `missing_filenames` — the new mark candidate.
        Returns start - 1h (i.e. "nothing confirmed") if even the first hour is missing."""
        missing = set(missing_filenames)
        mark = start - datetime.timedelta(hours=1)
        for ts in pipeline_fetch.expected_hours(start, end):
            if pipeline_fetch.quantrac_filename_at(ts) in missing:
                break
            mark = ts
        return mark

    def _advance_catchup_mark(self, start: datetime.datetime, end: datetime.datetime,
                               missing_filenames):
        """Persist the new contiguous mark if this cycle's result confirms a
        later hour than what's already stored. Called from every _on_fetch_done,
        regardless of what triggered the run (manual/auto/catch-up)."""
        candidate = self._contiguous_advance(start, end, missing_filenames)
        if candidate < start:
            return   # first hour of this cycle was itself missing, nothing new confirmed

        raw = config.CONFIG.get("catchup_mark")
        if raw:
            try:
                current = datetime.datetime.strptime(raw, CATCHUP_MARK_FMT)
            except ValueError:
                current = None
        else:
            current = None
        if current is not None and candidate <= current:
            return

        mark_str = candidate.strftime(CATCHUP_MARK_FMT)
        config.CONFIG["catchup_mark"] = mark_str
        update_ini_key(self.app.cfg_path, config.CONFIG_SECTION, "catchup_mark", mark_str)

    def _set_actions_enabled(self, enabled: bool):
        """Toggle 'Bắt đầu' (tab 'Tải số liệu theo khoảng' trong main.py): khóa
        khi có tác vụ đang chạy. Cũng tạm dừng/tiếp tục tự động truy vấn ngay tại
        đây - auto-query giờ gắn với "có đang chạy 1 lượt tải hay không"."""
        app = self.app
        self._run_in_progress = not enabled
        if enabled:
            app.auto_query.resume()
        else:
            app.auto_query.pause()
        app.refresh_range_panel_state()
        if enabled and self._on_run_done is not None:
            callback = self._on_run_done
            self._on_run_done = None
            callback()

    def _on_run(self) -> bool:
        """Returns True iff a worker thread was actually started, False if
        skipped (a run is already in progress) or rejected (bad input)."""
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
        return self._start_worker(cfg)

    def _work(self, cfg):
        """
        Worker thread: only pushes events onto the queue, never touches widgets.

        pipeline.decode_files được import TRỄ, ngay ở đây (không phải ở đầu file).
        Một lỗi decode (import lỗi hay exception lúc chạy) chỉ làm hỏng giai
        đoạn export, không đụng tới giai đoạn fetch đã báo xong lẫn việc
        main.py tự khởi động (xem module docstring: fetch/decode không import
        lẫn nhau).
        """
        q = self.q
        def log(level, msg): q.put(("log", level, msg))
        def progress(done, total, status, filename): q.put(("progress", done, total, status, filename))

        try:
            dl = pipeline_fetch.fetch_files(cfg, log=log, progress=progress)
        except Exception as e:
            _logger.exception("fetch_files thất bại")
            q.put(("error", f"{type(e).__name__}: {e}"))
            return

        q.put(("fetch_done", dl))
        if not dl["files"]:
            return

        try:
            from pipeline import decode_files as pipeline_decode
            output_dir = os.path.abspath(cfg.get("output_dir") or config.DEFAULT_OUTPUT_DIR)
            os.makedirs(output_dir, exist_ok=True)
            history_files = pipeline_decode.export_history_by_date(sorted(dl["files"]), output_dir)
            q.put(("export_done", {"output_dir": output_dir, "history_files": history_files}))
        except Exception as e:
            _logger.exception("export_history_by_date thất bại")
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
                    _, done, total, status, filename = item
                    app._set_download_progress(done, total, status, filename)
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
        """Giai đoạn 1 (fetch) xong: LUÔN cập nhật files/missing bất kể giai
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

        if self.last_cfg is not None:
            self._advance_catchup_mark(self.last_cfg["start_date"], self.last_cfg["end_date"], miss)

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
        app._log("OK", "Hoàn tất, đã xuất: " + (", ".join(parts) if parts else "(không có)"))
        app.history_viewer.refresh_date_list()

    def _on_export_error(self, msg: str):
        """Khối 1 đã xong (self.last_result đã có files/missing từ _on_fetch_done),
        lỗi ở đây chỉ là khối 2 (xử lý readable), không xoá kết quả tải đã có."""
        app = self.app
        self._set_actions_enabled(True)
        app._log("ERR", f"Xử lý số liệu thất bại (đã tải xong file, chỉ bước xử lý lỗi): {msg}")
        app.status.config(text="Tải xong, xử lý lỗi")
        messagebox.showerror("Lỗi xử lý", msg)
