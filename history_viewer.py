"""
history_viewer.py
====================
The "Xem số liệu" window: load a history_YYYYMMDD.csv into a Treeview, filter
by trạm/giờ/ngày, sort by column, toggle raw/data mode, and pick visible columns.

HistoryViewer is a standalone class (not a mixin) — it takes the App instance
in its constructor and reaches back into it (`self.app....`) for the handful
of things it needs: the root window, the shared log/dialog-registry helpers,
and the output-dir/config state. gui.py creates ONE HistoryViewer per App and
keeps it around, so its own state (hidden_cols, the open viewer Toplevel...)
persists across "Xem số liệu" clicks.
"""

import csv
import os

import tkinter as tk
from tkinter import ttk, messagebox

import config
from gui_common import (
    STATIONS, STATION_NAMES, NAME_TO_CODE, ALL_STATIONS,
    HOURS, ALL_HOURS, HISTORY_CSV_RE, ALWAYS_HIDDEN_VIEWER_COLUMNS,
    _is_numeric_viewer_column, open_in_editor, report_open,
)


class HistoryViewer:
    def __init__(self, app):
        self.app = app
        # Columns hidden in the CSV viewer — shared across all viewer windows
        # (every history_*.csv has the same schema); loaded from config, saved back on change.
        self.hidden_cols = set(config.CONFIG.get("viewer_hidden_columns", []))

    # ----- Entry points ---------------------------------------------------
    def open_latest(self):
        """'Xem số liệu' — opens the history viewer showing the MOST RECENT day
        available on disk. core.export_history_by_date() writes one
        history_YYYYMMDD.csv per day, so a multi-day advanced query leaves several
        files behind — the 'Ngày' dropdown inside the viewer switches between them."""
        history_files = self._available_history_files()
        if not history_files:
            self.app._log("WARN", "Xem số liệu: chưa có file lịch sử nào — hãy 'Làm mới' trước")
            messagebox.showwarning("Chưa có dữ liệu",
                                   "Chưa có file lịch sử nào.\n\nHãy bấm 'Làm mới' để tạo file trước.")
            return
        self.show_date(max(history_files))

    def show_date(self, date_key: str):
        """Open the (single, shared) history viewer window on history_YYYYMMDD.csv
        for `date_key`, or switch its content to that date if it's already open."""
        history_files = self._available_history_files()
        path = history_files.get(date_key)
        filename = f"history_{date_key.replace('-', '')}.csv"
        self.app._log("ACT", f"Xem {filename}")
        if not path or not os.path.isfile(path):
            self.app._log("ERR", f"Chưa có {filename} trong {self._current_output_dir()} — hãy Làm mới trước")
            messagebox.showwarning(
                "Chưa có file",
                f"Không có dữ liệu ngày {date_key}.\n\nHãy bấm 'Làm mới' để tạo file trước.")
            return

        key = "view_history"
        existing = self.app._dialogs.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify(); existing.lift(); existing.focus_set()
            existing.title(filename)
            existing._path = path
            existing._date_filter.set(date_key)   # triggers _on_date_filter_change → reloads
            return

        win = tk.Toplevel(self.app.root)
        win.title(filename)
        win.transient(self.app.root)
        win.geometry("1040x480")
        win.minsize(480, 240)
        self.app._dialogs[key] = win
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
        default_code = (config.CONFIG.get("station_code") or "").strip()
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

        self.app._center_over_root(win)
        self._load_csv_into_viewer(win, path)

    # ----- File discovery ---------------------------------------------------
    def _current_output_dir(self) -> str:
        """Directory holding the CSVs: prefers where the last run wrote to, else the form."""
        if self.app.last_output_dir:
            return self.app.last_output_dir
        return os.path.abspath(self.app.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR)

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

    # ----- Loading / rendering ----------------------------------------------
    def _load_csv_into_viewer(self, win, path: str):
        """Read the CSV into the viewer window's memory, then draw it in the current mode."""
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except OSError as e:
            win._status.config(text=f"Lỗi đọc file: {e}")
            self.app._log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
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
        self.app._log("OK", f"Đã hiển thị {os.path.basename(path)} ({len(win._data)} dòng)")

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
        self.app._log("ACT", f"Xem CSV — chế độ {'Raw' if win._mode == 'raw' else 'Số liệu'}")
        self._render_viewer(win)

    def _open_csv_external(self, path: str):
        """Open the CSV file with its default application (usually Excel on Windows)."""
        self.app._log("ACT", f"Mở bằng Excel: {os.path.basename(path)}")
        report_open(self.app._log, *open_in_editor(path), warn=True)

    def _on_station_filter_change(self, win):
        self.app._log("ACT", f"Lọc trạm: {win._station_filter.get()}")
        self._sync_hour_filter_for_station(win)
        self._render_viewer(win)

    def _on_hour_filter_change(self, win):
        self.app._log("ACT", f"Lọc giờ: {win._hour_filter.get()}")
        self._render_viewer(win)

    def _on_date_filter_change(self, win):
        """Ngày dropdown = file picker now (each history_YYYYMMDD.csv is one day),
        so changing it loads a different file instead of filtering the loaded one."""
        date_key = win._date_filter.get()
        history_files = self._available_history_files()
        path = history_files.get(date_key)
        if not path or not os.path.isfile(path):
            self.app._log("ERR", f"Chọn ngày: không có dữ liệu cho {date_key}")
            win._status.config(text=f"Không có dữ liệu ngày {date_key}")
            return
        self.app._log("ACT", f"Chọn ngày: {date_key}")
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
        self.app._log("ACT", f"Sắp xếp theo '{col}' ({'giảm dần' if win._sort_reverse else 'tăng dần'})")
        self._apply_sort(win)
        self._render_viewer(win)

    # ----- Column visibility --------------------------------------------
    def _open_column_picker(self, win):
        """Open a checkbox dialog to pick visible columns (shared across all viewer windows)."""
        self.app._log("ACT", "Mở hộp thoại Chọn cột hiển thị")
        dlg = self.app._make_dialog("columns", "Chọn cột hiển thị")
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
        self.app._center_over_root(dlg)

    def _apply_column_selection(self, col_vars: dict):
        """Read checkbox states → update self.hidden_cols, redraw every open viewer, save to config."""
        self.hidden_cols = {c for c, v in col_vars.items() if not v.get()}
        self.app._log("ACT", f"Áp dụng hiển thị cột — ẩn {len(self.hidden_cols)} cột")
        for key, w in self.app._dialogs.items():
            if key.startswith("view_") and w.winfo_exists():
                self._render_viewer(w)
        self._save_hidden_columns_to_config()

    def _save_hidden_columns_to_config(self):
        value = ",".join(sorted(self.hidden_cols))
        try:
            config.update_ini_key(self.app.cfg_path, config.CONFIG_SECTION, "viewer_hidden_columns", value)
            config.CONFIG["viewer_hidden_columns"] = sorted(self.hidden_cols)
            self.app._log("OK", f"Đã lưu lựa chọn cột vào config: {self.app.cfg_path}")
        except OSError as e:
            self.app._log("ERR", f"Không lưu được lựa chọn cột vào config: {e}")

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
