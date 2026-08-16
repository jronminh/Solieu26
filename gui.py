"""
gui.py
===================
Tkinter GUI wrapping core.py (imported as `core`).

Run:  python gui.py [config.ini path]
Requires core.py in the same folder.

Anti-freeze architecture: heavy work (FTP + decode + CSV export, all in core)
runs on a worker thread that never touches widgets — it only pushes ('log' /
'progress' / 'done' / 'error') events onto a queue.Queue(); the main thread
polls the queue every 100ms via root.after() and applies the UI updates itself.

Tác giả: congminh9981 (congminh9981@gmail.com); Claude (Anthropic) — đồng tác giả.
"""

import csv
import datetime
import os
import queue
import re
import subprocess
import sys
import threading

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import core


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
# Feeds the station filter dropdown in the "Xem lịch sử" viewer (each history_*.csv
# holds every station already — the dropdown just filters rows client-side, it no
# longer drives what gets downloaded/decoded). Add/remove a station by editing this table.
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

# Names feed the dropdown — order KEPT the same as the STATIONS table above;
# also builds the reverse lookup name → code.
STATION_NAMES = list(STATIONS.values())
NAME_TO_CODE  = {name: code for code, name in STATIONS.items()}

ALL_STATIONS = "Tất cả các trạm"   # station-filter dropdown option that disables filtering

# Hours feed the hour-filter dropdown in the "Xem lịch sử" viewer — each
# history_*.csv's "hour" column is a zero-padded string ("00".."23"), so the
# dropdown values match.
HOURS = [f"{h:02d}" for h in range(24)]
ALL_HOURS = "Tất cả các giờ"   # hour-filter dropdown option that disables filtering

# Matches core.export_history_by_date()'s output filenames — one CSV per day.
# The viewer's Ngày dropdown lists dates found this way and picks which file to
# load, rather than filtering rows within a single (now nonexistent) history.csv.
HISTORY_CSV_RE = re.compile(r"^history_(\d{8})\.csv$")


# Numeric columns in the CSV viewer — right-aligned + compared as NUMBERS when
# sorting (instead of as strings). *_hshs columns are numeric too but their names
# aren't fixed (cloud_1_hshs, cloud_2_hshs...) so they're detected by suffix instead
# of being listed here.
NUMERIC_VIEWER_COLUMNS = {
    "lat", "lon", "visibility_km", "total_cloud_N", "wind_dd_deg",
    "wind_ff", "temperature_c", "dewpoint_c", "pressure_hpa",
    "cloud_layers", "hour",
}

# Columns that never appear in the CSV viewer — not shown in either mode, and
# not offered in the "Hiển thị" picker either, so they can't be toggled back on
# from the GUI. They stay in the exported CSV file untouched; the only way to
# see them is opening a history_*.csv file directly (e.g. in Excel).
ALWAYS_HIDDEN_VIEWER_COLUMNS = {
    "date", "hour", "source_file", "station_code", "lat", "lon", "cloud_layers",
}


def _is_numeric_viewer_column(col: str) -> bool:
    """*_hshs columns are numeric too, but their names aren't fixed
    (cloud_1_hshs, cloud_2_hshs...), so they're matched by suffix instead of
    being listed in NUMERIC_VIEWER_COLUMNS."""
    return col in NUMERIC_VIEWER_COLUMNS or col.endswith("_hshs")


def _os_open(path: str):
    """Hand `path` to the OS's default handler — file manager for a folder, the
    associated app for a file. Returns (ok: bool, reason/path)."""
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


def open_folder(path: str):
    """Open a folder with the OS's file manager. Returns (ok: bool, reason/path)."""
    if not path:
        return False, "chưa có thư mục xuất (cần chạy thành công ít nhất một lần)"
    path = os.path.abspath(path)                      # './x' → absolute (Windows dislikes relative paths)
    if not os.path.isdir(path):
        return False, f"thư mục không tồn tại: {path}"
    return _os_open(path)


def open_in_editor(path: str):
    """Open a FILE with its default application (for editing). Returns (ok, reason/path)."""
    if not path:
        return False, "chưa có đường dẫn file"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, f"file không tồn tại: {path}"
    return _os_open(path)


def write_minimal_config(path: str, values: dict):
    """Write a minimal config.ini from the current settings (only the keys the GUI has)."""
    lines = [
        "# config.ini cho Solieu26 — sửa giá trị rồi lưu lại.",
        "# Xóa dòng nào muốn dùng mặc định trong mã.",
        "[Solieu26]",
        f"ftp_host = {values['ftp_host']}",
        f"ftp_user = {values['ftp_user']}",
        f"ftp_pass = {values['ftp_pass']}",
        f"remote_dir = {values['remote_dir']}",
        f"output_dir = {values['output_dir']}",
        f"station_code = {values['station_code']}",
        f"end_hour = {values['end_hour']}",
        f"delete_on_exit = {'true' if values['delete_on_exit'] else 'false'}",
        f"auto_query_value = {values['auto_query_value']}",
        f"auto_query_unit = {values['auto_query_unit']}",
        f"auto_query_on_startup = {'true' if values['auto_query_on_startup'] else 'false'}",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class App:
    def __init__(self, root: tk.Tk, config_path: str = None):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self._run_in_progress = False  # mirrors _set_actions_enabled — feeds _refresh_advanced_controls_state
        self.last_output_dir = None
        self.auto_job = None        # root.after() id for the pending auto-query tick
        self.auto_next_run = None   # datetime of the next scheduled auto-query tick (None = off)
        self.last_result = None     # result dict from the last completed run (for the info panel)
        self.last_cfg = None        # cfg dict from the last _on_run (carries the queried date)
        self.last_updated_at = None # datetime the last run finished (success or not)
        self._dialogs = {}          # keeps references to open dialogs (avoids reopening duplicates)

        # Load the external config (if any) BEFORE prefilling the form
        self.cfg_path, self.cfg_overrides = core.apply_config_file(config_path)

        # Columns hidden in the CSV viewer — shared across all viewer windows
        # (every history_*.csv has the same schema); loaded from config, saved back on change.
        self.hidden_cols = set(core.CONFIG.get("viewer_hidden_columns", []))

        root.title("Solieu26")
        root.minsize(200, 150)   # temporary low floor, replaced below once real content is laid out
        icon_path = os.path.join(core.SCRIPT_DIR, "icon.ico")
        if os.path.isfile(icon_path):
            try:
                root.iconbitmap(icon_path)
            except tk.TclError:
                pass   # e.g. platform without .ico support — window just keeps the default icon

        # CSV viewer Treeview look — taller rows + bold headings read better than
        # the ttk defaults across the many columns flatten_record() produces.
        style = ttk.Style(root)
        style.configure("Treeview", rowheight=22)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        d = core.CONFIG
        today = datetime.date.today()

        self.v = {
            "ftp_host":    tk.StringVar(value=d.get("ftp_host", "")),
            "ftp_user":    tk.StringVar(value=d.get("ftp_user", "")),
            "ftp_pass":    tk.StringVar(value=d.get("ftp_pass", "")),
            "remote_dir":  tk.StringVar(value=d.get("remote_dir", "/Quantrac")),
            "output_dir":  tk.StringVar(value=d.get("output_dir") or core.DEFAULT_OUTPUT_DIR),
            # Advanced mode (date-range query) — off by default; normal mode always
            # queries "today", no date field shown.
            "advanced_mode": tk.BooleanVar(value=False),
            "start_date":  tk.StringVar(value=today.strftime("%Y-%m-%d")),
            "end_date":    tk.StringVar(value=today.strftime("%Y-%m-%d")),
            "delete_on_exit": tk.BooleanVar(value=bool(d.get("delete_on_exit", False))),
            "auto_value":  tk.StringVar(value=str(d.get("auto_query_value", 15))),
            "auto_unit":   tk.StringVar(value="Hours" if d.get("auto_query_unit", "minutes") == "hours" else "Minutes"),
            "auto_on_startup": tk.BooleanVar(value=bool(d.get("auto_query_on_startup", False))),
        }

        # Read-only labels in the "Thông tin truy vấn" panel — recomputed by
        # _refresh_info_panel() whenever the underlying state changes.
        self.info = {
            "csv_result":    tk.StringVar(value="—"),
            "data_status":   tk.StringVar(value="Chưa có dữ liệu"),
            "auto_status":   tk.StringVar(value="—"),
            "missing":       tk.StringVar(value="—"),
        }

        self._build_menu()
        self._build_ui()
        self._fit_window_to_content()
        # Floor = the natural size with every field + the log shown.
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.after(100, self._poll)
        self._log("INFO", "Khởi động xong — sẵn sàng. Điền thông tin rồi bấm 'Làm mới'.")
        if self.cfg_overrides:
            self._log("OK", f"Đã nạp {len(self.cfg_overrides)} thiết lập từ config: {self.cfg_path}")
        else:
            self._log("INFO", f"Không thấy config ({self.cfg_path}) — dùng mặc định trong mã.")
        self._schedule_auto_tick()   # also refreshes the info panel's auto-query status

        if self.v["auto_on_startup"].get():
            self._log("ACT", "Tự động truy vấn khi khởi động")
            self.root.after(300, self._on_run)   # small delay so the window renders first

    # -----------------------------------------------------------------
    def _build_menu(self):
        """Single menu bar entry, 'Tùy chọn' — every action (run / toggles /
        settings / file ops) lives here. Xem số liệu is a button on the main
        screen now, not a menu item — see _build_ui."""
        menubar = tk.Menu(self.root)

        # --- Tùy chọn --- grouped: run → toggles/settings → file ops
        opt_menu = tk.Menu(menubar, tearoff=0)

        opt_menu.add_command(label="Làm mới", command=self._on_run)
        opt_menu.add_separator()

        # Thiết lập... opens the combined Kết nối / Đường dẫn / Tự động truy vấn
        # dialog, with config.ini actions at its bottom.
        opt_menu.add_command(label="Thiết lập...", command=self._open_settings_dialog)
        opt_menu.add_separator()

        opt_menu.add_command(label="Mở thư mục CSV", command=self._on_open_folder)
        opt_menu.add_command(label="Mở thư mục data", command=self._on_open_data)
        opt_menu.add_separator()
        opt_menu.add_command(label="Thoát", command=self._on_exit)

        menubar.add_cascade(label="Tùy chọn", menu=opt_menu)
        self.opt_menu = opt_menu   # lets us enable/disable entries by state ("Làm mới" while
                                    # running, "Mở thư mục CSV" until there's something to open)
        self.opt_menu.entryconfig("Mở thư mục CSV", state="disabled")   # nothing to open yet

        self.root.config(menu=menubar)

    # -----------------------------------------------------------------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # --- Truy vấn nâng cao: checkbox chỉ đổi CHẾ ĐỘ truy vấn (ngày đơn ↔
        # khoảng ngày) và tạm dừng/tiếp tục tự động truy vấn. Chế độ thường (bỏ
        # tick, mặc định) luôn truy vấn "hôm nay".
        self.adv_check = ttk.Checkbutton(frm, text="Nâng cao",
                                         variable=self.v["advanced_mode"],
                                         command=self._on_toggle_advanced)
        self.adv_check.pack(anchor="w")

        # --- Thông tin truy vấn --- (read-only status; recomputed by _refresh_info_panel)
        # No LabelFrame border — laid directly on frm.
        top = ttk.Frame(frm)
        top.pack(fill="x", pady=(8, 0))

        def info_row(r, caption, var=None, widget=None):
            """One grid row: caption label + either a read-only value (var, as a
            Label) or an editable/composite widget passed in directly."""
            cap = ttk.Label(top, text=caption)
            val = widget if widget is not None else ttk.Label(top, textvariable=var)
            cap.grid(row=r, column=0, sticky="w", padx=6, pady=2)
            val.grid(row=r, column=1, sticky="ew" if widget is not None else "w", padx=6, pady=2)

        # Ngày bắt đầu/kết thúc + 2 nút điều khiển chỉ THẬT SỰ dùng được khi
        # "Truy vấn nâng cao" được tick — _refresh_advanced_controls_state() giữ
        # chúng ở trạng thái disabled khi chưa tick.
        self.start_date_entry = ttk.Entry(top, textvariable=self.v["start_date"], width=12)
        info_row(0, "Ngày bắt đầu:", widget=self.start_date_entry)

        self.end_date_entry = ttk.Entry(top, textvariable=self.v["end_date"], width=12)
        info_row(1, "Ngày kết thúc:", widget=self.end_date_entry)

        # "Bắt đầu" chạy truy vấn nâng cao ngay tại chỗ; "Về hiện tại" nằm cạnh —
        # cả hai căn giữa trên dòng riêng ngay dưới Ngày kết thúc.
        btn_row = ttk.Frame(top)
        self.start_btn = ttk.Button(btn_row, text="Bắt đầu", command=self._on_run)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.now_btn = ttk.Button(btn_row, text="Về hiện tại", command=self._on_now)
        self.now_btn.pack(side="left")
        btn_row.grid(row=2, column=0, columnspan=2, pady=(2, 4))

        info_row(3, "Máy chủ:", self.v["ftp_host"])
        info_row(4, "Xuất CSV:", self.info["csv_result"])
        info_row(5, "Dữ liệu:", self.info["data_status"])
        info_row(6, "Tự động:", self.info["auto_status"])
        info_row(7, "File thiếu:", self.info["missing"])
        top.columnconfigure(1, weight=1)

        # --- Xem số liệu — ngay dưới trường dữ liệu, căn giữa. pack() không
        # fill/expand → tự căn giữa theo chiều ngang trong frm.
        view_row = ttk.Frame(frm)
        view_row.pack(pady=(8, 0))
        ttk.Button(view_row, text="Xem số liệu",
                  command=self._open_history_viewer).pack(side="left")

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

        self._refresh_advanced_controls_state()

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
        # "Làm mới"). 0 = tắt tự động truy vấn.
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
        ttk.Checkbutton(auto_box, text="Tự động truy vấn khi khởi động",
                        variable=self.v["auto_on_startup"]).grid(
                        row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

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
            "auto_query_on_startup": "true" if self.v["auto_on_startup"].get() else "false",
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
                "auto_query_on_startup": self.v["auto_on_startup"].get(),
            })
            self._log("OK", f"Đã lưu thiết lập vào config: {self.cfg_path}")
        except OSError as e:
            self._log("ERR", f"Không lưu được thiết lập: {e}")
            messagebox.showerror("Lỗi", f"Không lưu được thiết lập:\n{e}")
        self._schedule_auto_tick()

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

    def _available_history_files(self) -> dict:
        """Scan the current output dir for history_YYYYMMDD.csv files (one per
        day, written by core.export_history_by_date). Returns {"YYYY-MM-DD": path},
        sorted by nothing in particular — callers sort the keys as needed."""
        out_dir = self._current_output_dir()
        found = {}
        try:
            names = os.listdir(out_dir)
        except OSError:
            return found
        for name in names:
            m = HISTORY_CSV_RE.match(name)
            if m:
                ymd = m.group(1)
                date_key = f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"
                found[date_key] = os.path.join(out_dir, name)
        return found

    def _open_history_viewer(self):
        """'Xem số liệu' — opens the history viewer showing the MOST RECENT day
        available on disk. core.export_history_by_date() writes one
        history_YYYYMMDD.csv per day, so a multi-day advanced query leaves several
        files behind — the 'Ngày' dropdown inside the viewer switches between them."""
        history_files = self._available_history_files()
        if not history_files:
            self._log("WARN", "Xem số liệu: chưa có file lịch sử nào — hãy 'Làm mới' trước")
            messagebox.showwarning("Chưa có dữ liệu",
                                   "Chưa có file lịch sử nào.\n\nHãy bấm 'Làm mới' để tạo file trước.")
            return
        self._show_history_date(max(history_files))

    def _show_history_date(self, date_key: str):
        """Open the (single, shared) history viewer window on history_YYYYMMDD.csv
        for `date_key`, or switch its content to that date if it's already open."""
        history_files = self._available_history_files()
        path = history_files.get(date_key)
        filename = f"history_{date_key.replace('-', '')}.csv"
        self._log("ACT", f"Xem {filename}")
        if not path or not os.path.isfile(path):
            self._log("ERR", f"Chưa có {filename} trong {self._current_output_dir()} — hãy Làm mới trước")
            messagebox.showwarning(
                "Chưa có file",
                f"Không có dữ liệu ngày {date_key}.\n\nHãy bấm 'Làm mới' để tạo file trước.")
            return

        key = "view_history"
        existing = self._dialogs.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify(); existing.lift(); existing.focus_set()
            existing.title(filename)
            existing._path = path
            existing._date_filter.set(date_key)   # triggers _on_date_filter_change → reloads
            return

        win = tk.Toplevel(self.root)
        win.title(filename)
        win.transient(self.root)
        win.geometry("1040x480")
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
                   command=lambda: self._load_csv_into_viewer(win, win._path)).pack(side="left", padx=6)
        ttk.Button(bar, text="Mở bằng Excel",
                   command=lambda: self._open_csv_external(win._path)).pack(side="left")
        ttk.Button(bar, text="Hiển thị",
                   command=lambda: self._open_column_picker(win)).pack(side="left", padx=6)

        # Station filter — post-process filter over the loaded day's file (which
        # already holds every station); default to the station_code configured
        # in config.ini.
        default_code = (core.CONFIG.get("station_code") or "").strip()
        default_name = STATIONS.get(default_code, ALL_STATIONS)
        win._station_filter = tk.StringVar(value=default_name)
        ttk.Label(bar, text="Trạm:").pack(side="left", padx=(12, 2))
        ttk.Combobox(bar, textvariable=win._station_filter,
                    values=[ALL_STATIONS] + STATION_NAMES, state="readonly",
                    width=16).pack(side="left")
        win._station_filter.trace_add("write", lambda *_: self._on_station_filter_change(win))

        # Hour filter — same post-process idea as the station filter above, but over
        # the "hour" column (always present, just hidden from the rendered table).
        # Its OWN options are derived from the station filter (see
        # _sync_hour_filter_for_station): a specific station locks giờ to "Tất cả
        # các giờ" (one station's whole history), while "Tất cả các trạm" hides that
        # option and forces a specific giờ (otherwise the table would be every
        # station × every hour at once).
        win._hour_filter = tk.StringVar(value=ALL_HOURS)
        ttk.Label(bar, text="Giờ:").pack(side="left", padx=(12, 2))
        win._hour_combo = ttk.Combobox(bar, textvariable=win._hour_filter,
                    values=[ALL_HOURS] + HOURS, state="readonly",
                    width=8)
        win._hour_combo.pack(side="left")
        win._hour_filter.trace_add("write", lambda *_: self._on_hour_filter_change(win))

        self._sync_hour_filter_for_station(win)

        # Date filter — NOT a row filter: each history_YYYYMMDD.csv is already one
        # day, so picking a date here SWITCHES WHICH FILE is loaded (see
        # _on_date_filter_change / _available_history_files), same idea as a file
        # picker rather than a post-process filter like Trạm/Giờ above.
        win._date_filter = tk.StringVar(value=date_key)
        ttk.Label(bar, text="Ngày:").pack(side="left", padx=(12, 2))
        win._date_combo = ttk.Combobox(bar, textvariable=win._date_filter,
                    values=sorted(history_files), state="readonly", width=12)
        win._date_combo.pack(side="left")
        win._date_filter.trace_add("write", lambda *_: self._on_date_filter_change(win))

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
        # Zebra striping — tags live on the widget, so this only needs setting once.
        tree.tag_configure("odd", background="#f3f4f6")
        tree.tag_configure("even", background="#ffffff")

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

        self._refresh_date_filter_options(win)

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

    def _refresh_date_filter_options(self, win):
        """Rebuild the Ngày dropdown's values from the history_*.csv files currently
        on disk (one file = one day, unlike STATIONS/HOURS which are a fixed table).
        Picks up new days written since the window was opened (e.g. a fresh 'Làm
        mới'). Falls back to the most recent date if the current selection's file
        is gone."""
        history_files = self._available_history_files()
        dates = sorted(history_files)
        win._date_combo["values"] = dates
        if win._date_filter.get() not in dates and dates:
            win._date_filter.set(dates[-1])

    def _toggle_viewer_mode(self, win):
        """Switch between Data mode (hides raw) and Raw mode (identity cols + raw)."""
        win._mode = "raw" if win._mode == "data" else "data"
        self._log("ACT", f"Xem CSV — chế độ {'Raw' if win._mode == 'raw' else 'Số liệu'}")
        self._render_viewer(win)

    def _on_station_filter_change(self, win):
        self._log("ACT", f"Lọc trạm: {win._station_filter.get()}")
        self._sync_hour_filter_for_station(win)
        self._render_viewer(win)

    def _on_hour_filter_change(self, win):
        self._log("ACT", f"Lọc giờ: {win._hour_filter.get()}")
        self._render_viewer(win)

    def _on_date_filter_change(self, win):
        """Ngày dropdown = file picker now (each history_YYYYMMDD.csv is one day),
        so changing it loads a different file instead of filtering the loaded one."""
        date_key = win._date_filter.get()
        history_files = self._available_history_files()
        path = history_files.get(date_key)
        if not path or not os.path.isfile(path):
            self._log("ERR", f"Chọn ngày: không có dữ liệu cho {date_key}")
            win._status.config(text=f"Không có dữ liệu ngày {date_key}")
            return
        self._log("ACT", f"Chọn ngày: {date_key}")
        win._path = path
        win.title(os.path.basename(path))
        self._load_csv_into_viewer(win, path)

    def _sync_hour_filter_for_station(self, win):
        """Giờ filter's OWN options depend on the trạm filter: chọn một trạm cụ thể
        khóa giờ về 'Tất cả các giờ' (chỉ có ý nghĩa xem toàn bộ giờ của trạm đó);
        chọn 'Tất cả các trạm' thì ẩn 'Tất cả các giờ' đi, bắt buộc chọn một giờ cụ
        thể (tránh bảng hiện toàn bộ trạm × toàn bộ giờ cùng lúc)."""
        if win._station_filter is None or win._hour_filter is None:
            return
        if win._station_filter.get() == ALL_STATIONS:
            win._hour_combo["values"] = HOURS
            win._hour_combo["state"] = "readonly"
            if win._hour_filter.get() == ALL_HOURS:
                win._hour_filter.set(HOURS[0])
        else:
            win._hour_combo["values"] = [ALL_HOURS]
            win._hour_combo["state"] = "disabled"
            if win._hour_filter.get() != ALL_HOURS:
                win._hour_filter.set(ALL_HOURS)

    # ----- Column sorting --------------------------------------------
    def _apply_sort(self, win):
        """Sort win._data in place by the current win._sort_col/_sort_reverse (if set)."""
        col = win._sort_col
        if not col or col not in win._header:
            return
        idx = win._header.index(col)
        numeric = _is_numeric_viewer_column(col)

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

        header = [c for c in (win._header or []) if c not in ALWAYS_HIDDEN_VIEWER_COLUMNS]
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

        if win._hour_filter is not None and "hour" in header:
            hour = win._hour_filter.get()
            if hour != ALL_HOURS:
                h_idx = header.index("hour")
                data = [r for r in data if h_idx < len(r) and r[h_idx] == hour]

        # No date filter here — win._date_filter now picks WHICH FILE is loaded
        # (see _on_date_filter_change), not a row filter within it.

        if mode == "raw":
            # Just obs_time + raw, to read the original bulletin per station.
            prefer = ["obs_time", "raw"]
            cols = [c for c in prefer if c in header]
        else:
            cols = [c for c in header if c != "raw"]   # data mode: all columns, minus raw
        # ALWAYS_HIDDEN_VIEWER_COLUMNS are dropped in both modes — they stay in the
        # CSV file, just never rendered here (see the constant's docstring above).
        cols = [c for c in cols
                if c not in ALWAYS_HIDDEN_VIEWER_COLUMNS and c not in self.hidden_cols]

        idx = {c: header.index(c) for c in cols}

        tree.delete(*tree.get_children())
        tree["columns"] = cols
        # Width from the ACTUAL DATA, not the header text — a header like
        # "temperature_c" is much longer than any value it holds, so sizing off
        # the header (the old behavior) left short numeric columns wide and sparse.
        # Falls back to the header length only when a column has no data to sample
        # (e.g. cloud_2_* with no station reporting a 2nd layer at all).
        sample_rows = data[:300]
        for c in cols:
            is_sorted = (c == win._sort_col)
            arrow = "" if not is_sorted else (" ▼" if win._sort_reverse else " ▲")
            tree.heading(c, text=c + arrow, command=lambda c=c: self._sort_viewer(win, c))
            if c == "raw":
                tree.column(c, width=560, stretch=True, anchor="w")
            else:
                i = idx[c]
                vals = [len(r[i]) for r in sample_rows if i < len(r) and r[i]]
                longest = max(vals) if vals else len(c)
                w = max(50, min(200, (longest + 2) * 7))
                anchor = "e" if _is_numeric_viewer_column(c) else "w"
                tree.column(c, width=w, stretch=False, anchor=anchor)

        for i, r in enumerate(data):
            tree.insert("", "end", tags=("odd" if i % 2 else "even",),
                        values=[r[idx[c]] if idx[c] < len(r) else "" for c in cols])

        tree.xview_moveto(0)
        win._status.config(text=f"Chế độ: {'Raw' if mode == 'raw' else 'Số liệu'} — "
                                f"{len(data)} dòng × {len(cols)} cột")
        win._toggle_btn.config(text="Xem số liệu" if mode == "raw" else "Xem raw")

    def _open_csv_external(self, path: str):
        """Open the CSV file with its default application (usually Excel on Windows)."""
        self._log("ACT", f"Mở bằng Excel: {os.path.basename(path)}")
        self._report_open(*open_in_editor(path), warn=True)

    def _on_now(self):
        """'Về hiện tại' (Nâng cao frame): force start_date/end_date to today."""
        now = datetime.datetime.now()
        self.v["start_date"].set(now.strftime("%Y-%m-%d"))
        self.v["end_date"].set(now.strftime("%Y-%m-%d"))
        self._log("ACT", f"Về hiện tại: ngày {now:%Y-%m-%d}")

    def _on_toggle_advanced(self):
        """Toggle 'Truy vấn nâng cao': switches query mode (ngày đơn ↔ khoảng ngày),
        pauses/resumes auto-query (mutually exclusive with advanced mode), and
        enables/disables the date-range fields + 'Bắt đầu'/'Về hiện tại'."""
        on = self.v["advanced_mode"].get()
        if on:
            if self.auto_job is not None:
                self.root.after_cancel(self.auto_job)
                self.auto_job = None
            self.auto_next_run = None
        else:
            self._schedule_auto_tick()   # resume per the settings already in config/mã nguồn
        self._refresh_advanced_controls_state()
        self._refresh_info_panel()
        self._log("ACT", f"Truy vấn nâng cao: {'Bật' if on else 'Tắt'}")

    def _refresh_advanced_controls_state(self):
        """Ngày bắt đầu/kết thúc + 'Về hiện tại' theo đúng trạng thái tick của
        'Truy vấn nâng cao'; 'Bắt đầu' còn bị khóa thêm khi đang có tác vụ chạy."""
        on = self.v["advanced_mode"].get()
        field_state = "normal" if on else "disabled"
        self.start_date_entry.config(state=field_state)
        self.end_date_entry.config(state=field_state)
        self.now_btn.config(state=field_state)
        self.start_btn.config(state="normal" if (on and not self._run_in_progress) else "disabled")

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
            self.info["auto_status"].set("Tạm dừng trong truy vấn nâng cao")
            return

        if self._auto_effective_minutes() <= 0:
            self.info["auto_status"].set("Tắt")
        else:
            v, unit = self.v["auto_value"].get(), self.v["auto_unit"].get()
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
        return v * 60 if self.v["auto_unit"].get() == "Hours" else v

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

    def _on_toggle_delete(self):
        state = "Bật" if self.v["delete_on_exit"].get() else "Tắt"
        self._log("ACT", f"Tùy chọn 'Xóa file tải về sau khi xong': {state}")

    def _report_open(self, ok: bool, info: str, what: str = None, warn: bool = False):
        """Log the result of an open_folder()/open_in_editor() call in the standard
        'Đã mở <what>: ...' / 'Không mở được <what>: ...' shape; optionally also
        pop a warning dialog on failure."""
        suffix = f" {what}" if what else ""
        if ok:
            self._log("OK", f"Đã mở{suffix}: {info}")
        else:
            self._log("ERR", f"Không mở được{suffix}: {info}")
            if warn:
                messagebox.showwarning("Không mở được", info)

    def _on_open_folder(self):
        self._log("ACT", "Mở thư mục CSV")
        self._report_open(*open_folder(self.last_output_dir), "thư mục CSV")

    def _on_open_data(self):
        self._log("ACT", "Mở thư mục data")
        os.makedirs(core.TEMP_DL_DIR, exist_ok=True)   # create it upfront if never run before
        self._report_open(*open_folder(core.TEMP_DL_DIR), "thư mục data")

    def _read_form_values(self) -> dict:
        """Current form values (as strings/bools) for writing out to config.ini."""
        return {
            "ftp_host": self.v["ftp_host"].get().strip(),
            "ftp_user": self.v["ftp_user"].get().strip(),
            "ftp_pass": self.v["ftp_pass"].get(),
            "remote_dir": self.v["remote_dir"].get().strip(),
            "output_dir": self.v["output_dir"].get().strip(),
            "station_code": core.CONFIG.get("station_code", ""),
            "end_hour": 23,
            "delete_on_exit": self.v["delete_on_exit"].get(),
            "auto_query_value": self._auto_effective_value(),
            "auto_query_unit": "hours" if self.v["auto_unit"].get() == "Hours" else "minutes",
            "auto_query_on_startup": self.v["auto_on_startup"].get(),
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

        Always sets start_date/end_date — core.download_files() takes the fast
        single-day path when they're equal. Normal mode: always "today", no date
        field to read. Advanced mode (self.v["advanced_mode"]): reads them from
        the Nâng cao form instead.
        """
        cfg = {
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
        """Toggle 'Làm mới' and 'Truy vấn nâng cao' — locked while a run is in
        progress (advanced mode can't change the query mid-run). 'Bắt đầu' follows
        via _refresh_advanced_controls_state, which also re-applies the checkbox's
        own on/off state to the date fields."""
        self._run_in_progress = not enabled
        state = "normal" if enabled else "disabled"
        self.opt_menu.entryconfig("Làm mới", state=state)
        self.adv_check.config(state=state)
        self._refresh_advanced_controls_state()

    # -----------------------------------------------------------------
    def _on_run(self):
        self._log("ACT", "Bắt đầu truy vấn")
        if self.worker and self.worker.is_alive():
            self._log("WARN", "Bỏ qua: một tác vụ đang chạy")
            return
        try:
            cfg = self._build_cfg()
            if not cfg["ftp_host"]:
                raise ValueError("Chưa nhập FTP host")
        except ValueError as e:
            self._log("ERR", f"Nhập sai: {e}")
            messagebox.showerror("Nhập sai", str(e))
            return

        self._divider()
        if cfg["start_date"].date() == cfg["end_date"].date():
            self._log("ACT", f"Bắt đầu: ngày {cfg['start_date']:%Y-%m-%d} (00h–23h)")
        else:
            days = (cfg["end_date"].date() - cfg["start_date"].date()).days + 1
            self._log("ACT", f"Bắt đầu: {cfg['start_date']:%Y-%m-%d} → "
                             f"{cfg['end_date']:%Y-%m-%d} ({days} ngày)")
        self.last_cfg = cfg
        self._set_actions_enabled(False)
        self.opt_menu.entryconfig("Mở thư mục CSV", state="disabled")
        self.status.config(text="Đang chạy...")

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
        if self.last_output_dir and os.path.isdir(self.last_output_dir):
            self.opt_menu.entryconfig("Mở thư mục CSV", state="normal")

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
