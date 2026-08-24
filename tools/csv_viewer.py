"""
csv_viewer.py
====================
Standalone Tkinter tool to browse history_YYYYMMDD.csv and score_YYYYMMDD.csv
files without launching the full app (main.py) or its Tkinter App instance.
Mirrors the "Số liệu" and "Xem chấm điểm" tabs (viewer.py, score_viewer.py)
in a single 2-tab window that points at any folder you choose.

Read-only: never runs the fetch/decode/score pipeline, never writes
config.ini. Column-visibility choices live in memory for the session only.

Run: python -m tools.csv_viewer [--dir PATH]
"""

import argparse
import csv
import os
import sys

import tkinter as tk
from tkinter import ttk, filedialog

from common import (
    STATIONS, STATION_NAMES, NAME_TO_CODE, ALL_STATIONS,
    HOURS, ALL_HOURS, HISTORY_CSV_RE, SCORE_CSV_RE, ALWAYS_HIDDEN_VIEWER_COLUMNS,
    _is_numeric_viewer_column, make_dialog, center_over_root,
)
from pipeline.match_score import FIELD_ORDER
from forecast_editor import FIELD_LABELS, bucket_label
from utils import config_utils as config

_LABEL_TO_FIELD = {v: k for k, v in FIELD_LABELS.items()}
_ALL_FIELDS_LABEL = "Tất cả 6 trường"


def _log(level: str, msg: str):
    """print() alone can raise UnicodeEncodeError on a non-UTF-8 Windows
    console (cp1252 can't hold Vietnamese diacritics) - fall back to a
    lossy encode instead of crashing the whole app over a log line."""
    try:
        print(f"[{level}] {msg}")
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(f"[{level}] {msg}".encode(enc, errors="replace").decode(enc, errors="replace"))


# =============================================================================
# HISTORY PANE: adapted from viewer.py::HistoryViewer, minus everything that
# reached into the App instance (output-dir resolution, log widget, config.ini
# persistence of hidden columns).
# =============================================================================

class HistoryPane:
    def __init__(self, root, dialogs, get_dir):
        self._root, self._dialogs, self._get_dir = root, dialogs, get_dir
        self.hidden_cols = {"station_code", "lat", "lon"}
        self._mode = "data"          # "data" (hides raw) | "raw" (identity cols + raw only)
        self._header, self._data = [], []
        self._sort_col, self._sort_reverse = None, False

    def build(self, parent):
        bar = ttk.Frame(parent, padding=(0, 0, 0, 6))
        bar.pack(fill="x")
        self._bar = bar   # anchor for _all_stations_hint's pack(after=...), see below
        self._toggle_btn = ttk.Button(bar, text="Xem raw", command=self._toggle_viewer_mode)
        self._toggle_btn.pack(side="left")
        ttk.Button(bar, text="Thiết lập...", command=self._open_column_picker).pack(side="left", padx=6)

        self._station_filter = tk.StringVar(value=ALL_STATIONS)
        ttk.Label(bar, text="Trạm:").pack(side="left", padx=(12, 2))
        ttk.Combobox(bar, textvariable=self._station_filter,
                    values=[ALL_STATIONS] + STATION_NAMES, state="readonly",
                    width=16).pack(side="left")
        self._station_filter.trace_add("write", lambda *_: self._on_station_filter_change())

        self._hour_filter = tk.StringVar(value=ALL_HOURS)
        ttk.Label(bar, text="Giờ:").pack(side="left", padx=(12, 2))
        self._hour_combo = ttk.Combobox(bar, textvariable=self._hour_filter,
                    values=[ALL_HOURS] + HOURS, state="readonly",
                    width=8)
        self._hour_combo.pack(side="left")
        self._hour_filter.trace_add("write", lambda *_: self._on_hour_filter_change())

        self._date_filter = tk.StringVar()
        ttk.Label(bar, text="Ngày:").pack(side="left", padx=(12, 2))
        self._date_combo = ttk.Combobox(bar, textvariable=self._date_filter,
                    state="readonly", width=12)
        self._date_combo.pack(side="left")
        self._date_filter.trace_add("write", lambda *_: self._on_date_filter_change())

        self._status = ttk.Label(bar, text="")
        self._status.pack(side="right")

        self._all_stations_hint = ttk.Label(
            parent, text="Vì đang xem tất cả trạm, phải chọn một giờ cụ thể để tránh bảng quá lớn",
            foreground="#6b7280", padding=(0, 0, 0, 4))

        self._empty_label = ttk.Label(
            parent, foreground="#6b7280", padding=(0, 24), anchor="center",
            text="Không có file history_*.csv trong thư mục này.")

        tf = ttk.Frame(parent)
        tree = ttk.Treeview(tf, show="headings")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self._tree = tree
        tree.tag_configure("odd", background="#f3f4f6")
        tree.tag_configure("even", background="#ffffff")
        self._table_frame = tf

        self._sync_hour_filter_for_station()
        self.reload()

    def reload(self):
        """Rescan the current folder, repopulate Ngày, and (re)load a file:
        keeps the current selection if it still exists (forcing a re-read, in
        case the file grew), else falls back to the newest date."""
        history_files = self._available_history_files()
        dates = sorted(history_files)
        self._date_combo["values"] = dates
        if not dates:
            self._header, self._data = [], []
            self._show_empty_state()
            return
        self._show_table_state()
        if self._date_filter.get() not in dates:
            self._date_filter.set(dates[-1])   # triggers _on_date_filter_change -> loads
        else:
            self._on_date_filter_change()

    def _show_empty_state(self):
        self._table_frame.pack_forget()
        self._all_stations_hint.pack_forget()
        self._status.config(text="")
        self._empty_label.pack(fill="both", expand=True)

    def _show_table_state(self):
        self._empty_label.pack_forget()
        self._table_frame.pack(fill="both", expand=True)

    # ----- File discovery ---------------------------------------------------
    def _available_history_files(self) -> dict:
        out_dir = self._get_dir()
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
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except OSError as e:
            self._status.config(text=f"Lỗi đọc file: {e}")
            _log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
            return

        if not rows:
            self._header, self._data = [], []
            self._tree.delete(*self._tree.get_children())
            self._tree["columns"] = ()
            self._status.config(text="File rỗng")
            return

        self._header, self._data = rows[0], rows[1:]
        self._apply_sort()
        self._render_viewer()
        _log("OK", f"Đã hiển thị {os.path.basename(path)} ({len(self._data)} dòng)")

    def _toggle_viewer_mode(self):
        self._mode = "raw" if self._mode == "data" else "data"
        _log("ACT", f"Xem CSV: chế độ {'Raw' if self._mode == 'raw' else 'Số liệu'}")
        self._render_viewer()

    def _on_station_filter_change(self):
        _log("ACT", f"Lọc trạm: {self._station_filter.get()}")
        self._sync_hour_filter_for_station()
        self._render_viewer()

    def _on_hour_filter_change(self):
        _log("ACT", f"Lọc giờ: {self._hour_filter.get()}")
        self._render_viewer()

    def _on_date_filter_change(self):
        date_key = self._date_filter.get()
        if not date_key:
            return
        history_files = self._available_history_files()
        path = history_files.get(date_key)
        if not path or not os.path.isfile(path):
            _log("ERR", f"Chọn ngày: không có dữ liệu cho {date_key}")
            self._status.config(text=f"Không có dữ liệu ngày {date_key}")
            return
        _log("ACT", f"Chọn ngày: {date_key}")
        self._load_csv_into_viewer(path)

    def _sync_hour_filter_for_station(self):
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
            # after=self._bar (always packed, unlike _table_frame which may not
            # be packed yet on first call) keeps the hint pinned right under
            # the filter bar regardless of packing order.
            self._all_stations_hint.pack(fill="x", after=self._bar)
        else:
            self._all_stations_hint.pack_forget()

    # ----- Column sorting --------------------------------------------
    def _apply_sort(self):
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
                    return (1, 0.0)
            return (0, v) if v else (1, "")

        self._data.sort(key=key, reverse=self._sort_reverse)

    def _sort_viewer(self, col):
        if not self._header or col not in self._header:
            return
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col, self._sort_reverse = col, False
        _log("ACT", f"Sắp xếp theo '{col}' ({'giảm dần' if self._sort_reverse else 'tăng dần'})")
        self._apply_sort()
        self._render_viewer()

    # ----- Column visibility --------------------------------------------
    def _open_column_picker(self):
        _log("ACT", "Mở hộp thoại Chọn cột hiển thị")
        dlg = make_dialog(self._root, self._dialogs, "columns", "Chọn cột hiển thị")
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
        center_over_root(self._root, dlg)

    def _apply_column_selection(self, col_vars: dict):
        self.hidden_cols = {c for c, v in col_vars.items() if not v.get()}
        _log("ACT", f"Áp dụng hiển thị cột, ẩn {len(self.hidden_cols)} cột")
        self._render_viewer()

    def _render_viewer(self):
        tree, header, data, mode = self._tree, self._header, self._data, self._mode
        if not header:
            return

        if "station_code" in header:
            name = self._station_filter.get()
            if name != ALL_STATIONS:
                code = NAME_TO_CODE.get(name)
                sc_idx = header.index("station_code")
                data = [r for r in data if sc_idx < len(r) and r[sc_idx] == code]

        if "hour" in header:
            hour = self._hour_filter.get()
            if hour != ALL_HOURS:
                h_idx = header.index("hour")
                data = [r for r in data if h_idx < len(r) and r[h_idx] == hour]

        if mode == "raw":
            prefer = ["obs_time", "raw"]
            cols = [c for c in prefer if c in header]
        else:
            cols = [c for c in header if c != "raw"]
        cols = [c for c in cols
                if c not in ALWAYS_HIDDEN_VIEWER_COLUMNS and c not in self.hidden_cols]

        idx = {c: header.index(c) for c in cols}

        tree.delete(*tree.get_children())
        tree["columns"] = cols
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


# =============================================================================
# SCORE PANE: adapted from score_viewer.py::ScoreViewer, same App-removal as
# HistoryPane above. _parse_score/_load_score_csv/_display_*/_score_label are
# already free functions there, so they're reused verbatim.
# =============================================================================

def _parse_score(s):
    if s == "True":
        return True
    if s == "False":
        return False
    return None   # "" (hoặc thiếu cột) -> bỏ cặp


def _load_score_csv(path: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    parsed = []
    for r in rows:
        row = {"date": r.get("date", ""), "station_code": r.get("station_code", ""),
               "hour": int(r["hour"]), "buoi": r.get("buoi", "")}
        for field in FIELD_ORDER:
            row[f"forecast_{field}"] = r.get(f"forecast_{field}", "")
            row[f"obs_{field}"] = r.get(f"obs_{field}", "")
            row[f"score_{field}"] = _parse_score(r.get(f"score_{field}", ""))
        parsed.append(row)
    return parsed


def _display_forecast(field: str, value: str) -> str:
    return bucket_label(field, value) if value else ""


def _display_obs(field: str, value: str) -> str:
    if not value:
        return ""
    if field in ("hien_tuong", "huong_gio"):
        return bucket_label(field, value)
    return value


def _score_label(v) -> str:
    if v is True:
        return "Đạt"
    if v is False:
        return "Không đạt"
    return "Bỏ cặp"


class ScorePane:
    def __init__(self, root, dialogs, get_dir):
        self._root, self._dialogs, self._get_dir = root, dialogs, get_dir
        self._rows = []
        self._sort_col, self._sort_reverse = None, False
        self._hidden_field_groups = set()

    def build(self, parent):
        bar = ttk.Frame(parent, padding=(0, 0, 0, 6))
        bar.pack(fill="x")

        ttk.Label(bar, text="Trạm:").pack(side="left")
        self._station_filter = tk.StringVar(value=ALL_STATIONS)
        ttk.Combobox(bar, textvariable=self._station_filter,
                    values=[ALL_STATIONS] + STATION_NAMES, state="readonly",
                    width=16).pack(side="left", padx=(2, 12))
        self._station_filter.trace_add("write", lambda *_: self._render_table())

        ttk.Label(bar, text="Ngày:").pack(side="left")
        self._date_filter = tk.StringVar()
        self._date_combo = ttk.Combobox(bar, textvariable=self._date_filter,
                                       state="readonly", width=12)
        self._date_combo.pack(side="left", padx=(2, 12))
        self._date_filter.trace_add("write", lambda *_: self._on_date_change())

        ttk.Label(bar, text="Trường:").pack(side="left")
        self._field_filter = tk.StringVar()
        self._field_combo = ttk.Combobox(
            bar, textvariable=self._field_filter,
            values=[FIELD_LABELS[f] for f in FIELD_ORDER] + [_ALL_FIELDS_LABEL],
            state="readonly", width=18)
        self._field_combo.pack(side="left", padx=(2, 12))
        self._field_filter.trace_add("write", lambda *_: self._render_table())

        ttk.Button(bar, text="Thiết lập...",
                  command=lambda: self._open_column_picker()).pack(side="left")

        self._summary = ttk.Label(parent, padding=(8, 4), background="#dce9f4")
        self._summary.pack(fill="x")

        self._empty_label = ttk.Label(
            parent, text="Không có file score_*.csv trong thư mục này.",
            foreground="#6b7280", padding=(8, 24))

        self._table_frame = ttk.Frame(parent, padding=(0, 4, 0, 0))
        tree = ttk.Treeview(self._table_frame, show="headings")
        vsb = ttk.Scrollbar(self._table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._table_frame.rowconfigure(0, weight=1)
        self._table_frame.columnconfigure(0, weight=1)
        self._tree = tree
        tree.tag_configure("pass", background="#dff0d8")
        tree.tag_configure("fail", background="#f2dede")
        tree.tag_configure("skip", background="#eeeeee")

        statusbar = ttk.Frame(parent, padding=(0, 4, 0, 0))
        statusbar.pack(side="bottom", fill="x")
        self._status = ttk.Label(statusbar, text="", anchor="e")
        self._status.pack(side="right")

        self._field_filter.set(FIELD_LABELS[FIELD_ORDER[0]])
        self.reload()

    # ----- File discovery ---------------------------------------------------
    def _available_score_files(self) -> dict:
        out_dir = self._get_dir()
        found = {}
        try:
            names = os.listdir(out_dir)
        except OSError:
            return found
        for name in names:
            m = SCORE_CSV_RE.match(name)
            if m:
                ymd = m.group(1)
                found[f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"] = os.path.join(out_dir, name)
        return found

    def reload(self):
        """Rescan the current folder, repopulate Ngày, and (re)load a file:
        keeps the current selection if it still exists (forcing a re-read, in
        case the file grew), else falls back to the newest date."""
        dates = sorted(self._available_score_files())
        self._date_combo["values"] = dates
        if not dates:
            self._rows = []
            self._show_empty(reset_status=True)
            return
        if self._date_filter.get() not in dates:
            self._date_filter.set(dates[-1])   # triggers _on_date_change -> loads
        else:
            self._on_date_change()

    # ----- Loading a day -----------------------------------------------
    def _on_date_change(self):
        date_str = self._date_filter.get()
        path = self._available_score_files().get(date_str)
        if not path or not os.path.isfile(path):
            self._rows = []
            self._show_empty(reset_status=True)
            return
        try:
            self._rows = _load_score_csv(path)
        except (OSError, KeyError, ValueError) as e:
            _log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
            self._rows = []
            self._show_empty(reset_status=True)
            return
        _log("ACT", f"Xem chấm điểm: {os.path.basename(path)} ({len(self._rows)} dòng)")
        self._show_table()
        self._render_table()

    def _show_empty(self, reset_status=False):
        self._table_frame.pack_forget()
        if reset_status:
            self._summary.config(text="")
            self._status.config(text="")
        self._empty_label.pack(fill="both", expand=True)

    def _show_table(self):
        self._empty_label.pack_forget()
        self._table_frame.pack(fill="both", expand=True)

    # ----- Filter helpers ----------------------------------------------
    def _field_filter_key(self):
        label = self._field_filter.get()
        return "ALL" if label == _ALL_FIELDS_LABEL else _LABEL_TO_FIELD.get(label)

    def _filtered_rows(self):
        rows = self._rows
        station = self._station_filter.get()
        if station != ALL_STATIONS:
            code = NAME_TO_CODE.get(station)
            rows = [r for r in rows if r["station_code"] == code]
        return rows

    # ----- Sort -----------------------------------------------------------
    def _on_sort(self, col):
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col, self._sort_reverse = col, False
        self._render_table()

    def _sorted(self, rows):
        col = self._sort_col
        if col == "hour":
            return sorted(rows, key=lambda r: r["hour"], reverse=self._sort_reverse)
        if col == "buoi":
            return sorted(rows, key=lambda r: r["buoi"], reverse=self._sort_reverse)
        return rows

    def _heading_text(self, col, label):
        if self._sort_col == col:
            return label + (" ▼" if self._sort_reverse else " ▲")
        return label

    # ----- Summary bar ---------------------------------------------------
    def _render_summary(self, rows):
        field_key = self._field_filter_key()
        fields = FIELD_ORDER if field_key == "ALL" else (field_key,)
        dat = khong_dat = bo_cap = 0
        for r in rows:
            for f in fields:
                v = r[f"score_{f}"]
                if v is True:
                    dat += 1
                elif v is False:
                    khong_dat += 1
                else:
                    bo_cap += 1
        total = dat + khong_dat
        pct = (dat / total * 100) if total else 0
        field_txt = _ALL_FIELDS_LABEL.lower() if field_key == "ALL" else FIELD_LABELS[field_key]
        self._summary.config(
            text=f"Đạt {dat}/{total} ({pct:.1f}%) — bỏ cặp {bo_cap}, trường {field_txt}")

    # ----- Table rendering ------------------------------------------------
    def _render_table(self):
        if not self._rows:
            return
        field_key = self._field_filter_key()
        if field_key is None:
            return
        rows = self._sorted(self._filtered_rows())
        tree = self._tree

        show_station_col = self._station_filter.get() == ALL_STATIONS
        base_cols = ["station", "hour", "buoi"] if show_station_col else ["hour", "buoi"]

        if field_key == "ALL":
            visible = [f for f in FIELD_ORDER if f not in self._hidden_field_groups]
            columns = base_cols + [f"{f}__{part}" for f in visible for part in ("db", "qt", "diem")]
        else:
            visible = [field_key]
            columns = base_cols + ["db", "qt", "diem"]

        tree["columns"] = columns
        tree.delete(*tree.get_children())

        if show_station_col:
            tree.heading("station", text="Trạm")
            tree.column("station", width=100, anchor="w")
        tree.heading("hour", text=self._heading_text("hour", "Giờ"),
                     command=lambda: self._on_sort("hour"))
        tree.column("hour", width=50, anchor="center")
        tree.heading("buoi", text=self._heading_text("buoi", "Buổi"),
                     command=lambda: self._on_sort("buoi"))
        tree.column("buoi", width=70, anchor="w")

        if field_key == "ALL":
            for f in visible:
                tree.heading(f"{f}__db", text=f"{FIELD_LABELS[f]} (DB)")
                tree.column(f"{f}__db", width=110, anchor="w")
                tree.heading(f"{f}__qt", text=f"{FIELD_LABELS[f]} (QT)")
                tree.column(f"{f}__qt", width=110, anchor="w")
                tree.heading(f"{f}__diem", text=f"{FIELD_LABELS[f]} (Điểm)")
                tree.column(f"{f}__diem", width=80, anchor="center")
        else:
            tree.heading("db", text="DB"); tree.column("db", width=120, anchor="w")
            tree.heading("qt", text="QT"); tree.column("qt", width=120, anchor="w")
            tree.heading("diem", text="Điểm"); tree.column("diem", width=90, anchor="center")

        for r in rows:
            base_values = ([STATIONS.get(r["station_code"], r["station_code"])] if show_station_col else [])
            base_values += [f"{r['hour']:02d}", r["buoi"]]
            if field_key == "ALL":
                values = list(base_values)
                for f in visible:
                    values += [_display_forecast(f, r[f"forecast_{f}"]),
                              _display_obs(f, r[f"obs_{f}"]),
                              _score_label(r[f"score_{f}"])]
                any_false = any(r[f"score_{f}"] is False for f in FIELD_ORDER)
                tag = "fail" if any_false else "pass"
            else:
                sc = r[f"score_{field_key}"]
                values = base_values + [
                    _display_forecast(field_key, r[f"forecast_{field_key}"]),
                    _display_obs(field_key, r[f"obs_{field_key}"]),
                    _score_label(sc)]
                tag = "pass" if sc is True else ("fail" if sc is False else "skip")
            tree.insert("", "end", values=values, tags=(tag,))

        self._status.config(text=f"{len(rows)} dòng")
        self._render_summary(rows)

    # ----- "Thiết lập...": nhóm cột theo trường ------------------------------
    def _open_column_picker(self):
        _log("ACT", "Mở hộp thoại Thiết lập (Xem chấm điểm)")
        dlg = make_dialog(self._root, self._dialogs, "score_columns", "Thiết lập")
        if dlg is None:
            return
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text='Hiện nhóm cột theo trường (áp dụng ở chế độ "Tất cả 6 trường"):'
                  ).pack(anchor="w", pady=(0, 6))

        field_vars = {}
        for f in FIELD_ORDER:
            var = tk.BooleanVar(value=f not in self._hidden_field_groups)
            field_vars[f] = var
            ttk.Checkbutton(frm, text=FIELD_LABELS[f], variable=var).pack(anchor="w", pady=2)

        def apply_and_close():
            self._hidden_field_groups = {f for f, v in field_vars.items() if not v.get()}
            self._render_table()
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Đóng", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Áp dụng", command=apply_and_close).pack(side="right", padx=6)

        dlg.minsize(300, 0)
        center_over_root(self._root, dlg)


# =============================================================================
# WINDOW: 2-tab Notebook (Số liệu / Xem chấm điểm) + a folder picker shared by
# both tabs, since neither history_*.csv nor score_*.csv carry their own path.
# =============================================================================

class CsvViewerApp:
    def __init__(self, root, initial_dir):
        self.root = root
        self._dir = initial_dir
        self._dialogs = {}
        root.title("Solieu26 - Xem CSV")
        root.geometry("1150x650")

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="Thư mục:").pack(side="left")
        self._dir_var = tk.StringVar(value=self._dir)
        ttk.Entry(bar, textvariable=self._dir_var, state="readonly", width=70).pack(
            side="left", padx=(4, 8), fill="x", expand=True)
        ttk.Button(bar, text="Chọn thư mục...", command=self._choose_dir).pack(side="left")
        ttk.Button(bar, text="Làm mới", command=self._reload_all).pack(side="left", padx=(6, 0))

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        history_tab = ttk.Frame(nb)
        score_tab = ttk.Frame(nb)
        nb.add(history_tab, text="Số liệu")
        nb.add(score_tab, text="Xem chấm điểm")

        self.history_pane = HistoryPane(root, self._dialogs, self._get_dir)
        self.score_pane = ScorePane(root, self._dialogs, self._get_dir)
        self.history_pane.build(history_tab)
        self.score_pane.build(score_tab)

    def _get_dir(self) -> str:
        return self._dir

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self._dir or os.getcwd(),
                                     title="Chọn thư mục chứa CSV")
        if not d:
            return
        self._dir = d
        self._dir_var.set(d)
        _log("ACT", f"Đổi thư mục: {d}")
        self._reload_all()

    def _reload_all(self):
        self.history_pane.reload()
        self.score_pane.reload()


def main(argv=None) -> int:
    # Some Windows consoles default stdout/stderr to cp1252, which can't hold
    # Vietnamese diacritics - argparse's --help and _log() above both write
    # through these streams, so widen them upfront instead of crashing later.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="Xem history_*.csv / score_*.csv độc lập, không cần chạy toàn bộ app.")
    parser.add_argument("--dir", default=None,
                         help=f"Thư mục chứa CSV, mặc định {config.DEFAULT_OUTPUT_DIR}")
    args = parser.parse_args(argv)
    initial_dir = os.path.abspath(args.dir) if args.dir else config.DEFAULT_OUTPUT_DIR

    root = tk.Tk()
    CsvViewerApp(root, initial_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
