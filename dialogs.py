"""
dialogs.py
====================
The "Thiết lập" (settings) Toplevel dialog hung off the main window. The
date-range query ("Tải số liệu theo khoảng") used to be a separate dialog here
too; it's now a panel embedded directly in main.py's main window instead.

Reaches into the App instance (see main.py) for app.v, the
log/dialog-registry helpers, and the auto-query timer.
"""

import datetime
import os

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from utils import config_utils as config
from common import report_open, make_dialog, center_over_root
from utils.file_utils import open_folder
from utils.ini_utils import update_ini_key


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        # Rebuilt fresh each open() call (make_dialog only calls open() when no
        # Toplevel is currently up), so no stale-widget risk keeping refs here.
        self._dirty_var = None
        self._dirty_label = None
        self._toast_label = None

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
        win = make_dialog(app.root, app._dialogs, "settings", "Thiết lập")
        if win is None:
            return
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        # Every field below shares 1 "Lưu thiết lập" button (no more auto-apply
        # on FocusOut/Enter for the auto-query fields specifically) - typing
        # anywhere just marks the dirty indicator, config.ini and the running
        # auto-query schedule only change once "Lưu thiết lập" is clicked.
        conn_box = ttk.LabelFrame(frm, text="Kết nối", padding=8)
        conn_box.pack(fill="x")
        host_entry = self._row(conn_box, 0, "Host",     app.v["ftp_host"])
        user_entry = self._row(conn_box, 1, "User",     app.v["ftp_user"])
        pass_entry = self._row(conn_box, 2, "Password", app.v["ftp_pass"], show="*")
        conn_box.columnconfigure(1, weight=1)

        path_box = ttk.LabelFrame(frm, text="Đường dẫn", padding=8)
        path_box.pack(fill="x", pady=(8, 0))
        remote_dir_entry = self._row(path_box, 0, "Thư mục server",  app.v["remote_dir"])
        output_dir_entry = self._row(path_box, 1, "Thư mục xuất CSV", app.v["output_dir"])
        ttk.Button(path_box, text="Chọn...",
                   command=lambda: self._browse_output(parent=win)).grid(row=1, column=2, padx=4)
        ttk.Button(path_box, text="Mở thư mục data",
                   command=self._on_open_data).grid(
                   row=2, column=0, sticky="w", pady=(6, 0))
        path_box.columnconfigure(1, weight=1)

        auto_box = ttk.LabelFrame(frm, text="Tự động truy vấn", padding=8)
        auto_box.pack(fill="x", pady=(8, 0))
        auto_entry = ttk.Entry(auto_box, textvariable=app.v["auto_value"], width=6)
        auto_entry.grid(row=0, column=0, padx=(0, 4))
        auto_unit = ttk.Combobox(auto_box, textvariable=app.v["auto_unit"],
                                 values=["Phút", "Giờ"], state="readonly", width=8)
        auto_unit.grid(row=0, column=1)
        ttk.Label(auto_box, text="(0 = tắt)").grid(row=0, column=2, padx=(8, 0))
        on_startup_chk = ttk.Checkbutton(auto_box, text="Tự động truy vấn khi khởi động",
                        variable=app.v["auto_on_startup"])
        on_startup_chk.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._dirty_label = ttk.Label(auto_box, text="", foreground="#b45309")
        self._dirty_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self._dirty_var = tk.BooleanVar(value=False)
        for entry in (host_entry, user_entry, pass_entry, remote_dir_entry,
                      output_dir_entry, auto_entry):
            entry.bind("<KeyRelease>", self._mark_dirty)
        auto_unit.bind("<<ComboboxSelected>>", self._mark_dirty)
        on_startup_chk.config(command=self._mark_dirty)

        self._toast_label = ttk.Label(frm, text="", foreground="#1d4ed8")
        self._toast_label.pack(fill="x", pady=(8, 0))

        btn_bar = ttk.Frame(frm)
        btn_bar.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_bar, text="Khôi phục mặc định",
                   command=self._on_restore_defaults).pack(side="left")
        ttk.Button(btn_bar, text="Lưu thiết lập",
                   command=self._on_save_settings).pack(side="right")

        win.minsize(420, 0)
        center_over_root(app.root, win)

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
                update_ini_key(app.cfg_path, config.CONFIG_SECTION, key, value)
            config.CONFIG.update({
                "ftp_host": values["ftp_host"], "ftp_user": values["ftp_user"],
                "ftp_pass": values["ftp_pass"], "remote_dir": values["remote_dir"],
                "output_dir": values["output_dir"],
                "auto_query_value": v, "auto_query_unit": unit_key,
                "auto_query_on_startup": app.v["auto_on_startup"].get(),
            })
            app._log("OK", f"Đã lưu thiết lập vào config: {app.cfg_path}")
            self._clear_dirty()
            self._show_saved_toast()
        except OSError as e:
            app._log("ERR", f"Không lưu được thiết lập: {e}")
            messagebox.showerror("Lỗi", f"Không lưu được thiết lập:\n{e}")
        app.auto_query._schedule_auto_tick()

    def _mark_dirty(self, event=None):
        """Any field changed since the dialog opened (or since the last save)."""
        if self._dirty_var is not None:
            self._dirty_var.set(True)
        if self._dirty_label is not None and self._dirty_label.winfo_exists():
            self._dirty_label.config(text="● Có thay đổi chưa lưu")
        if self._toast_label is not None and self._toast_label.winfo_exists():
            self._toast_label.config(text="")

    def _clear_dirty(self):
        if self._dirty_var is not None:
            self._dirty_var.set(False)
        if self._dirty_label is not None and self._dirty_label.winfo_exists():
            self._dirty_label.config(text="")

    def _show_saved_toast(self):
        """"Đã lưu thiết lập lúc HH:MM", auto-hides after a few seconds."""
        if self._toast_label is None or not self._toast_label.winfo_exists():
            return
        win = self._toast_label.winfo_toplevel()
        now = datetime.datetime.now().strftime("%H:%M")
        self._toast_label.config(text=f"Đã lưu thiết lập lúc {now}")
        win.after(3000, lambda: self._toast_label.config(text="")
                  if self._toast_label.winfo_exists() else None)

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
        app.auto_query._schedule_auto_tick()
        self._clear_dirty()
        app._log("OK", f"Đã khôi phục thiết lập mặc định vào config: {path}")

    def _browse_output(self, parent=None):
        app = self.app
        app._log("ACT", "Chọn thư mục xuất CSV")
        p = filedialog.askdirectory(title="Chọn thư mục xuất CSV",
                                    parent=parent or app.root)
        if p:
            app.v["output_dir"].set(p)
            self._mark_dirty()
            app._log("OK", f"Thư mục xuất CSV: {p}")
        else:
            app._log("INFO", "Đã hủy chọn thư mục xuất")

    def _on_open_data(self):
        app = self.app
        app._log("ACT", "Mở thư mục data")
        os.makedirs(config.TEMP_DL_DIR, exist_ok=True)   # create it upfront if never run before
        report_open(app._log, *open_folder(config.TEMP_DL_DIR), "thư mục data")
