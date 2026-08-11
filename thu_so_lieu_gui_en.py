"""
thu_so_lieu_gui_en.py
======================
English-language variant of thu_so_lieu_gui.py — same layout, same behavior,
only the on-screen text is English. Wraps thu_so_lieu_core_en (imported as
`core`), the English-language sibling of thu_so_lieu_core.py.

Run:  python thu_so_lieu_gui_en.py [config.ini path]
Requires thu_so_lieu_core_en.py in the same folder.

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

import thu_so_lieu_core_en as core


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
# Feeds the station filter dropdown in the "View history" viewer (history.csv
# holds every station already — the dropdown just filters rows client-side, it
# no longer drives what gets downloaded/decoded). Add/remove a station by
# editing this table. Station names are place names — kept in Vietnamese
# regardless of UI language, the same way "Tokyo" stays "Tokyo" in English.
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

ALL_STATIONS = "All stations"   # station-filter dropdown option that disables filtering


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
        return False, "no output folder yet (run successfully at least once)"
    path = os.path.abspath(path)                      # './x' → absolute (Windows dislikes relative paths)
    if not os.path.isdir(path):
        return False, f"folder does not exist: {path}"
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
        return False, "no file path given"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, f"file does not exist: {path}"
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
        "# config.ini for thu_so_lieu_core_en.py — edit values then save.",
        "# Delete any line to use the default in code.",
        "[thu_so_lieu]",
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
        self.auto_next_run = None   # datetime of the next scheduled auto-query tick (None = off)
        self.last_result = None     # result dict from the last completed run (for the info panel)
        self.last_cfg = None        # cfg dict from the last _on_run (carries the queried date)
        self.last_updated_at = None # datetime the last run finished (success or not)
        self._dialogs = {}          # keeps references to open dialogs (avoids reopening duplicates)

        # Load the external config (if any) BEFORE prefilling the form
        self.cfg_path, self.cfg_overrides = core.apply_config_file(config_path)

        # Columns hidden in the CSV viewer — shared across all viewer windows
        # (latest/history have the same schema); loaded from config, saved back on change.
        self.hidden_cols = set(core.CONFIG.get("viewer_hidden_columns", []))

        root.title("Weather Observation Data Collector")
        root.minsize(200, 150)   # temporary low floor, replaced below once real content is laid out

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
            "show_log":    tk.BooleanVar(value=False),   # log frame hidden by default
            "auto_value":  tk.StringVar(value=str(d.get("auto_query_value", 15))),
            "auto_unit":   tk.StringVar(value="Hours" if d.get("auto_query_unit", "minutes") == "hours" else "Minutes"),
        }

        # Read-only labels in the info panel — recomputed by
        # _refresh_info_panel() whenever the underlying state changes.
        self.info = {
            "latest_file":   tk.StringVar(value="—"),
            "csv_result":    tk.StringVar(value="—"),
            "data_status":   tk.StringVar(value="No data yet"),
            "auto_status":   tk.StringVar(value="—"),
            "missing":       tk.StringVar(value="—"),
        }

        self._build_menu()
        self._build_ui()
        self._fit_window_to_content()
        # Floor = the natural size with the log hidden (its default state) — small
        # enough to fit just the info box + the 5 buttons, but never smaller.
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())
        self.root.after(100, self._poll)
        self._log("INFO", "Startup complete — ready. Fill in the settings, then click 'Query'.")
        if self.cfg_overrides:
            self._log("OK", f"Loaded {len(self.cfg_overrides)} settings from config: {self.cfg_path}")
        else:
            self._log("INFO", f"Config not found ({self.cfg_path}) — using defaults in code.")
        self._schedule_auto_tick()   # also refreshes the info panel's auto-query status

    # -----------------------------------------------------------------
    def _build_menu(self):
        """Menu bar: File / Help only — Actions and View were removed (every command they
        held mirrors a button/checkbox already on the main screen)."""
        menubar = tk.Menu(self.root)

        # --- File --- (Settings opens the combined Connection / Paths / Auto-query
        # dialog, with config.ini actions at its bottom)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Settings", command=self._open_settings_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Open CSV folder", command=self._on_open_folder)
        file_menu.add_command(label="Open download folder", command=self._on_open_data)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_exit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.file_menu = file_menu               # lets us enable/disable "Open CSV folder" by state
        # Not run yet → no CSV folder to open
        self.file_menu.entryconfig("Open CSV folder", state="disabled")

        # --- Help ---
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Guide", command=self._on_help_usage)
        help_menu.add_command(label="About", command=self._on_help_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # -----------------------------------------------------------------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        # --- Advanced: start/end date — hidden by default, only shown when the
        # "Advanced query" checkbox at the bottom is ticked (replaces the old
        # date field). Normal mode has NO date field — it always queries "today".
        self.adv_frame = ttk.LabelFrame(frm, text="Advanced", padding=8)
        ttk.Label(self.adv_frame, text="Start date").pack(side="left")
        ttk.Entry(self.adv_frame, textvariable=self.v["start_date"], width=12).pack(
            side="left", padx=(4, 10))
        ttk.Label(self.adv_frame, text="End date").pack(side="left")
        ttk.Entry(self.adv_frame, textvariable=self.v["end_date"], width=12).pack(
            side="left", padx=(4, 10))
        ttk.Button(self.adv_frame, text="Reset to now", command=self._on_now).pack(side="left")

        # --- Bottom row: read-only info panel (left) + action buttons stacked (right) ---
        top = ttk.Frame(frm)
        top.pack(fill="x", pady=(8, 0))
        self.top_frame = top   # anchor: adv_frame is packed(before=self.top_frame) when shown

        # --- Info --- (read-only status; recomputed by _refresh_info_panel)
        q_box = ttk.LabelFrame(top, text="Info", padding=8)
        q_box.pack(side="left", fill="both", expand=True)
        ttk.Label(q_box, text="Server:").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, textvariable=self.v["ftp_host"]).grid(row=0, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, text="Latest file:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, textvariable=self.info["latest_file"]).grid(row=1, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, text="CSV export result:").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, textvariable=self.info["csv_result"]).grid(row=2, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, text="Data:").grid(row=3, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, textvariable=self.info["data_status"]).grid(row=3, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, text="Auto-query:").grid(row=4, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, textvariable=self.info["auto_status"]).grid(row=4, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, text="Files missing on server:").grid(row=5, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(q_box, textvariable=self.info["missing"]).grid(row=5, column=1, sticky="w", padx=6, pady=2)
        q_box.columnconfigure(1, weight=1)

        # --- Actions: stacked vertically so they line up as one column ---
        btn_col = ttk.Frame(top)
        btn_col.pack(side="left", fill="y", padx=(8, 0))
        self.run_btn = ttk.Button(btn_col, text="Query", command=self._on_run)
        self.run_btn.pack(fill="x")
        ttk.Button(btn_col, text="View latest",
                   command=lambda: self._open_csv_viewer("latest.csv", "latest.csv")
                   ).pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="View history",
                   command=lambda: self._open_csv_viewer("history.csv", "history.csv",
                                                         with_station_filter=True)
                   ).pack(fill="x", pady=(4, 0))
        ttk.Button(btn_col, text="Settings",
                   command=self._open_settings_dialog).pack(fill="x", pady=(4, 0))

        # --- Progress bar (spans the window's full width) ---
        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.pack(fill="x", pady=(10, 0))

        # --- Status bar at the BOTTOM: "Advanced query" toggle at bottom-left,
        # status indicator at bottom-right ---
        statusbar = ttk.Frame(frm)
        statusbar.pack(side="bottom", fill="x", pady=(6, 0))
        self.adv_check = ttk.Checkbutton(statusbar, text="Advanced query",
                                         variable=self.v["advanced_mode"],
                                         command=self._on_toggle_advanced)
        self.adv_check.pack(side="left")
        ttk.Checkbutton(statusbar, text="Show log", variable=self.v["show_log"],
                        command=self._on_toggle_log).pack(side="left", padx=(10, 0))
        self.status = ttk.Label(statusbar, text="Ready", anchor="e")
        self.status.pack(side="right")

        # --- Log (fills the middle, sits above the status bar) ---
        # Frame built regardless, only packed/shown if "Show log" is on
        # (default off) — the Text widget itself still receives every log line,
        # so nothing is lost while hidden.
        self.log_box = ttk.LabelFrame(frm, text="Log", padding=6)
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
        """Combined settings dialog: Connection / Paths / Auto-query, plus
        config.ini actions (create-or-edit at bottom-left, explicit save at bottom-right)."""
        self._log("ACT", "Opened the Settings dialog")
        win = self._make_dialog("settings", "Settings")
        if win is None:
            return
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        conn_box = ttk.LabelFrame(frm, text="Connection", padding=8)
        conn_box.pack(fill="x")
        self._row(conn_box, 0, "Server",   self.v["ftp_host"])
        self._row(conn_box, 1, "Username", self.v["ftp_user"])
        self._row(conn_box, 2, "Password", self.v["ftp_pass"], show="*")
        conn_box.columnconfigure(1, weight=1)

        path_box = ttk.LabelFrame(frm, text="Paths", padding=8)
        path_box.pack(fill="x", pady=(8, 0))
        self._row(path_box, 0, "Server folder",     self.v["remote_dir"])
        self._row(path_box, 1, "CSV output folder", self.v["output_dir"])
        ttk.Button(path_box, text="Browse",
                   command=lambda: self._browse_output(parent=win)).grid(row=1, column=2, padx=4)
        ttk.Checkbutton(path_box, text="Delete downloaded files when done",
                        variable=self.v["delete_on_exit"],
                        command=self._on_toggle_delete).grid(
                        row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        path_box.columnconfigure(1, weight=1)

        # Auto-query: re-runs the pipeline on a timer (system time → "Reset to now" →
        # "Query"). 0 = auto-query off.
        auto_box = ttk.LabelFrame(frm, text="Auto-query", padding=8)
        auto_box.pack(fill="x", pady=(8, 0))
        auto_entry = ttk.Entry(auto_box, textvariable=self.v["auto_value"], width=6)
        auto_entry.grid(row=0, column=0, padx=(0, 4))
        auto_entry.bind("<FocusOut>", self._on_auto_change)
        auto_entry.bind("<Return>", self._on_auto_change)
        auto_unit = ttk.Combobox(auto_box, textvariable=self.v["auto_unit"],
                                 values=["Minutes", "Hours"], state="readonly", width=8)
        auto_unit.grid(row=0, column=1)
        auto_unit.bind("<<ComboboxSelected>>", self._on_auto_change)
        ttk.Label(auto_box, text="(0 = off)").grid(row=0, column=2, padx=(8, 0))

        btn_bar = ttk.Frame(frm)
        btn_bar.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_bar, text="Create/edit config.ini",
                   command=self._on_edit_config).pack(side="left")
        ttk.Button(btn_bar, text="Save settings",
                   command=self._on_save_settings).pack(side="right")

        win.minsize(420, 0)
        self._center_over_root(win)

    def _on_save_settings(self):
        """Persist every field in the Settings dialog to config.ini in one shot."""
        self._log("ACT", "Save settings")
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
            self._log("OK", f"Settings saved to config: {self.cfg_path}")
        except OSError as e:
            self._log("ERR", f"Could not save settings: {e}")
            messagebox.showerror("Error", f"Could not save settings:\n{e}")
        self._schedule_auto_tick()

    # ----- Help ---------------------------------------------------
    def _on_help_usage(self):
        self._log("ACT", "Opened 'Guide'")
        messagebox.showinfo(
            "Guide",
            "1. Normal mode (default): no date to pick — always queries the\n"
            "   full 00:00-23:00 of TODAY. Click 'Query' to run it manually,\n"
            "   or enable 'Auto-query' in Settings to run it automatically\n"
            "   on a schedule.\n\n"
            "2. Advanced query: check 'Advanced query' in the bottom-left\n"
            "   corner to enter a Start date / End date (downloads every day\n"
            "   in that range); click 'Reset to now' to set both dates back\n"
            "   to today. Turning this on pauses auto-query (the Info panel\n"
            "   shows 'Paused for advanced query'); uncheck it to return to\n"
            "   normal mode — auto-query resumes from the saved settings.\n\n"
            "3. Click 'Query' to download bulletins from FTP and decode them.\n"
            "   Watch progress in the status bar; check 'Show log' (bottom-left\n"
            "   corner) to show/hide the Log panel (off by default).\n\n"
            "4. 'View latest' / 'View history' buttons on the main screen:\n"
            "   • 'View latest' — the most recent bulletin for ALL stations.\n"
            "   • 'View history' — hourly history for ALL stations; use the\n"
            "     'Station' box in the viewer window to filter to a single\n"
            "     station (defaults to station_code in config.ini).\n"
            "     In the viewer, click 'View raw' to check against the\n"
            "     original bulletin.\n\n"
            "5. File menu:\n"
            "   • 'Settings' — opens a dialog with:\n"
            "     - Connection: FTP server/username/password.\n"
            "     - Paths: server folder, CSV output folder, toggle\n"
            "       deleting downloaded files when done.\n"
            "     - Auto-query: re-runs every N minutes/hours (0 = off);\n"
            "       only active in normal mode (each auto-run always uses\n"
            "       today's date).\n"
            "     - 'Create/edit config.ini' — creates it (if missing) then\n"
            "       opens the file for manual editing; also where you\n"
            "       change the default station for the history filter\n"
            "       (station_code).\n"
            "     - 'Save settings' — saves everything above to config.ini\n"
            "       right away so the next run loads it automatically.\n"
            "   • 'Open CSV folder' — view latest.csv / history.csv.\n"
            "   • 'Open download folder' — view the original bulletins\n"
            "     (.txt) that were downloaded.")

    def _on_help_about(self):
        self._log("ACT", "Opened 'About'")
        messagebox.showinfo(
            "About",
            "Weather Observation Data Collector\n\n"
            "Author:\n"
            "  congminh9981 — congminh9981@gmail.com\n"
            "  Claude (Anthropic) — co-author")

    # ----- Exit ------------------------------------------------------
    def _on_exit(self):
        self._log("ACT", "Exiting the program")
        self.root.destroy()

    # ----- CSV viewing ----------------------------------------------------
    def _current_output_dir(self) -> str:
        """Directory holding the CSVs: prefers where the last run wrote to, else the form."""
        if self.last_output_dir:
            return self.last_output_dir
        return os.path.abspath(self.v["output_dir"].get().strip() or core.DEFAULT_OUTPUT_DIR)

    def _open_csv_viewer(self, filename: str, title: str, with_station_filter: bool = False):
        """Open a dedicated window to view a CSV file as a table (read-only)."""
        self._log("ACT", f"Viewing {filename}")
        path = os.path.join(self._current_output_dir(), filename)
        if not os.path.isfile(path):
            self._log("ERR", f"{filename} not found in {self._current_output_dir()} — run Query first")
            messagebox.showwarning(
                "No file yet",
                f"Not found:\n{path}\n\nClick 'Query' first to create the file.")
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
        win._toggle_btn = ttk.Button(bar, text="View raw",
                                     command=lambda: self._toggle_viewer_mode(win))
        win._toggle_btn.pack(side="left")
        ttk.Button(bar, text="Refresh",
                   command=lambda: self._load_csv_into_viewer(win, path)).pack(side="left", padx=6)
        ttk.Button(bar, text="Open in Excel",
                   command=lambda: self._open_csv_external(path)).pack(side="left")
        ttk.Button(bar, text="Columns",
                   command=lambda: self._open_column_picker(win)).pack(side="left", padx=6)

        # Station filter — post-process filter over history.csv (which already holds
        # every station); default to the station_code configured in config.ini.
        if with_station_filter:
            default_code = (core.CONFIG.get("station_code") or "").strip()
            default_name = STATIONS.get(default_code, ALL_STATIONS)
            win._station_filter = tk.StringVar(value=default_name)
            ttk.Label(bar, text="Station:").pack(side="left", padx=(12, 2))
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
            win._status.config(text=f"Error reading file: {e}")
            self._log("ERR", f"Could not read {os.path.basename(path)}: {e}")
            return

        if not rows:
            win._header, win._data = [], []
            win._tree.delete(*win._tree.get_children())
            win._tree["columns"] = ()
            win._status.config(text="Empty file")
            return

        win._header, win._data = rows[0], rows[1:]
        self._apply_sort(win)         # keep the current sort (if any) after reloading
        self._render_viewer(win)
        self._log("OK", f"Displayed {os.path.basename(path)} ({len(win._data)} rows)")

    def _toggle_viewer_mode(self, win):
        """Switch between Data mode (hides raw) and Raw mode (identity cols + raw)."""
        win._mode = "raw" if win._mode == "data" else "data"
        self._log("ACT", f"Viewing CSV — {'raw' if win._mode == 'raw' else 'data'} mode")
        self._render_viewer(win)

    def _on_station_filter_change(self, win):
        self._log("ACT", f"Station filter: {win._station_filter.get()}")
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
        self._log("ACT", f"Sorted by '{col}' ({'descending' if win._sort_reverse else 'ascending'})")
        self._apply_sort(win)
        self._render_viewer(win)

    # ----- Column visibility --------------------------------------------
    def _open_column_picker(self, win):
        """Open a checkbox dialog to pick visible columns (shared across all viewer windows)."""
        self._log("ACT", "Opened 'Columns'")
        dlg = self._make_dialog("columns", "Choose visible columns")
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
        ttk.Button(btns, text="Close", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Apply",
                   command=lambda: self._apply_column_selection(col_vars)).pack(
                   side="right", padx=6)

        dlg.minsize(360, 0)
        self._center_over_root(dlg)

    def _apply_column_selection(self, col_vars: dict):
        """Read checkbox states → update self.hidden_cols, redraw every open viewer, save to config."""
        self.hidden_cols = {c for c, v in col_vars.items() if not v.get()}
        self._log("ACT", f"Applied column visibility — {len(self.hidden_cols)} columns hidden")
        for key, w in self._dialogs.items():
            if key.startswith("view_") and w.winfo_exists():
                self._render_viewer(w)
        self._save_hidden_columns_to_config()

    def _save_hidden_columns_to_config(self):
        value = ",".join(sorted(self.hidden_cols))
        try:
            core.update_ini_key(self.cfg_path, core.CONFIG_SECTION, "viewer_hidden_columns", value)
            core.CONFIG["viewer_hidden_columns"] = sorted(self.hidden_cols)
            self._log("OK", f"Column selection saved to config: {self.cfg_path}")
        except OSError as e:
            self._log("ERR", f"Could not save column selection to config: {e}")

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
        win._status.config(text=f"Mode: {'Raw' if mode == 'raw' else 'Data'} — "
                                f"{len(data)} rows × {len(cols)} columns")
        win._toggle_btn.config(text="View data" if mode == "raw" else "View raw")

    def _open_csv_external(self, path: str):
        """Open the CSV file with its default application (usually Excel on Windows)."""
        self._log("ACT", f"Opening in Excel: {os.path.basename(path)}")
        ok, info = open_in_editor(path)
        if ok:
            self._log("OK", f"Opened: {info}")
        else:
            self._log("ERR", f"Could not open: {info}")
            messagebox.showwarning("Could not open", info)

    def _on_now(self):
        """'Reset to now' (Advanced frame): force start_date/end_date to today."""
        now = datetime.datetime.now()
        self.v["start_date"].set(now.strftime("%Y-%m-%d"))
        self.v["end_date"].set(now.strftime("%Y-%m-%d"))
        self._log("ACT", f"Reset to now: {now:%Y-%m-%d}")

    def _on_toggle_advanced(self):
        """Toggle 'Advanced query': shows/hides the Advanced frame (start/end date +
        'Reset to now') where the old date field used to sit, and pauses/resumes
        auto-query — advanced mode and the auto-query timer are mutually exclusive."""
        on = self.v["advanced_mode"].get()
        if on:
            self.adv_frame.pack(fill="x", before=self.top_frame)
            if self.auto_job is not None:
                self.root.after_cancel(self.auto_job)
                self.auto_job = None
            self.auto_next_run = None
        else:
            self.adv_frame.pack_forget()
            self._schedule_auto_tick()   # resume per the settings already in config/code
        self._fit_window_to_content()
        self._refresh_info_panel()
        self._log("ACT", f"Advanced query: {'On' if on else 'Off'}")

    # ----- Info panel --------------------------------------------------
    def _refresh_info_panel(self):
        """Recompute every label in the info panel from current state (last run result,
        auto-query schedule). Cheap — just StringVar.set() calls — safe to call often."""
        result = self.last_result or {}

        self.info["latest_file"].set(result.get("latest_file") or "—")

        if self.last_result is not None:
            lr = result.get("latest_records", 0)
            hr = result.get("history_records", 0)
            self.info["csv_result"].set(f"{lr} stations (latest.csv) · {hr} records (history.csv)")
            missing = len(result.get("missing") or [])
            self.info["missing"].set("None missing" if missing == 0 else f"{missing} files")
        else:
            self.info["csv_result"].set("—")
            self.info["missing"].set("—")

        if self.last_cfg and self.last_updated_at:
            if "start_date" in self.last_cfg:
                rng = f"{self.last_cfg['start_date']:%Y-%m-%d} → {self.last_cfg['end_date']:%Y-%m-%d}"
            else:
                rng = f"Date {self.last_cfg['date']:%Y-%m-%d}"
            self.info["data_status"].set(f"{rng} — updated at {self.last_updated_at:%H:%M:%S}")
        else:
            self.info["data_status"].set("No data yet")

        if self.v["advanced_mode"].get():
            self.info["auto_status"].set("Paused for advanced query")
            return

        minutes = self._auto_effective_minutes()
        if minutes <= 0:
            self.info["auto_status"].set("Off")
        elif self.auto_next_run:
            v, unit = self.v["auto_value"].get(), self.v["auto_unit"].get()
            self.info["auto_status"].set(
                f"On — every {v} {unit} (next: {self.auto_next_run:%H:%M:%S})")
        else:
            v, unit = self.v["auto_value"].get(), self.v["auto_unit"].get()
            self.info["auto_status"].set(f"On — every {v} {unit}")

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
            self._log("SKIP", "Auto-query: skipped, a task is already running")
        else:
            self._log("ACT", "Auto-query: running query")
            self._on_run()
        self._schedule_auto_tick()

    def _on_auto_change(self, event=None):
        """Entry/dropdown changed: normalize the value and reschedule the timer right away
        (takes effect immediately); persisting to config.ini happens via 'Save settings'."""
        v = self._auto_effective_value()
        self.v["auto_value"].set(str(v))
        unit = self.v["auto_unit"].get()
        state = "off" if v == 0 else f"every {v} {unit.lower()}"
        self._log("ACT", f"'Auto-query' option: {state}")
        self._schedule_auto_tick()

    def _auto_effective_value(self) -> int:
        try:
            return max(int(self.v["auto_value"].get().strip()), 0)
        except ValueError:
            return 0

    def _on_toggle_delete(self):
        state = "On" if self.v["delete_on_exit"].get() else "Off"
        self._log("ACT", f"'Delete downloaded files when done' option: {state}")

    def _on_toggle_log(self):
        show = self.v["show_log"].get()
        if show:
            self.log_box.pack(side="top", fill="both", expand=True, pady=(8, 0))
        else:
            self.log_box.pack_forget()
        self._fit_window_to_content()
        self._log("ACT", f"'Show log' option: {'On' if show else 'Off'}")

    def _on_open_folder(self):
        self._log("ACT", "Opening CSV folder")
        ok, info = open_folder(self.last_output_dir)
        if ok:
            self._log("OK", f"Opened CSV folder: {info}")
        else:
            self._log("ERR", f"Could not open CSV folder: {info}")

    def _on_open_data(self):
        self._log("ACT", "Opening download folder")
        os.makedirs(core.TEMP_DL_DIR, exist_ok=True)   # create it upfront if never run before
        ok, info = open_folder(core.TEMP_DL_DIR)
        if ok:
            self._log("OK", f"Opened download folder: {info}")
        else:
            self._log("ERR", f"Could not open download folder: {info}")

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
        }

    def _on_edit_config(self):
        self._log("ACT", "Create/edit config.ini")
        path = os.path.abspath(self.cfg_path)
        created = False
        if not os.path.isfile(path):
            try:
                write_minimal_config(path, self._read_form_values())
                created = True
                self._log("OK", f"Created config from current settings: {path}")
            except Exception as e:
                self._log("ERR", f"Could not create config: {e}")
                messagebox.showerror("Error", f"Could not create config:\n{e}")
                return
        ok, info = open_in_editor(path)
        if ok:
            if created:
                self._log("OK", f"Created & opened config for editing "
                              f"(auto-loaded next run): {info}")
            else:
                self._log("ACT", f"Opened config for editing: {info}")
        else:
            self._log("ERR", f"Could not open config: {info}")
            messagebox.showwarning("Could not open",
                                   f"{info}\n\nYou can open the file manually:\n{path}")

    def _browse_output(self, parent=None):
        self._log("ACT", "Choose CSV output folder")
        p = filedialog.askdirectory(title="Choose CSV output folder",
                                    parent=parent or self.root)
        if p:
            self.v["output_dir"].set(p)
            self._log("OK", f"CSV output folder: {p}")
        else:
            self._log("INFO", "Folder selection cancelled")

    def _build_cfg(self) -> dict:
        """Read the form → cfg dict; local_dir/timeout/retry come from core's fixed constants.

        Normal mode: always queries "today", 00h-23h — no date field to read.
        Advanced mode (self.v["advanced_mode"]): queries start_date..end_date instead.
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
                raise ValueError("Start/end date must be in YYYY-MM-DD format, e.g. 2026-08-10")
            if end < start:
                raise ValueError("End date must be on or after the start date")
            cfg["start_date"] = start
            cfg["end_date"] = end
        else:
            cfg["date"] = datetime.datetime.combine(datetime.date.today(), datetime.time())
            cfg["end_hour"] = 23

        return cfg

    # -----------------------------------------------------------------
    def _on_run(self):
        self._log("ACT", "Clicked 'Query'")
        if self.worker and self.worker.is_alive():
            self._log("WARN", "Skipped: a task is already running")
            return
        try:
            cfg = self._build_cfg()
        except ValueError as e:
            self._log("ERR", f"Invalid input: {e}")
            messagebox.showerror("Invalid input", str(e))
            return
        if not cfg["ftp_host"]:
            self._log("ERR", "Invalid input: FTP server not entered")
            messagebox.showerror("Invalid input", "FTP server not entered")
            return

        self._divider()
        if "start_date" in cfg:
            days = (cfg["end_date"].date() - cfg["start_date"].date()).days + 1
            total = days * 24
            self._log("ACT", f"Starting: {cfg['start_date']:%Y-%m-%d} → "
                             f"{cfg['end_date']:%Y-%m-%d} ({days} days)")
        else:
            total = cfg["end_hour"] + 1
            self._log("ACT", f"Starting: {cfg['date']:%Y-%m-%d} (00:00-23:00)")
        self.last_cfg = cfg
        self.run_btn.config(state="disabled")
        self.adv_check.config(state="disabled")
        self.file_menu.entryconfig("Open CSV folder", state="disabled")
        self.status.config(text="Running...")
        self.bar.config(value=0, maximum=total)

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
                    self.status.config(text=f"Downloading {done}/{total}")
                elif kind == "done":
                    self._on_done(item[1])
                elif kind == "error":
                    self._log("ERR", item[1])
                    self.status.config(text="Error")
                    self.run_btn.config(state="normal")
                    self.adv_check.config(state="normal")
                    messagebox.showerror("Error", item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_done(self, result: dict):
        self.run_btn.config(state="normal")
        self.adv_check.config(state="normal")
        self.last_output_dir = result.get("output_dir")
        if self.last_output_dir and os.path.isdir(self.last_output_dir):
            self.file_menu.entryconfig("Open CSV folder", state="normal")

        self.last_result = result
        self.last_updated_at = datetime.datetime.now()
        self._refresh_info_panel()

        if not result.get("ok"):
            self.status.config(text="No data")
            miss = result.get("missing") or []
            if miss:
                self._log("WARN", f"Missing {len(miss)} files on server")
            return

        self.status.config(text="Done")
        parts = []
        if result.get("latest_csv"):
            parts.append(f"latest.csv ({result['latest_records']} stations)")
        if result.get("history_csv"):
            parts.append(f"history.csv ({result['history_records']} records)")
        self._log("OK", "Done — exported: " + (", ".join(parts) if parts else "(none)"))


def main():
    # Allows: python thu_so_lieu_gui_en.py [config_ini_path]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    App(root, config_path=config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
