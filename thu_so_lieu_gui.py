"""
thu_so_lieu_gui.py
===================
Tkinter GUI wrapping thu_so_lieu_core (imported as `core`).

Run:  python thu_so_lieu_gui.py [config.ini path]
Requires thu_so_lieu_core.py in the same folder.

Anti-freeze architecture: heavy work (FTP + decode + CSV export, all in core)
runs on a worker thread that never touches widgets — it only pushes ('log' /
'progress' / 'done' / 'error') events onto a queue.Queue(); the main thread
polls the queue every 100ms via root.after() and applies the UI updates itself.
"""

import csv
import datetime
import os
import queue
import subprocess
import sys
import threading

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import thu_so_lieu_core as core


# =============================================================================
# LOG COLORS (Tkinter Text tags — see core.py for the shared level format)
# =============================================================================

LOG_COLORS = {
    "INFO": "#374151",   # dark gray
    "OK":   "#15803d",   # green
    "SKIP": "#6b7280",   # gray
    "MISS": "#b45309",   # amber
    "WARN": "#b45309",   # amber
    "ERR":  "#b91c1c",   # red
    "ACT":  "#1d4ed8",   # blue
}


# =============================================================================
# STATION LIST (code → name)
# -----------------------------------------------------------------------------
# Feeds the station filter dropdown in the "Xem lịch sử" viewer (history.csv holds
# every station already — the dropdown just filters rows client-side, it no longer
# drives what gets downloaded/decoded). Add/remove a station by editing this table.
# =============================================================================
STATIONS = {
    "k31": "Yên Bái",    "k21": "Nội Bài",     "k27": "Kép",
    "k33": "Kiến An",    "k16": "Hòa Lạc",     "k18": "Gia Lâm",
    "k23": "Thọ Xuân",   "k05": "Vinh",        "k25": "Đà Nẵng",
    "k26": "Chu Lai",    "k66": "Plâycu",      "k40": "Phù Cát",
    "k30": "Tuy Hòa",    "k15": "Phan Thiết",  "k20": "Phan Rang",
    "k35": "Biên Hòa",   "k03": "T.S.Nhất",    "k36": "Cần Thơ",
    "k92": "Trường Sa",  "k93": "Thuyền Chài",
}

# Names feed the dropdown — order KEPT the same as latest.csv (order of the table
# above); also builds the reverse lookup name → code.
STATION_NAMES = list(STATIONS.values())
NAME_TO_CODE  = {name: code for code, name in STATIONS.items()}

ALL_STATIONS = "Tất cả các trạm"   # station-filter dropdown option that disables filtering


# Numeric columns in the CSV viewer — right-aligned + compared as NUMBERS when
# sorting (instead of as strings). *_hshs columns are numeric too but their names
# aren't fixed (cloud_1_hshs, cloud_2_hshs...) so they're detected by suffix instead
# of being listed here.
NUMERIC_VIEWER_COLUMNS = {
    "lat", "lon", "visibility_km", "total_cloud_N", "wind_dd_deg",
    "wind_ff", "temperature_c", "dewpoint_c", "pressure_hpa",
    "cloud_layers", "hour",
}


def open_folder(path: str):
    """Open a folder with the OS's file manager. Returns (ok: bool, reason/path)."""
    if not path:
        return False, "chưa có thư mục xuất (cần chạy thành công ít nhất một lần)"
    path = os.path.abspath(path)                      # './x' → absolute (Windows dislikes relative paths)
    if not os.path.isdir(path):
        return False, f"thư mục không tồn tại: {path}"
    try:
        if os.name == "nt":
            os.startfile(path)                       # Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])         # macOS
        else:
            subprocess.Popen(["xdg-open", path])     # Linux
        return True, path
    except Exception as e:
        return False, str(e)


def open_in_editor(path: str):
    """Open a FILE with its default application (for editing). Returns (ok, reason/path)."""
    if not path:
        return False, "chưa có đường dẫn file"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, f"file không tồn tại: {path}"
    try:
        if os.name == "nt":
            os.startfile(path)                       # Windows: opens with the app associated to .ini
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])         # macOS
        else:
            subprocess.Popen(["xdg-open", path])     # Linux
        return True, path
    except Exception as e:
        return False, str(e)


def write_minimal_config(path: str, values: dict):
    """Write a minimal config.ini from the current settings (only the keys the GUI has)."""
    lines = [
        "# config.ini cho thu_so_lieu.py — sửa giá trị rồi lưu lại.",
        "# Xóa dòng nào muốn dùng mặc định trong mã.",
        "[thu_so_lieu]",
        f"ftp_host = {values['ftp_host']}",
        f"ftp_user = {values['ftp_user']}",
        f"ftp_pass = {values['ftp_pass']}",
        f"remote_dir = {values['remote_dir']}",
        f"output_dir = {values['output_dir']}",
        f"station_code = {values['station_code']}",
        f"date = {values['date']}",
        f"end_hour = {values['end_hour']}",
        f"delete_on_exit = {'true' if values['delete_on_exit'] else 'false'}",
        f"auto_query_value = {values['auto_query_value']}",
        f"auto_query_unit = {values['auto_query_unit']}",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class App:
    def __init__(self, root: tk.Tk, config_path: str = None):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.last_output_dir = None
        self.auto_job = None        # root.after() id for the pending auto-query tick
        self._dialogs = {}          # keeps references to open dialogs (avoids reopening duplicates)

        # Load the external config (if any) BEFORE prefilling the form
        self.cfg_path, self.cfg_overrides = core.apply_config_file(config_path)

        # Columns hidden in the CSV viewer — shared across all viewer windows
        # (latest/history have the same schema); loaded from config, saved back on change.
        self.hidden_cols = set(core.CONFIG.get("viewer_hidden_columns", []))

        root.title("Thu số liệu quan trắc")
        root.minsize(200, 150)   # temporary low floor, replaced below once real content is laid out

        d = core.CONFIG
        today = datetime.date.today()
        default_date = d.get("date")
        if isinstance(default_date, datetime.datetime):
            default_date = default_date.date()

        self.v = {
            "ftp_host":    tk.StringVar(value=d.get("ftp_host", "")),
            "ftp_user":    tk.StringVar(value=d.get("ftp_user", "")),
            "ftp_pass":    tk.StringVar(value=d.get("ftp_pass", "")),
            "remote_dir":  tk.StringVar(value=d.get("remote_dir", "/Quantrac")),
            "output_dir":  tk.StringVar(value=d.get("output_dir") or core.DEFAULT_OUTPUT_DIR),
            "date":        tk.StringVar(value=(default_date or today).strftime("%Y-%m-%d")),
            "delete_on_exit": tk.BooleanVar(value=bool(d.get("delete_on_exit", False))),
            "show_log":    tk.BooleanVar(value=False),   # log frame hidden by default
            "auto_value":  tk.StringVar(value=str(d.get("auto_query_value", 15))),
            "auto_unit":   tk.StringVar(value="Hours" if d.get("auto_query_unit", "minutes") == "hours" else "Minutes"),
        }

        self._build_menu()
        self._build_ui()
        self._fit_window_to_content()
        # Floor = the natural size with the log hidden (its default state) — small
        # enough to fit just the query box + the 4 buttons, but never smaller.
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.after(100, self._poll)
        self._log("INFO", "Khởi động xong — sẵn sàng. Điền thông tin rồi bấm 'Chạy'.")
        if self.cfg_overrides:
            self._log("OK", f"Đã nạp {len(self.cfg_overrides)} thiết lập từ config: {self.cfg_path}")
        else:
            self._log("INFO", f"Không thấy config ({self.cfg_path}) — dùng mặc định trong mã.")
        self._schedule_auto_tick()

    # -----------------------------------------------------------------
    def _build_menu(self):
        """Menu bar: File / Actions / View / Options / Help. Keeps the main screen compact."""
        menubar = tk.Menu(self.root)

        # --- File ---
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Mở thư mục CSV", command=self._on_open_folder)
        file_menu.add_command(label="Mở thư mục data", command=self._on_open_data)
        file_menu.add_separator()
        file_menu.add_command(label="Thoát", command=self._on_exit)
        menubar.add_cascade(label="Tệp", menu=file_menu)
        self.file_menu = file_menu               # lets us enable/disable "Open CSV folder" by state
        # Not run yet → no CSV folder to open
        self.file_menu.entryconfig("Mở thư mục CSV", state="disabled")

        # --- Actions --- (mirrors the "Chạy" / "Về hiện tại" buttons on the main screen)
        action_menu = tk.Menu(menubar, tearoff=0)
        action_menu.add_command(label="Chạy", command=self._on_run)
        action_menu.add_command(label="Về hiện tại", command=self._on_now)
        menubar.add_cascade(label="Thao tác", menu=action_menu)

        # --- View --- (mirrors the "Xem gần nhất" / "Xem lịch sử" buttons on the main screen)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Xem gần nhất",
                              command=lambda: self._open_csv_viewer("latest.csv", "latest.csv"))
        view_menu.add_command(label="Xem lịch sử",
                              command=lambda: self._open_csv_viewer(
                                  "history.csv", "history.csv", with_station_filter=True))
        menubar.add_cascade(label="Xem", menu=view_menu)

        # --- Options --- (Hiển thị nhật ký toggles the log frame; Thiết lập... opens the
        # combined Kết nối / Đường dẫn / Tự động truy vấn dialog, with config.ini actions
        # at its bottom)
        opt_menu = tk.Menu(menubar, tearoff=0)
        opt_menu.add_checkbutton(label="Hiển thị nhật ký", variable=self.v["show_log"],
                                 command=self._on_toggle_log)
        opt_menu.add_command(label="Thiết lập...", command=self._open_settings_dialog)
        menubar.add_cascade(label="Tùy chọn", menu=opt_menu)

        # --- Help ---
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Cách sử dụng...", command=self._on_help_usage)
        help_menu.add_command(label="Tác giả", command=self._on_help_about)
        menubar.add_cascade(label="Trợ giúp", menu=help_menu)

        self.root.config(menu=menubar)

    # -----------------------------------------------------------------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # --- Top row: Query form (left) + action buttons stacked (right) ---
        top = ttk.Frame(frm)
        top.pack(fill="x")

        # --- Query --- (chỉ còn Ngày — luôn truy vấn trọn 00h–23h của ngày đó)
        q_box = ttk.LabelFrame(top, text="Truy vấn", padding=8)
        q_box.pack(side="left", fill="both", expand=True)
        self._row(q_box, 0, "Ngày (YYYY-MM-DD)", self.v["date"], width=14)
        q_box.columnconfigure(1, weight=1)

        # --- Actions: stacked vertically so they line up as one column ---
        btn_col = ttk.Frame(top)
        btn_col.pack(side="left", fill="y", padx=(8, 0))
        self.run_btn = ttk.Button(btn_col, text="Chạy", command=self._on_run)
        self.run_btn.pack(fill="x")
        ttk.Button(btn_col, text="Về hiện tại",
                   command=self._on_now).pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="Xem gần nhất",
                   command=lambda: self._open_csv_viewer("latest.csv", "latest.csv")
                   ).pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="Xem lịch sử",
                   command=lambda: self._open_csv_viewer("history.csv", "history.csv",
                                                         with_station_filter=True)
                   ).pack(fill="x", pady=(4, 0))

        # --- Progress bar (spans the window's full width) ---
        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.pack(fill="x", pady=(10, 0))

        # --- Status bar at the BOTTOM: indicator sits at bottom-right ---
        statusbar = ttk.Frame(frm)
        statusbar.pack(side="bottom", fill="x", pady=(6, 0))
        self.status = ttk.Label(statusbar, text="Sẵn sàng", anchor="e")
        self.status.pack(side="right")

        # --- Log (fills the middle, sits above the status bar) ---
        # Frame built regardless, only packed/shown if "Hiển thị nhật ký" is on
        # (default off) — the Text widget itself still receives every log line,
        # so nothing is lost while hidden.
        self.log_box = ttk.LabelFrame(frm, text="Nhật ký", padding=6)
        self.log = scrolledtext.ScrolledText(self.log_box, height=12, state="disabled",
                                             wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

        # Color tags for each part of a log line
        self.log.tag_config("ts", foreground="#9ca3af")          # timestamp (light gray)
        for lvl, color in LOG_COLORS.items():                    # level
            self.log.tag_config("lvl_" + lvl, foreground=color)

        if self.v["show_log"].get():
            self.log_box.pack(side="top", fill="both", expand=True, pady=(8, 0))

    def _row(self, parent, r, label, var, width=None, show=None):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        e = ttk.Entry(parent, textvariable=var, show=show)
        if width:
            e.config(width=width)
            e.grid(row=r, column=1, sticky="w", padx=6, pady=3)
        else:
            e.grid(row=r, column=1, sticky="ew", padx=6, pady=3)
        return e

    def _fit_window_to_content(self):
        """Shrink/grow the main window to fit its currently packed widgets (e.g. after
        showing/hiding the log frame) instead of leaving stale empty space."""
        self.root.update_idletasks()
        self.root.geometry("")

    # -----------------------------------------------------------------
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

    # ----- Dialogs (Options) --------------------------------------
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

    def _open_settings_dialog(self):
        """Combined settings dialog: Kết nối / Đường dẫn / Tự động truy vấn, plus
        config.ini actions (create-or-edit at bottom-left, explicit save at bottom-right)."""
        self._log("ACT", "Mở hộp thoại Thiết lập")
        win = self._make_dialog("settings", "Thiết lập")
        if win is None:
            return
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        conn_box = ttk.LabelFrame(frm, text="Kết nối", padding=8)
        conn_box.pack(fill="x")
        self._row(conn_box, 0, "Host",     self.v["ftp_host"])
        self._row(conn_box, 1, "User",     self.v["ftp_user"])
        self._row(conn_box, 2, "Password", self.v["ftp_pass"], show="*")
        conn_box.columnconfigure(1, weight=1)

        path_box = ttk.LabelFrame(frm, text="Đường dẫn", padding=8)
        path_box.pack(fill="x", pady=(8, 0))
        self._row(path_box, 0, "Thư mục server",  self.v["remote_dir"])
        self._row(path_box, 1, "Thư mục xuất CSV", self.v["output_dir"])
        ttk.Button(path_box, text="Chọn...",
                   command=lambda: self._browse_output(parent=win)).grid(row=1, column=2, padx=4)
        ttk.Checkbutton(path_box, text="Xóa file tải về sau khi xong",
                        variable=self.v["delete_on_exit"],
                        command=self._on_toggle_delete).grid(
                        row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        path_box.columnconfigure(1, weight=1)

        # Auto-query: re-runs the pipeline on a timer (system time → "Về hiện tại" →
        # "Chạy"). 0 = tắt tự động truy vấn.
        auto_box = ttk.LabelFrame(frm, text="Tự động truy vấn", padding=8)
        auto_box.pack(fill="x", pady=(8, 0))
        auto_entry = ttk.Entry(auto_box, textvariable=self.v["auto_value"], width=6)
        auto_entry.grid(row=0, column=0, padx=(0, 4))
        auto_entry.bind("<FocusOut>", self._on_auto_change)
        auto_entry.bind("<Return>", self._on_auto_change)
        auto_unit = ttk.Combobox(auto_box, textvariable=self.v["auto_unit"],
                                 values=["Minutes", "Hours"], state="readonly", width=8)
        auto_unit.grid(row=0, column=1)
        auto_unit.bind("<<ComboboxSelected>>", self._on_auto_change)
        ttk.Label(auto_box, text="(0 = tắt)").grid(row=0, column=2, padx=(8, 0))

        btn_bar = ttk.Frame(frm)
        btn_bar.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_bar, text="Tạo/sửa config.ini",
                   command=self._on_edit_config).pack(side="left")
        ttk.Button(btn_bar, text="Lưu thiết lập",
                   command=self._on_save_settings).pack(side="right")

        win.minsize(420, 0)
        self._center_over_root(win)

    def _on_save_settings(self):
        """Persist every field in the Thiết lập dialog to config.ini in one shot."""
        self._log("ACT", "Lưu thiết lập")
        v = self._auto_effective_value()
        self.v["auto_value"].set(str(v))
        unit_key = "hours" if self.v["auto_unit"].get() == "Hours" else "minutes"
        values = {
            "ftp_host":           self.v["ftp_host"].get().strip(),
            "ftp_user":           self.v["ftp_user"].get().strip(),
            "ftp_pass":           self.v["ftp_pass"].get(),
            "remote_dir":         self.v["remote_dir"].get().strip(),
            "output_dir":         self.v["output_dir"].get().strip(),
            "delete_on_exit":     "true" if self.v["delete_on_exit"].get() else "false",
            "auto_query_value":   str(v),
            "auto_query_unit":    unit_key,
        }
        try:
            for key, value in values.items():
                core.update_ini_key(self.cfg_path, core.CONFIG_SECTION, key, value)
            core.CONFIG.update({
                "ftp_host": values["ftp_host"], "ftp_user": values["ftp_user"],
                "ftp_pass": values["ftp_pass"], "remote_dir": values["remote_dir"],
                "output_dir": values["output_dir"],
                "delete_on_exit": self.v["delete_on_exit"].get(),
                "auto_query_value": v, "auto_query_unit": unit_key,
            })
            self._log("OK", f"Đã lưu thiết lập vào config: {self.cfg_path}")
        except OSError as e:
            self._log("ERR", f"Không lưu được thiết lập: {e}")
            messagebox.showerror("Lỗi", f"Không lưu được thiết lập:\n{e}")
        self._schedule_auto_tick()

    # ----- Help ---------------------------------------------------
    def _on_help_usage(self):
        self._log("ACT", "Mở 'Cách sử dụng'")
        messagebox.showinfo(
            "Cách sử dụng",
            "1. Chọn Ngày (YYYY-MM-DD) — luôn truy vấn trọn 00h–23h ngày đó.\n"
            "   Bấm 'Về hiện tại' để tự điền ngày hệ thống.\n\n"
            "2. Bấm 'Chạy' để tải bản tin từ FTP và giải mã.\n"
            "   Theo dõi tiến trình ở thanh trạng thái và Nhật ký bên dưới.\n\n"
            "3. Xem kết quả:\n"
            "   • 'Xem gần nhất' — bản tin mới nhất của TẤT CẢ các trạm.\n"
            "   • 'Xem lịch sử' — lịch sử theo giờ của TẤT CẢ các trạm;\n"
            "     dùng ô 'Trạm' trong cửa sổ xem để lọc riêng 1 trạm\n"
            "     (mặc định lọc theo station_code trong config.ini).\n"
            "   Trong cửa sổ xem, bấm 'Xem raw' để đối chiếu bản tin gốc.\n\n"
            "4. Menu Tùy chọn:\n"
            "   • 'Hiển thị nhật ký' — bật/tắt khung Nhật ký (mặc định tắt).\n"
            "   • 'Thiết lập...' — mở hộp thoại gồm:\n"
            "     - Kết nối: host/user/mật khẩu FTP.\n"
            "     - Đường dẫn: thư mục server, thư mục xuất CSV,\n"
            "       bật/tắt xóa file tải về sau khi xong.\n"
            "     - Tự động truy vấn: tự chạy lại sau mỗi N phút/giờ\n"
            "       (0 = tắt); mỗi lần tự chạy sẽ tự cập nhật Ngày\n"
            "       theo giờ hệ thống rồi 'Chạy' như bình thường.\n"
            "     - 'Tạo/sửa config.ini' — tạo (nếu chưa có) rồi mở\n"
            "       file để sửa tay; cũng là nơi đổi trạm mặc định\n"
            "       cho bộ lọc lịch sử (station_code).\n"
            "     - 'Lưu thiết lập' — lưu ngay các mục trên vào\n"
            "       config.ini để lần chạy sau tự nạp lại.\n\n"
            "5. Menu Tệp:\n"
            "   • 'Mở thư mục CSV' — xem file latest.csv / history.csv.\n"
            "   • 'Mở thư mục data' — xem các bản tin gốc (.txt) đã tải về.")

    def _on_help_about(self):
        self._log("ACT", "Mở 'Tác giả'")
        messagebox.showinfo(
            "Tác giả",
            "Thu số liệu quan trắc\n\n"
            "Tác giả:\n"
            "  congminh9981 — congminh9981@gmail.com\n"
            "  Claude (Anthropic) — đồng tác giả")

    # ----- Exit ------------------------------------------------------
    def _on_exit(self):
        self._log("ACT", "Thoát chương trình")
        self.root.destroy()

    # ----- CSV viewing ----------------------------------------------------
    def _current_output_dir(self) -> str:
        """Directory holding the CSVs: prefers where the last run wrote to, else the form."""
        if self.last_output_dir:
            return self.last_output_dir
        return os.path.abspath(self.v["output_dir"].get().strip() or core.DEFAULT_OUTPUT_DIR)

    def _open_csv_viewer(self, filename: str, title: str, with_station_filter: bool = False):
        """Open a dedicated window to view a CSV file as a table (read-only)."""
        self._log("ACT", f"Xem {filename}")
        path = os.path.join(self._current_output_dir(), filename)
        if not os.path.isfile(path):
            self._log("ERR", f"Chưa có {filename} trong {self._current_output_dir()} — hãy Chạy trước")
            messagebox.showwarning(
                "Chưa có file",
                f"Không tìm thấy:\n{path}\n\nHãy bấm 'Chạy' để tạo file trước.")
            return

        key = "view_" + filename
        existing = self._dialogs.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify(); existing.lift(); existing.focus_set()
            self._load_csv_into_viewer(existing, path)   # refresh the content
            return

        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.geometry("900x420")
        win.minsize(480, 240)
        self._dialogs[key] = win
        win._path = path
        win._mode = "data"          # "data" (hides raw) | "raw" (identity cols + raw only)
        win._header, win._data = [], []
        win._sort_col, win._sort_reverse = None, False   # column currently sorted & direction

        # Toolbar
        bar = ttk.Frame(win, padding=(8, 6))
        bar.pack(fill="x")
        win._toggle_btn = ttk.Button(bar, text="Xem raw",
                                     command=lambda: self._toggle_viewer_mode(win))
        win._toggle_btn.pack(side="left")
        ttk.Button(bar, text="Làm mới",
                   command=lambda: self._load_csv_into_viewer(win, path)).pack(side="left", padx=6)
        ttk.Button(bar, text="Mở bằng Excel",
                   command=lambda: self._open_csv_external(path)).pack(side="left")
        ttk.Button(bar, text="Hiển thị",
                   command=lambda: self._open_column_picker(win)).pack(side="left", padx=6)

        # Station filter — post-process filter over history.csv (which already holds
        # every station); default to the station_code configured in config.ini.
        if with_station_filter:
            default_code = (core.CONFIG.get("station_code") or "").strip()
            default_name = STATIONS.get(default_code, ALL_STATIONS)
            win._station_filter = tk.StringVar(value=default_name)
            ttk.Label(bar, text="Trạm:").pack(side="left", padx=(12, 2))
            ttk.Combobox(bar, textvariable=win._station_filter,
                        values=[ALL_STATIONS] + STATION_NAMES, state="readonly",
                        width=16).pack(side="left")
            win._station_filter.trace_add("write", lambda *_: self._on_station_filter_change(win))
        else:
            win._station_filter = None

        win._status = ttk.Label(bar, text="")
        win._status.pack(side="right")

        # Table + two scrollbars
        tf = ttk.Frame(win, padding=(8, 0, 8, 8))
        tf.pack(fill="both", expand=True)
        tree = ttk.Treeview(tf, show="headings")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        win._tree = tree

        self._center_over_root(win)
        self._load_csv_into_viewer(win, path)

    def _load_csv_into_viewer(self, win, path: str):
        """Read the CSV into the viewer window's memory, then draw it in the current mode."""
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except OSError as e:
            win._status.config(text=f"Lỗi đọc file: {e}")
            self._log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
            return

        if not rows:
            win._header, win._data = [], []
            win._tree.delete(*win._tree.get_children())
            win._tree["columns"] = ()
            win._status.config(text="File rỗng")
            return

        win._header, win._data = rows[0], rows[1:]
        self._apply_sort(win)         # keep the current sort (if any) after reloading
        self._render_viewer(win)
        self._log("OK", f"Đã hiển thị {os.path.basename(path)} ({len(win._data)} dòng)")

    def _toggle_viewer_mode(self, win):
        """Switch between Data mode (hides raw) and Raw mode (identity cols + raw)."""
        win._mode = "raw" if win._mode == "data" else "data"
        self._log("ACT", f"Xem CSV — chế độ {'Raw' if win._mode == 'raw' else 'Số liệu'}")
        self._render_viewer(win)

    def _on_station_filter_change(self, win):
        self._log("ACT", f"Lọc trạm: {win._station_filter.get()}")
        self._render_viewer(win)

    # ----- Column sorting --------------------------------------------
    def _apply_sort(self, win):
        """Sort win._data in place by the current win._sort_col/_sort_reverse (if set)."""
        col = win._sort_col
        if not col or col not in win._header:
            return
        idx = win._header.index(col)
        numeric = col in NUMERIC_VIEWER_COLUMNS or col.endswith("_hshs")

        def key(row):
            v = row[idx] if idx < len(row) else ""
            if numeric:
                try:
                    return (0, float(v))
                except ValueError:
                    return (1, 0.0)          # empty/non-numeric → sorted last
            return (0, v) if v else (1, "")

        win._data.sort(key=key, reverse=win._sort_reverse)

    def _sort_viewer(self, win, col):
        """Click a column header: new column → ascending; same column again → reverses."""
        if not win._header or col not in win._header:
            return
        if win._sort_col == col:
            win._sort_reverse = not win._sort_reverse
        else:
            win._sort_col, win._sort_reverse = col, False
        self._log("ACT", f"Sắp xếp theo '{col}' ({'giảm dần' if win._sort_reverse else 'tăng dần'})")
        self._apply_sort(win)
        self._render_viewer(win)

    # ----- Column visibility --------------------------------------------
    def _open_column_picker(self, win):
        """Open a checkbox dialog to pick visible columns (shared across all viewer windows)."""
        self._log("ACT", "Mở 'Hiển thị cột'")
        dlg = self._make_dialog("columns", "Chọn cột hiển thị")
        if dlg is None:
            return
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        header = win._header or []
        col_vars = {}
        ncols = 3
        for i, c in enumerate(header):
            var = tk.BooleanVar(value=c not in self.hidden_cols)
            col_vars[c] = var
            r, cpos = divmod(i, ncols)
            ttk.Checkbutton(frm, text=c, variable=var).grid(
                row=r, column=cpos, sticky="w", padx=6, pady=2)

        btn_row = (max(len(header), 1) - 1) // ncols + 1
        btns = ttk.Frame(frm)
        btns.grid(row=btn_row, column=0, columnspan=ncols, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Đóng", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Áp dụng",
                   command=lambda: self._apply_column_selection(col_vars)).pack(
                   side="right", padx=6)

        dlg.minsize(360, 0)
        self._center_over_root(dlg)

    def _apply_column_selection(self, col_vars: dict):
        """Read checkbox states → update self.hidden_cols, redraw every open viewer, save to config."""
        self.hidden_cols = {c for c, v in col_vars.items() if not v.get()}
        self._log("ACT", f"Áp dụng hiển thị cột — ẩn {len(self.hidden_cols)} cột")
        for key, w in self._dialogs.items():
            if key.startswith("view_") and w.winfo_exists():
                self._render_viewer(w)
        self._save_hidden_columns_to_config()

    def _save_hidden_columns_to_config(self):
        value = ",".join(sorted(self.hidden_cols))
        try:
            core.update_ini_key(self.cfg_path, core.CONFIG_SECTION, "viewer_hidden_columns", value)
            core.CONFIG["viewer_hidden_columns"] = sorted(self.hidden_cols)
            self._log("OK", f"Đã lưu lựa chọn cột vào config: {self.cfg_path}")
        except OSError as e:
            self._log("ERR", f"Không lưu được lựa chọn cột vào config: {e}")

    def _render_viewer(self, win):
        """Rebuild the table from win._mode + self.hidden_cols, using the loaded win._header/_data."""
        tree, header, data, mode = win._tree, win._header, win._data, win._mode
        if not header:
            return

        if win._station_filter is not None and "station_code" in header:
            name = win._station_filter.get()
            if name != ALL_STATIONS:
                code = NAME_TO_CODE.get(name)
                sc_idx = header.index("station_code")
                data = [r for r in data if sc_idx < len(r) and r[sc_idx] == code]

        if mode == "raw":
            # Just a few identity columns + raw, to read the original bulletin per station.
            prefer = ["obs_time", "station", "station_code", "source_file",
                      "hour", "cloud_layers", "raw"]
            cols = [c for c in prefer if c in header]
        else:
            cols = [c for c in header if c != "raw"]   # data mode: all columns, minus raw
        cols = [c for c in cols if c not in self.hidden_cols]   # apply the column selection

        idx = {c: header.index(c) for c in cols}

        tree.delete(*tree.get_children())
        tree["columns"] = cols
        for c in cols:
            is_sorted = (c == win._sort_col)
            arrow = "" if not is_sorted else (" ▼" if win._sort_reverse else " ▲")
            tree.heading(c, text=c + arrow, command=lambda c=c: self._sort_viewer(win, c))
            if c == "raw":
                tree.column(c, width=560, stretch=True, anchor="w")
            else:
                w = max(60, min(240, (len(c) + 2) * 8))
                anchor = "e" if (c in NUMERIC_VIEWER_COLUMNS or c.endswith("_hshs")) else "w"
                tree.column(c, width=w, stretch=False, anchor=anchor)

        for r in data:
            tree.insert("", "end",
                        values=[r[idx[c]] if idx[c] < len(r) else "" for c in cols])

        tree.xview_moveto(0)
        win._status.config(text=f"Chế độ: {'Raw' if mode == 'raw' else 'Số liệu'} — "
                                f"{len(data)} dòng × {len(cols)} cột")
        win._toggle_btn.config(text="Xem số liệu" if mode == "raw" else "Xem raw")

    def _open_csv_external(self, path: str):
        """Open the CSV file with its default application (usually Excel on Windows)."""
        self._log("ACT", f"Mở bằng Excel: {os.path.basename(path)}")
        ok, info = open_in_editor(path)
        if ok:
            self._log("OK", f"Đã mở: {info}")
        else:
            self._log("ERR", f"Không mở được: {info}")
            messagebox.showwarning("Không mở được", info)

    def _on_now(self):
        """Reset the Query to now: date = today."""
        now = datetime.datetime.now()
        self.v["date"].set(now.strftime("%Y-%m-%d"))
        self._log("ACT", f"Về hiện tại: ngày {now:%Y-%m-%d}")

    # ----- Auto-query (timer) ----------------------------------------
    def _auto_effective_minutes(self) -> int:
        """Current interval in minutes; 0 means auto-query is off."""
        try:
            v = int(self.v["auto_value"].get().strip())
        except ValueError:
            v = 0
        v = max(v, 0)
        return v * 60 if self.v["auto_unit"].get() == "Hours" else v

    def _schedule_auto_tick(self):
        """(Re)schedule the next auto-query tick from the current value/unit; cancels any pending one first."""
        if self.auto_job is not None:
            self.root.after_cancel(self.auto_job)
            self.auto_job = None
        minutes = self._auto_effective_minutes()
        if minutes <= 0:
            return
        self.auto_job = self.root.after(minutes * 60 * 1000, self._on_auto_tick)

    def _on_auto_tick(self):
        self.auto_job = None
        if self.worker and self.worker.is_alive():
            self._log("SKIP", "Tự động truy vấn: bỏ qua vì đang có tác vụ chạy")
        else:
            self._log("ACT", "Tự động truy vấn: về hiện tại rồi chạy")
            self._on_now()
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

    def _on_toggle_delete(self):
        state = "Bật" if self.v["delete_on_exit"].get() else "Tắt"
        self._log("ACT", f"Tùy chọn 'Xóa file tải về sau khi xong': {state}")

    def _on_toggle_log(self):
        show = self.v["show_log"].get()
        if show:
            self.log_box.pack(side="top", fill="both", expand=True, pady=(8, 0))
        else:
            self.log_box.pack_forget()
        self._fit_window_to_content()
        self._log("ACT", f"Tùy chọn 'Hiển thị nhật ký': {'Bật' if show else 'Tắt'}")

    def _on_open_folder(self):
        self._log("ACT", "Mở thư mục CSV")
        ok, info = open_folder(self.last_output_dir)
        if ok:
            self._log("OK", f"Đã mở thư mục CSV: {info}")
        else:
            self._log("ERR", f"Không mở được thư mục CSV: {info}")

    def _on_open_data(self):
        self._log("ACT", "Mở thư mục data")
        os.makedirs(core.TEMP_DL_DIR, exist_ok=True)   # create it upfront if never run before
        ok, info = open_folder(core.TEMP_DL_DIR)
        if ok:
            self._log("OK", f"Đã mở thư mục data: {info}")
        else:
            self._log("ERR", f"Không mở được thư mục data: {info}")

    def _read_form_values(self) -> dict:
        """Current form values (as strings/bools) for writing out to config.ini."""
        return {
            "ftp_host": self.v["ftp_host"].get().strip(),
            "ftp_user": self.v["ftp_user"].get().strip(),
            "ftp_pass": self.v["ftp_pass"].get(),
            "remote_dir": self.v["remote_dir"].get().strip(),
            "output_dir": self.v["output_dir"].get().strip(),
            "station_code": core.CONFIG.get("station_code", ""),
            "date": self.v["date"].get().strip(),
            "end_hour": 23,
            "delete_on_exit": self.v["delete_on_exit"].get(),
            "auto_query_value": self._auto_effective_value(),
            "auto_query_unit": "hours" if self.v["auto_unit"].get() == "Hours" else "minutes",
        }

    def _on_edit_config(self):
        self._log("ACT", "Tạo/sửa config.ini")
        path = os.path.abspath(self.cfg_path)
        created = False
        if not os.path.isfile(path):
            try:
                write_minimal_config(path, self._read_form_values())
                created = True
                self._log("OK", f"Đã tạo config từ thiết lập hiện tại: {path}")
            except Exception as e:
                self._log("ERR", f"Không tạo được config: {e}")
                messagebox.showerror("Lỗi", f"Không tạo được config:\n{e}")
                return
        ok, info = open_in_editor(path)
        if ok:
            if created:
                self._log("OK", f"Đã tạo & mở config để sửa "
                              f"(lần chạy sau tự nạp): {info}")
            else:
                self._log("ACT", f"Mở config để sửa: {info}")
        else:
            self._log("ERR", f"Không mở được config: {info}")
            messagebox.showwarning("Không mở được",
                                   f"{info}\n\nBạn có thể mở tay file:\n{path}")

    def _browse_output(self, parent=None):
        self._log("ACT", "Chọn thư mục xuất CSV")
        p = filedialog.askdirectory(title="Chọn thư mục xuất CSV",
                                    parent=parent or self.root)
        if p:
            self.v["output_dir"].set(p)
            self._log("OK", f"Thư mục xuất CSV: {p}")
        else:
            self._log("INFO", "Đã hủy chọn thư mục xuất")

    def _build_cfg(self) -> dict:
        """Read the form → cfg dict; local_dir/timeout/retry come from core's fixed constants.

        end_hour is always 23 — a query always spans the whole day (00h–23h).
        """
        try:
            date = datetime.datetime.strptime(self.v["date"].get().strip(), "%Y-%m-%d")
        except ValueError:
            raise ValueError("Ngày phải theo định dạng YYYY-MM-DD, vd 2026-08-10")

        return {
            "ftp_host": self.v["ftp_host"].get().strip(),
            "ftp_user": self.v["ftp_user"].get().strip(),
            "ftp_pass": self.v["ftp_pass"].get(),
            "ftp_timeout": core.CONFIG.get("ftp_timeout", core.FTP_TIMEOUT),
            "retry_temp": core.CONFIG.get("retry_temp", core.RETRY_TEMP),
            "retry_wait": core.CONFIG.get("retry_wait", core.RETRY_WAIT),
            "remote_dir": self.v["remote_dir"].get().strip() or "/Quantrac",
            "local_dir":  core.TEMP_DL_DIR,
            "output_dir": self.v["output_dir"].get().strip() or core.DEFAULT_OUTPUT_DIR,
            "delete_on_exit": self.v["delete_on_exit"].get(),
            "date": date,
            "end_hour": 23,
        }

    # -----------------------------------------------------------------
    def _on_run(self):
        self._log("ACT", "Bấm 'Chạy'")
        if self.worker and self.worker.is_alive():
            self._log("WARN", "Bỏ qua: một tác vụ đang chạy")
            return
        try:
            cfg = self._build_cfg()
        except ValueError as e:
            self._log("ERR", f"Nhập sai: {e}")
            messagebox.showerror("Nhập sai", str(e))
            return
        if not cfg["ftp_host"]:
            self._log("ERR", "Nhập sai: chưa nhập FTP host")
            messagebox.showerror("Nhập sai", "Chưa nhập FTP host")
            return

        self._divider()
        self._log("ACT", f"Bắt đầu: ngày {cfg['date']:%Y-%m-%d} (00h–23h)")
        self.run_btn.config(state="disabled")
        self.file_menu.entryconfig("Mở thư mục CSV", state="disabled")
        self.status.config(text="Đang chạy...")
        self.bar.config(value=0, maximum=cfg["end_hour"] + 1)

        self.worker = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker.start()

    def _work(self, cfg):
        """Worker thread — only pushes events onto the queue, never touches widgets."""
        q = self.q
        def log(level, msg): q.put(("log", level, msg))
        def progress(done, total, status): q.put(("progress", done, total))
        try:
            result = core.run_pipeline(cfg, log=log, progress=progress)
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
                    self.bar.config(maximum=total, value=done)
                    self.status.config(text=f"Tải {done}/{total}")
                elif kind == "done":
                    self._on_done(item[1])
                elif kind == "error":
                    self._log("ERR", item[1])
                    self.status.config(text="Lỗi")
                    self.run_btn.config(state="normal")
                    messagebox.showerror("Lỗi", item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_done(self, result: dict):
        self.run_btn.config(state="normal")
        self.last_output_dir = result.get("output_dir")
        if self.last_output_dir and os.path.isdir(self.last_output_dir):
            self.file_menu.entryconfig("Mở thư mục CSV", state="normal")

        if not result.get("ok"):
            self.status.config(text="Không có dữ liệu")
            miss = result.get("missing") or []
            if miss:
                self._log("WARN", f"Thiếu {len(miss)} file trên server")
            return

        self.status.config(text="Hoàn tất")
        parts = []
        if result.get("latest_csv"):
            parts.append(f"latest.csv ({result['latest_records']} trạm)")
        if result.get("history_csv"):
            parts.append(f"history.csv ({result['history_records']} record)")
        self._log("OK", "Hoàn tất — đã xuất: " + (", ".join(parts) if parts else "(không có)"))


def main():
    # Allows: python thu_so_lieu_gui.py [config_ini_path]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    App(root, config_path=config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
