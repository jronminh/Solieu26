"""
viewer.py
====================
The "Số liệu" tab: load a history_YYYYMMDD.csv into a Treeview, filter by
trạm/giờ/ngày, sort by column, toggle raw/data mode, and pick visible columns.

Reaches into the App instance (see main.py) for the root window, the shared
log/dialog-registry helpers, and the output-dir/config state; main.py keeps
one HistoryViewer per App, so hidden_cols and every widget built here persist
for the app's whole lifetime (the tab is built once, not reopened).
"""

import csv
import os

import tkinter as tk
from tkinter import ttk, messagebox

from utils import config_utils as config
from common import (
    STATIONS, STATION_NAMES, NAME_TO_CODE, ALL_STATIONS,
    HOURS, ALL_HOURS, HISTORY_CSV_RE, ALWAYS_HIDDEN_VIEWER_COLUMNS,
    _is_numeric_viewer_column, make_dialog, center_over_root,
)
from utils.ini_utils import update_ini_key


class HistoryViewer:
    def __init__(self, app):
        self.app = app
        # Columns hidden in the CSV viewer, loaded from config, saved back on change.
        # station_code/lat/lon default to hidden (same as the old hard-hidden
        # behavior) until the user explicitly saves a selection via "Thiết
        # lập...", distinguished by whether config.ini actually HAD the key
        # (app.cfg_overrides) rather than by config.CONFIG's own default ([]),
        # which can't tell "never saved" apart from "saved as empty".
        if "viewer_hidden_columns" in app.cfg_overrides:
            self.hidden_cols = set(config.CONFIG.get("viewer_hidden_columns", []))
        else:
            self.hidden_cols = {"station_code", "lat", "lon"}

        self._path = None
        self._mode = "data"          # "data" (hides raw) | "raw" (identity cols + raw only)
        self._header, self._data = [], []
        self._sort_col, self._sort_reverse = None, False

    # ----- Tab construction ------------------------------------------------
    def build(self, parent):
        """Build the whole tab UI once into `parent`, then load the most recent
        history_*.csv on disk (or show the empty state if none exists yet)."""
        bar = ttk.Frame(parent, padding=(0, 0, 0, 6))
        bar.pack(fill="x")
        self._toggle_btn = ttk.Button(bar, text="Xem raw", command=self._toggle_viewer_mode)
        self._toggle_btn.pack(side="left")
        ttk.Button(bar, text="Thiết lập...", command=self._open_column_picker).pack(side="left", padx=6)

        # Station filter: post-process filter over the loaded day's file (which
        # already holds every station); default to the station_code configured
        # in config.ini.
        default_code = (config.CONFIG.get("station_code") or "").strip()
        default_name = STATIONS.get(default_code, ALL_STATIONS)
        self._station_filter = tk.StringVar(value=default_name)
        ttk.Label(bar, text="Trạm:").pack(side="left", padx=(12, 2))
        ttk.Combobox(bar, textvariable=self._station_filter,
                    values=[ALL_STATIONS] + STATION_NAMES, state="readonly",
                    width=16).pack(side="left")
        self._station_filter.trace_add("write", lambda *_: self._on_station_filter_change())

        # Hour filter: same post-process idea as the station filter above, but over
        # the "hour" column (always present, just hidden from the rendered table).
        # Its own options depend on the station filter: a specific station locks
        # giờ to "Tất cả các giờ" (one station's whole history), while "Tất cả các
        # trạm" hides that option and forces a specific giờ. Otherwise the table
        # would be every station × every hour at once.
        self._hour_filter = tk.StringVar(value=ALL_HOURS)
        ttk.Label(bar, text="Giờ:").pack(side="left", padx=(12, 2))
        self._hour_combo = ttk.Combobox(bar, textvariable=self._hour_filter,
                    values=[ALL_HOURS] + HOURS, state="readonly",
                    width=8)
        self._hour_combo.pack(side="left")
        self._hour_filter.trace_add("write", lambda *_: self._on_hour_filter_change())

        # Date filter is NOT a row filter: each history_YYYYMMDD.csv is already one
        # day, so picking a date here switches WHICH FILE is loaded, same idea as
        # a file picker rather than a post-process filter like Trạm/Giờ above.
        self._date_filter = tk.StringVar()
        ttk.Label(bar, text="Ngày:").pack(side="left", padx=(12, 2))
        self._date_combo = ttk.Combobox(bar, textvariable=self._date_filter,
                    state="readonly", width=12)
        self._date_combo.pack(side="left")
        self._date_filter.trace_add("write", lambda *_: self._on_date_filter_change())

        self._status = ttk.Label(bar, text="")
        self._status.pack(side="right")

        # Shown only when Trạm = "Tất cả các trạm" (see _sync_hour_filter_for_station),
        # explaining why Giờ is then locked to a specific hour.
        self._all_stations_hint = ttk.Label(
            parent, text="Vì đang xem tất cả trạm, phải chọn một giờ cụ thể để tránh bảng quá lớn",
            foreground="#6b7280", padding=(0, 0, 0, 4))

        self._empty_label = ttk.Label(
            parent, foreground="#6b7280", padding=(0, 24), anchor="center",
            text="Chưa có dữ liệu. Hãy sang tab 'Tải số liệu theo khoảng' và bấm 'Bắt đầu' trước.")

        tf = ttk.Frame(parent)
        tree = ttk.Treeview(tf, show="headings")
        # vsb: history files can run to thousands of rows. hsb: raw mode's single
        # column is 560px wide (see width below), often wider than the window.
        vsb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self._tree = tree
        # Zebra striping: tags live on the widget, so this only needs setting once.
        tree.tag_configure("odd", background="#f3f4f6")
        tree.tag_configure("even", background="#ffffff")
        self._table_frame = tf

        self._sync_hour_filter_for_station()
        self.refresh()

    def refresh(self):
        """Rescan disk for history_*.csv files, repopulate the Ngày dropdown, and
        (on the very first call, when nothing is loaded yet) load the newest day.
        Falls back to the empty state when no history_*.csv exists yet."""
        history_files = self._available_history_files()
        dates = sorted(history_files)
        self._date_combo["values"] = dates
        if not dates:
            self._show_empty_state()
            return
        self._show_table_state()
        if self._date_filter.get() not in dates:
            self._date_filter.set(dates[-1])   # triggers _on_date_filter_change -> loads

    def refresh_date_list(self):
        """Repopulate the Ngày dropdown's choices without disturbing what's
        currently loaded (called after a background fetch finishes, so a user
        looking at an older day isn't yanked away to today)."""
        dates = sorted(self._available_history_files())
        self._date_combo["values"] = dates
        if not self._header and dates:
            self.refresh()

    def _show_empty_state(self):
        self._table_frame.pack_forget()
        self._all_stations_hint.pack_forget()
        self._status.config(text="")
        self._empty_label.pack(fill="both", expand=True)

    def _show_table_state(self):
        self._empty_label.pack_forget()
        self._table_frame.pack(fill="both", expand=True)

    # ----- File discovery ---------------------------------------------------
    def _current_output_dir(self) -> str:
        """Directory holding the CSVs: prefers where the last run wrote to, else the form."""
        if self.app.runner.last_output_dir:
            return self.app.runner.last_output_dir
        return os.path.abspath(self.app.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR)

    def _available_history_files(self) -> dict:
        """Scan the current output dir for history_YYYYMMDD.csv files (one per
        day, written by pipeline.decode_files.export_history_by_date). Returns {"YYYY-MM-DD": path},
        sorted by nothing in particular; callers sort the keys as needed."""
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

    # ----- Loading / rendering ----------------------------------------------
    def _load_csv_into_viewer(self, path: str):
        """Read the CSV into memory, then draw it in the current mode."""
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except OSError as e:
            self._status.config(text=f"Lỗi đọc file: {e}")
            self.app._log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
            return

        if not rows:
            self._header, self._data = [], []
            self._tree.delete(*self._tree.get_children())
            self._tree["columns"] = ()
            self._status.config(text="File rỗng")
            return

        self._header, self._data = rows[0], rows[1:]
        self._apply_sort()         # keep the current sort (if any) after reloading
        self._render_viewer()
        self.app._log("OK", f"Đã hiển thị {os.path.basename(path)} ({len(self._data)} dòng)")

    def _toggle_viewer_mode(self):
        """Switch between Data mode (hides raw) and Raw mode (identity cols + raw)."""
        self._mode = "raw" if self._mode == "data" else "data"
        self.app._log("ACT", f"Xem CSV: chế độ {'Raw' if self._mode == 'raw' else 'Số liệu'}")
        self._render_viewer()

    def _on_station_filter_change(self):
        self.app._log("ACT", f"Lọc trạm: {self._station_filter.get()}")
        self._sync_hour_filter_for_station()
        self._render_viewer()

    def _on_hour_filter_change(self):
        self.app._log("ACT", f"Lọc giờ: {self._hour_filter.get()}")
        self._render_viewer()

    def _on_date_filter_change(self):
        """Ngày dropdown = file picker now (each history_YYYYMMDD.csv is one
        day), so changing it loads a different file instead of filtering the
        loaded one."""
        date_key = self._date_filter.get()
        if not date_key:
            return
        history_files = self._available_history_files()
        path = history_files.get(date_key)
        if not path or not os.path.isfile(path):
            self.app._log("ERR", f"Chọn ngày: không có dữ liệu cho {date_key}")
            self._status.config(text=f"Không có dữ liệu ngày {date_key}")
            return
        self.app._log("ACT", f"Chọn ngày: {date_key}")
        self._path = path
        self._load_csv_into_viewer(path)

    def _sync_hour_filter_for_station(self):
        """Giờ filter's OWN options depend on the trạm filter: chọn một trạm cụ thể
        khóa giờ về 'Tất cả các giờ' (chỉ có ý nghĩa xem toàn bộ giờ của trạm đó);
        chọn 'Tất cả các trạm' thì ẩn 'Tất cả các giờ' đi, bắt buộc chọn một giờ cụ
        thể (tránh bảng hiện toàn bộ trạm × toàn bộ giờ cùng lúc)."""
        all_stations = self._station_filter.get() == ALL_STATIONS
        if all_stations:
            self._hour_combo["values"] = HOURS
            self._hour_combo["state"] = "readonly"
            if self._hour_filter.get() == ALL_HOURS:
                self._hour_filter.set(HOURS[0])
        else:
            self._hour_combo["values"] = [ALL_HOURS]
            self._hour_combo["state"] = "disabled"
            if self._hour_filter.get() != ALL_HOURS:
                self._hour_filter.set(ALL_HOURS)

        if all_stations:
            self._all_stations_hint.pack(fill="x", before=self._table_frame)
        else:
            self._all_stations_hint.pack_forget()

    # ----- Column sorting --------------------------------------------
    def _apply_sort(self):
        """Sort self._data in place by the current self._sort_col/_sort_reverse (if set)."""
        col = self._sort_col
        if not col or col not in self._header:
            return
        idx = self._header.index(col)
        numeric = _is_numeric_viewer_column(col)

        def key(row):
            v = row[idx] if idx < len(row) else ""
            if numeric:
                try:
                    return (0, float(v))
                except ValueError:
                    return (1, 0.0)          # empty/non-numeric → sorted last
            return (0, v) if v else (1, "")

        self._data.sort(key=key, reverse=self._sort_reverse)

    def _sort_viewer(self, col):
        """Click a column header: new column → ascending; same column again → reverses."""
        if not self._header or col not in self._header:
            return
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col, self._sort_reverse = col, False
        self.app._log("ACT", f"Sắp xếp theo '{col}' ({'giảm dần' if self._sort_reverse else 'tăng dần'})")
        self._apply_sort()
        self._render_viewer()

    # ----- Column visibility --------------------------------------------
    def _open_column_picker(self):
        """Open a checkbox dialog to pick visible columns."""
        self.app._log("ACT", "Mở hộp thoại Chọn cột hiển thị")
        dlg = make_dialog(self.app.root, self.app._dialogs, "columns", "Chọn cột hiển thị")
        if dlg is None:
            return
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        header = [c for c in (self._header or []) if c not in ALWAYS_HIDDEN_VIEWER_COLUMNS]
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
        center_over_root(self.app.root, dlg)

    def _apply_column_selection(self, col_vars: dict):
        """Read checkbox states → update self.hidden_cols, redraw the table, save to config."""
        self.hidden_cols = {c for c, v in col_vars.items() if not v.get()}
        self.app._log("ACT", f"Áp dụng hiển thị cột, ẩn {len(self.hidden_cols)} cột")
        self._render_viewer()
        self._save_hidden_columns_to_config()

    def _save_hidden_columns_to_config(self):
        value = ",".join(sorted(self.hidden_cols))
        try:
            update_ini_key(self.app.cfg_path, config.CONFIG_SECTION, "viewer_hidden_columns", value)
            config.CONFIG["viewer_hidden_columns"] = sorted(self.hidden_cols)
            self.app._log("OK", f"Đã lưu lựa chọn cột vào config: {self.app.cfg_path}")
        except OSError as e:
            self.app._log("ERR", f"Không lưu được lựa chọn cột vào config: {e}")

    def _render_viewer(self):
        """Rebuild the table from self._mode + self.hidden_cols, using the loaded self._header/_data."""
        tree, header, data, mode = self._tree, self._header, self._data, self._mode
        if not header:
            return

        if self._station_filter is not None and "station_code" in header:
            name = self._station_filter.get()
            if name != ALL_STATIONS:
                code = NAME_TO_CODE.get(name)
                sc_idx = header.index("station_code")
                data = [r for r in data if sc_idx < len(r) and r[sc_idx] == code]

        if self._hour_filter is not None and "hour" in header:
            hour = self._hour_filter.get()
            if hour != ALL_HOURS:
                h_idx = header.index("hour")
                data = [r for r in data if h_idx < len(r) and r[h_idx] == hour]

        # No date filter here: self._date_filter picks WHICH FILE is loaded,
        # not a row filter within it.

        if mode == "raw":
            # Just obs_time + raw, to read the original bulletin per station.
            prefer = ["obs_time", "raw"]
            cols = [c for c in prefer if c in header]
        else:
            cols = [c for c in header if c != "raw"]   # data mode: all columns, minus raw
        # ALWAYS_HIDDEN_VIEWER_COLUMNS are dropped in both modes; they stay in the
        # CSV file, just never rendered here (see the constant's docstring above).
        cols = [c for c in cols
                if c not in ALWAYS_HIDDEN_VIEWER_COLUMNS and c not in self.hidden_cols]

        idx = {c: header.index(c) for c in cols}

        tree.delete(*tree.get_children())
        tree["columns"] = cols
        # Width from the ACTUAL DATA, not the header text: a header like
        # "temperature_c" is much longer than any value it holds, so sizing off
        # the header (the old behavior) left short numeric columns wide and sparse.
        # Falls back to the header length only when a column has no data to sample
        # (e.g. cloud_2_* with no station reporting a 2nd layer at all).
        sample_rows = data[:300]
        for c in cols:
            is_sorted = (c == self._sort_col)
            arrow = "" if not is_sorted else (" ▼" if self._sort_reverse else " ▲")
            tree.heading(c, text=c + arrow, command=lambda c=c: self._sort_viewer(c))
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
        self._status.config(text=f"Chế độ: {'Raw' if mode == 'raw' else 'Số liệu'}, "
                                f"{len(data)} dòng × {len(cols)} cột")
        self._toggle_btn.config(text="Xem số liệu" if mode == "raw" else "Xem raw")
