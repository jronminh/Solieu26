"""
dialogs.py
====================
The two small Toplevel dialogs hung off the main window: "Thiết lập" (settings)
and "Tải số liệu" (advanced date-range query).

Both are standalone classes (not mixins) — each takes the App instance in its
constructor and reaches back into it (`self.app....`) for shared state (the
form variables in app.v, the log/dialog-registry helpers, the auto-query
timer). gui.py creates ONE instance of each per App and keeps it around, so
e.g. AdvancedDialog's own widget refs survive across "Tải số liệu" opens/closes.
"""

import datetime
import os

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import config
from gui_common import open_folder, report_open


class SettingsDialog:
    def __init__(self, app):
        self.app = app

    def _row(self, parent, r, label, var, width=None, show=None):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        e = ttk.Entry(parent, textvariable=var, show=show)
        if width:
            e.config(width=width)
            e.grid(row=r, column=1, sticky="w", padx=6, pady=3)
        else:
            e.grid(row=r, column=1, sticky="ew", padx=6, pady=3)
        return e

    def open(self):
        """Combined settings dialog: Kết nối / Đường dẫn / Tự động truy vấn, plus
        config.ini actions (restore-defaults at bottom-left, explicit save at bottom-right)."""
        app = self.app
        app._log("ACT", "Mở hộp thoại Thiết lập")
        win = app._make_dialog("settings", "Thiết lập")
        if win is None:
            return
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        conn_box = ttk.LabelFrame(frm, text="Kết nối", padding=8)
        conn_box.pack(fill="x")
        self._row(conn_box, 0, "Host",     app.v["ftp_host"])
        self._row(conn_box, 1, "User",     app.v["ftp_user"])
        self._row(conn_box, 2, "Password", app.v["ftp_pass"], show="*")
        conn_box.columnconfigure(1, weight=1)

        path_box = ttk.LabelFrame(frm, text="Đường dẫn", padding=8)
        path_box.pack(fill="x", pady=(8, 0))
        self._row(path_box, 0, "Thư mục server",  app.v["remote_dir"])
        self._row(path_box, 1, "Thư mục xuất CSV", app.v["output_dir"])
        ttk.Button(path_box, text="Chọn...",
                   command=lambda: self._browse_output(parent=win)).grid(row=1, column=2, padx=4)
        ttk.Button(path_box, text="Mở thư mục data",
                   command=self._on_open_data).grid(
                   row=2, column=0, sticky="w", pady=(6, 0))

        path_box.columnconfigure(1, weight=1)

        # Auto-query: re-runs the pipeline on a timer (system time → "Về hiện tại" →
        # "Làm mới"). 0 = tắt tự động truy vấn.
        auto_box = ttk.LabelFrame(frm, text="Tự động truy vấn", padding=8)
        auto_box.pack(fill="x", pady=(8, 0))
        auto_entry = ttk.Entry(auto_box, textvariable=app.v["auto_value"], width=6)
        auto_entry.grid(row=0, column=0, padx=(0, 4))
        auto_entry.bind("<FocusOut>", app._on_auto_change)
        auto_entry.bind("<Return>", app._on_auto_change)
        auto_unit = ttk.Combobox(auto_box, textvariable=app.v["auto_unit"],
                                 values=["Phút", "Giờ"], state="readonly", width=8)
        auto_unit.grid(row=0, column=1)
        auto_unit.bind("<<ComboboxSelected>>", app._on_auto_change)
        ttk.Label(auto_box, text="(0 = tắt)").grid(row=0, column=2, padx=(8, 0))
        ttk.Checkbutton(auto_box, text="Tự động truy vấn khi khởi động",
                        variable=app.v["auto_on_startup"]).grid(
                        row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        btn_bar = ttk.Frame(frm)
        btn_bar.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_bar, text="Khôi phục mặc định",
                   command=self._on_restore_defaults).pack(side="left")
        ttk.Button(btn_bar, text="Lưu thiết lập",
                   command=self._on_save_settings).pack(side="right")

        win.minsize(420, 0)
        app._center_over_root(win)

    def _on_save_settings(self):
        """Persist every field in the Thiết lập dialog to config.ini in one shot."""
        app = self.app
        app._log("ACT", "Lưu thiết lập")
        v = app._auto_effective_value()
        app.v["auto_value"].set(str(v))
        unit_key = "hours" if app.v["auto_unit"].get() == "Giờ" else "minutes"
        values = {
            "ftp_host":           app.v["ftp_host"].get().strip(),
            "ftp_user":           app.v["ftp_user"].get().strip(),
            "ftp_pass":           app.v["ftp_pass"].get(),
            "remote_dir":         app.v["remote_dir"].get().strip(),
            "output_dir":         app.v["output_dir"].get().strip(),
            "auto_query_value":   str(v),
            "auto_query_unit":    unit_key,
            "auto_query_on_startup": "true" if app.v["auto_on_startup"].get() else "false",
        }
        try:
            for key, value in values.items():
                config.update_ini_key(app.cfg_path, config.CONFIG_SECTION, key, value)
            config.CONFIG.update({
                "ftp_host": values["ftp_host"], "ftp_user": values["ftp_user"],
                "ftp_pass": values["ftp_pass"], "remote_dir": values["remote_dir"],
                "output_dir": values["output_dir"],
                "auto_query_value": v, "auto_query_unit": unit_key,
                "auto_query_on_startup": app.v["auto_on_startup"].get(),
            })
            app._log("OK", f"Đã lưu thiết lập vào config: {app.cfg_path}")
        except OSError as e:
            app._log("ERR", f"Không lưu được thiết lập: {e}")
            messagebox.showerror("Lỗi", f"Không lưu được thiết lập:\n{e}")
        app._schedule_auto_tick()

    def _on_restore_defaults(self):
        """Overwrite config.ini with the hardcoded defaults (config.DEFAULT_CONFIG)
        and reflect them back into the open Thiết lập dialog."""
        app = self.app
        app._log("ACT", "Khôi phục thiết lập mặc định")
        if not messagebox.askyesno(
                "Khôi phục mặc định",
                "Toàn bộ thiết lập hiện tại sẽ bị ghi đè bằng mặc định trong "
                "mã nguồn. Bạn có chắc muốn tiếp tục?"):
            app._log("INFO", "Đã hủy khôi phục mặc định")
            return
        try:
            path = config.write_default_config(app.cfg_path)
        except OSError as e:
            app._log("ERR", f"Không khôi phục được mặc định: {e}")
            messagebox.showerror("Lỗi", f"Không khôi phục được mặc định:\n{e}")
            return

        d = config.DEFAULT_CONFIG
        config.CONFIG.update(d)
        app.v["ftp_host"].set(d["ftp_host"])
        app.v["ftp_user"].set(d["ftp_user"])
        app.v["ftp_pass"].set(d["ftp_pass"])
        app.v["remote_dir"].set(d["remote_dir"])
        app.v["output_dir"].set(d["output_dir"])
        app.v["auto_value"].set(str(d["auto_query_value"]))
        app.v["auto_unit"].set("Giờ" if d["auto_query_unit"] == "hours" else "Phút")
        app.v["auto_on_startup"].set(bool(d["auto_query_on_startup"]))
        app._schedule_auto_tick()
        app._log("OK", f"Đã khôi phục thiết lập mặc định vào config: {path}")

    def _browse_output(self, parent=None):
        app = self.app
        app._log("ACT", "Chọn thư mục xuất CSV")
        p = filedialog.askdirectory(title="Chọn thư mục xuất CSV",
                                    parent=parent or app.root)
        if p:
            app.v["output_dir"].set(p)
            app._log("OK", f"Thư mục xuất CSV: {p}")
        else:
            app._log("INFO", "Đã hủy chọn thư mục xuất")

    def _on_open_data(self):
        app = self.app
        app._log("ACT", "Mở thư mục data")
        os.makedirs(config.TEMP_DL_DIR, exist_ok=True)   # create it upfront if never run before
        report_open(app._log, *open_folder(config.TEMP_DL_DIR), "thư mục data")


class AdvancedDialog:
    """'Tải số liệu' button (next to 'Xem số liệu'): a date-range query UI
    (Ngày bắt đầu/kết thúc + Bắt đầu/Về hiện tại). Opening it turns advanced
    (date-range) mode on and pauses auto-query; closing it (nút X) turns
    advanced mode back off and resumes auto-query."""

    def __init__(self, app):
        self.app = app
        # None until first opened (see open()); every accessor guards for that
        # with winfo_exists().
        self.start_date_entry = None
        self.end_date_entry = None
        self.now_btn = None
        self.start_btn = None

    def open(self):
        app = self.app
        win = app._make_dialog("advanced", "Tải số liệu")
        if win is None:
            return
        app._log("ACT", "Mở hộp thoại Tải số liệu — tạm dừng tự động truy vấn")

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        date_box = ttk.Frame(frm)
        date_box.pack(fill="x")

        ttk.Label(date_box, text="Ngày bắt đầu:").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.start_date_entry = ttk.Entry(date_box, textvariable=app.v["start_date"], width=12)
        self.start_date_entry.grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(date_box, text="Ngày kết thúc:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.end_date_entry = ttk.Entry(date_box, textvariable=app.v["end_date"], width=12)
        self.end_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=2)

        # "Bắt đầu" chạy truy vấn tải số liệu rồi đóng luôn dialog này; "Về hiện
        # tại" nằm cạnh.
        btn_row = ttk.Frame(frm)
        self.start_btn = ttk.Button(btn_row, text="Bắt đầu", command=self._on_advanced_start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.now_btn = ttk.Button(btn_row, text="Về hiện tại", command=self._on_now)
        self.now_btn.pack(side="left")
        btn_row.pack(pady=(8, 0))

        win.protocol("WM_DELETE_WINDOW", self._on_close)

        app.v["advanced_mode"].set(True)
        self._on_mode_changed()
        win.minsize(260, 0)
        app._center_over_root(win)

    def _on_now(self):
        """'Về hiện tại': force start_date/end_date to today."""
        app = self.app
        now = datetime.datetime.now()
        app.v["start_date"].set(now.strftime("%Y-%m-%d"))
        app.v["end_date"].set(now.strftime("%Y-%m-%d"))
        app._log("ACT", f"Về hiện tại: ngày {now:%Y-%m-%d}")

    def _on_mode_changed(self):
        """Pauses/resumes auto-query to match app.v["advanced_mode"] (mutually
        exclusive — a background auto tick shouldn't re-fire a date-range fetch
        the user is busy configuring), then refreshes the date-range controls
        and info panel. advanced_mode simply tracks whether this dialog is open."""
        app = self.app
        if app.v["advanced_mode"].get():
            if app.auto_job is not None:
                app.root.after_cancel(app.auto_job)
                app.auto_job = None
            app.auto_next_run = None
        else:
            app._schedule_auto_tick()   # resume per the settings already in config/mã nguồn
        self.refresh_controls_state()
        app._refresh_info_panel()

    def refresh_controls_state(self):
        """'Bắt đầu' bị khóa khi đang có tác vụ chạy; ngày bắt đầu/kết thúc +
        'Về hiện tại' luôn bật vì dialog 'Tải số liệu' chỉ tồn tại khi đang ở chế
        độ tải số liệu. No-op nếu dialog chưa từng mở (hoặc đã bị đóng) — các
        widget bên dưới chỉ tồn tại từ lúc open() dựng chúng."""
        if self.start_date_entry is None or not self.start_date_entry.winfo_exists():
            return
        self.start_date_entry.config(state="normal")
        self.end_date_entry.config(state="normal")
        self.now_btn.config(state="normal")
        self.start_btn.config(state="disabled" if self.app._run_in_progress else "normal")

    def _on_close(self):
        """WM_DELETE_WINDOW cho dialog 'Tải số liệu': đóng cửa sổ rồi tắt chế độ
        tải số liệu (date-range) và tiếp tục tự động truy vấn."""
        app = self.app
        app._dialogs["advanced"].destroy()
        app.v["advanced_mode"].set(False)
        self._on_mode_changed()
        app._log("ACT", "Đóng hộp thoại Tải số liệu — tiếp tục tự động truy vấn")

    def _on_advanced_start(self):
        """'Bắt đầu': chạy truy vấn theo khoảng ngày đã nhập, rồi đóng dialog —
        NHƯNG chỉ khi truy vấn thực sự bắt đầu được. app._on_run() build cfg từ
        start_date/end_date trước khi dialog đóng, nên khoảng ngày vẫn đúng
        (đóng trước sẽ tắt advanced_mode → cfg rơi về "hôm nay"). Nếu ngày nhập
        sai hoặc đang có tác vụ chạy, app._on_run() trả về False và dialog vẫn
        mở để người dùng sửa."""
        if self.app._on_run():
            self._on_close()
