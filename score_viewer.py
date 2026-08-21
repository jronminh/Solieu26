"""
score_viewer.py
====================
The "Xem chấm điểm" tab: đọc score_YYYYMMDD.csv (chỉ đọc, không tự chạy
pipeline/match_score.py::export_forecast_score()), lọc theo trạm/ngày/trường,
tô màu theo Đạt/Không đạt/Bỏ cặp. Theo khuôn mẫu viewer.py nhưng đọc 1 loại
file khác và có quy tắc tô màu riêng.

Reaches into the App instance (see main.py) for the root window, the shared
log helper, và output-dir/config state.
"""

import csv
import os

import tkinter as tk
from tkinter import ttk

from utils import config_utils as config
from common import STATIONS, STATION_NAMES, NAME_TO_CODE, ALL_STATIONS, SCORE_CSV_RE, make_dialog, center_over_root
from pipeline.match_score import FIELD_ORDER
from forecast_editor import FIELD_LABELS, bucket_label

_LABEL_TO_FIELD = {v: k for k, v in FIELD_LABELS.items()}
_ALL_FIELDS_LABEL = "Tất cả 6 trường"


def _parse_score(s):
    if s == "True":
        return True
    if s == "False":
        return False
    return None   # "" (hoặc thiếu cột) -> bỏ cặp


def _load_score_csv(path: str) -> list:
    """Đọc score_YYYYMMDD.csv -> list dict, score_<field> đã ép về bool/None
    (CSV chỉ có string "True"/"False"/"" - write_csv() ghi None thành "")."""
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
    """forecast_<field> luôn là bucket đã chọn (index hoặc mã mega) - bucket_label()
    tự ép kiểu cần thiết."""
    return bucket_label(field, value) if value else ""


def _display_obs(field: str, value: str) -> str:
    """obs_<field> CHỈ cùng "miền giá trị" với forecast ở 2 trường hien_tuong
    (mã mega) và huong_gio (chỉ số hướng) - 4 trường còn lại là số đo thô
    (hoặc NO_CEILING), hiển thị nguyên văn, không tra qua bucket_label()."""
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


class ScoreViewer:
    def __init__(self, app):
        self.app = app
        self._rows = []
        self._sort_col, self._sort_reverse = None, False
        self._hidden_field_groups = set()   # "Tất cả 6 trường" mode: field key -> ẩn 3 cột của field đó

    # ----- Tab construction -------------------------------------------------
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
            parent, text="Chưa có dữ liệu chấm điểm", foreground="#6b7280", padding=(8, 24))

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
        self._refresh_date_options()
        dates = sorted(self._available_score_files())
        if dates:
            self._date_filter.set(dates[-1])
        else:
            self._show_empty(reset_status=True)

    # ----- File discovery ---------------------------------------------------
    def _current_output_dir(self) -> str:
        if self.app.runner.last_output_dir:
            return self.app.runner.last_output_dir
        return os.path.abspath(self.app.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR)

    def _available_score_files(self) -> dict:
        out_dir = self._current_output_dir()
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

    def _refresh_date_options(self):
        self._date_combo["values"] = sorted(self._available_score_files())

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
            self.app._log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
            self._rows = []
            self._show_empty(reset_status=True)
            return
        self.app._log("ACT", f"Xem chấm điểm: {os.path.basename(path)} ({len(self._rows)} dòng)")
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
        return rows   # cột DB/QT/Điểm là giá trị tổng hợp lúc render, không hỗ trợ sort

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
            return   # field_filter chưa set xong (đang khởi tạo)
        rows = self._sorted(self._filtered_rows())
        tree = self._tree

        # Trạm = "Tất cả các trạm" trộn nhiều trạm vào cùng bảng - thêm cột Trạm
        # để phân biệt; ẩn khi đã lọc còn 1 trạm cụ thể (khi đó thừa, mọi dòng
        # cùng 1 trạm).
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

    # ----- "Thiết lập...": nhóm cột theo trường (chỉ có ý nghĩa ở chế độ Tất cả 6 trường) ---
    def _open_column_picker(self):
        app = self.app
        app._log("ACT", "Mở hộp thoại Thiết lập (Xem chấm điểm)")
        dlg = make_dialog(app.root, app._dialogs, "score_columns", "Thiết lập")
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
        center_over_root(app.root, dlg)
