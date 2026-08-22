"""
forecast_editor.py
====================
The "Dự báo" tab: forecast-viên nhập bucket dự báo cho 6 trường theo trạm +
khoảng giờ, 1 file/ngày (forecast_YYYYMMDD.csv, nhiều trạm trong cùng file).
Chỉ đọc/ghi CSV qua pipeline/forecast.py, không tự chạy pipeline nào khác
(scoring/xuất số liệu quan trắc nằm ở chỗ khác).

Reaches into the App instance (see main.py) for the root window, the shared
log helper, và output-dir/config state, cùng kiểu với viewer.py.
"""

import datetime
import os

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from utils import config_utils as config
from common import STATIONS, STATION_NAMES, NAME_TO_CODE, HOURS, FORECAST_CSV_RE
from pipeline.forecast import (
    load_records_csv, build_hourly_table, export_forecast_table,
    FIELD_ORDER, WINDOW_FIELDS, LINEAR_FIELDS, CIRCULAR_FIELDS,
)
from scoring.score_tables import BUCKETS

FIELD_LABELS = {
    "tong_luong_may": "Tổng lượng mây",
    "do_cao_man_may": "Độ cao màn mây",
    "hien_tuong":     "Hiện tượng",
    "huong_gio":      "Hướng gió",
    "toc_do_gio":     "Tốc độ gió",
    "tam_nhin":       "Tầm nhìn",
}
_LABEL_TO_FIELD = {v: k for k, v in FIELD_LABELS.items()}


def _field_key_from_label(label: str) -> str:
    return _LABEL_TO_FIELD[label]


# ----- Bucket choice labels: 1 hàm/kiểu bucket, đọc thẳng từ BUCKETS ---------
# (thay cho window_labels()/linear_labels()/... đã mất theo module cũ đã xoá,
# xem reference/forecast_bucket_generator.py).

def _window_choices(field: str) -> list:
    labels = []
    for lo, hi in BUCKETS[field]["windows"]:
        labels.append(f"{lo} trở lên" if hi == float("inf") else f"{lo}-{hi}")
    return labels


def _linear_choices(field: str) -> list:
    bounds = BUCKETS[field]["bounds"]
    labels = [f"<{bounds[0]}"]
    labels += [f"{lo}-{hi}" for lo, hi in zip(bounds, bounds[1:])]
    labels.append(f">{bounds[-1]}")
    no_ceiling = BUCKETS[field].get("no_ceiling")
    if no_ceiling is not None:
        labels.append(no_ceiling)   # "không màn": 1 bucket riêng, đứng cuối
    return labels


def _circular_choices(field: str) -> list:
    return list(BUCKETS[field]["labels"])


def _phenomenon_choices():
    """Trả về (nhãn hiển thị, mã mega) cùng thứ tự - bucket_selected lưu MÃ,
    không phải index (khác 3 kiểu bucket kia)."""
    mega_keys = BUCKETS["hien_tuong"]["mega_buckets"]
    mega_labels = BUCKETS["hien_tuong"]["mega_labels"]
    return [mega_labels[k] for k in mega_keys], mega_keys


def bucket_label(field: str, bucket_selected) -> str:
    """bucket_selected đã lưu (index hoặc mã mega) -> nhãn tiếng Việt để hiển
    thị trong bảng/preview. None (chưa có dự báo giờ đó) -> chuỗi rỗng."""
    if bucket_selected is None:
        return ""
    if field == "hien_tuong":
        return BUCKETS["hien_tuong"]["mega_labels"].get(bucket_selected, str(bucket_selected))
    if field in WINDOW_FIELDS:
        labels = _window_choices(field)
    elif field in LINEAR_FIELDS:
        labels = _linear_choices(field)
    elif field in CIRCULAR_FIELDS:
        labels = _circular_choices(field)
    else:
        return str(bucket_selected)
    idx = int(bucket_selected)
    return labels[idx] if 0 <= idx < len(labels) else str(bucket_selected)


def _build_bucket_widget(parent, field: str):
    """1 widget bucket theo field_name - trả về (widget, get, set_): get() đọc
    giá trị hiện có (index hoặc mã mega); set_(v) nạp lại giá trị đã lưu (chỉ
    gọi khi sửa dòng có sẵn - dòng mới để widget tự ở lựa chọn đầu tiên)."""
    if field in WINDOW_FIELDS:
        cb = ttk.Combobox(parent, state="readonly", values=_window_choices(field), width=20)
        cb.current(0)
        return cb, cb.current, lambda v: cb.current(int(v))

    if field in LINEAR_FIELDS:
        cb = ttk.Combobox(parent, state="readonly", values=_linear_choices(field), width=20)
        cb.current(0)
        return cb, cb.current, lambda v: cb.current(int(v))

    if field in CIRCULAR_FIELDS:
        cb = ttk.Combobox(parent, state="readonly", values=_circular_choices(field), width=10)
        cb.current(0)
        return cb, cb.current, lambda v: cb.current(int(v))

    # hien_tuong (phenomenon): chỉ chọn MEGA, buổi suy từ giờ lúc chấm điểm.
    labels, keys = _phenomenon_choices()
    frame = ttk.Frame(parent)
    cb = ttk.Combobox(frame, state="readonly", values=labels, width=32)
    cb.current(0)
    cb.pack(anchor="w")
    ttk.Label(frame, text="(buổi suy từ giờ lúc chấm điểm - không chọn ở đây)",
              foreground="#6b7280").pack(anchor="w", pady=(2, 0))
    return frame, (lambda: keys[cb.current()]), (lambda v: cb.current(keys.index(v)))


class ForecastEditor:
    def __init__(self, app):
        self.app = app
        self._records = []            # bảng trong bộ nhớ: TOÀN BỘ ngày đang chọn (mọi trạm)
        self._selected_index = None   # index trong self._records đang nạp để sửa (None = "Thêm dòng")
        self._current_date = None

    # ----- Tab construction -------------------------------------------------
    def build(self, parent):
        top = ttk.Frame(parent, padding=(0, 0, 0, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Ngày:").pack(side="left")
        self._date_filter = tk.StringVar()
        # KHÔNG readonly: khác Ngày dropdown của Viewer (chỉ liệt kê file có sẵn),
        # ở đây dự báo viên phải gõ được ngày CHƯA có file để bắt đầu dự báo mới.
        self._date_combo = ttk.Combobox(top, textvariable=self._date_filter, width=12)
        self._date_combo.pack(side="left", padx=(4, 0))
        self._date_filter.trace_add("write", lambda *_: self._on_date_change())

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(body)
        right.pack(side="left", fill="y", padx=(10, 0))

        self._build_table_section(left)
        self._build_output_section(left)
        self._build_editor_panel(right)

        self._refresh_date_options()
        self._date_filter.set(datetime.date.today().strftime("%Y-%m-%d"))   # trigger _load_date

    # ----- File discovery ---------------------------------------------------
    def _current_output_dir(self) -> str:
        if self.app.runner.last_output_dir:
            return self.app.runner.last_output_dir
        return os.path.abspath(self.app.v["output_dir"].get().strip() or config.DEFAULT_OUTPUT_DIR)

    def _available_forecast_files(self) -> dict:
        out_dir = self._current_output_dir()
        found = {}
        try:
            names = os.listdir(out_dir)
        except OSError:
            return found
        for name in names:
            m = FORECAST_CSV_RE.match(name)
            if m:
                ymd = m.group(1)
                found[f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"] = os.path.join(out_dir, name)
        return found

    def _refresh_date_options(self):
        self._date_combo["values"] = sorted(self._available_forecast_files())

    # ----- Loading a day (mọi trạm) -----------------------------------------
    def _on_date_change(self):
        date_str = self._date_filter.get().strip()
        try:
            datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return   # đang gõ dở, chưa phải ngày hợp lệ - bỏ qua, không load
        self._load_date(date_str)

    def _load_date(self, date_str: str):
        """Nạp lại TOÀN BỘ forecast_YYYYMMDD.csv cho date_str (mọi trạm) vào
        self._records. "Xuất CSV..." sau đó luôn ghi lại đúng danh sách này,
        không bao giờ chỉ ghi phần trạm đang sửa - tránh mất dự báo trạm khác
        đã lưu trước đó trong cùng file."""
        self._current_date = date_str
        path = os.path.join(self._current_output_dir(), f"forecast_{date_str.replace('-', '')}.csv")
        if os.path.isfile(path):
            try:
                self._records = load_records_csv(path)
            except (OSError, ValueError, KeyError) as e:
                self.app._log("ERR", f"Không đọc được {os.path.basename(path)}: {e}")
                self._records = []
        else:
            self._records = []
        self.app._log("ACT", f"Dự báo: nạp ngày {date_str} ({len(self._records)} dòng)")
        self._refresh_table()
        self._reset_editor()
        self._refresh_output_summary()
        self._refresh_preview()

    # ----- Bảng bucket đã nhập ------------------------------------------
    def _build_table_section(self, parent):
        box = ttk.LabelFrame(parent, text="Bảng bucket đã nhập", padding=8)
        box.pack(fill="both", expand=True)

        toolbar = ttk.Frame(box)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Thêm dòng",
                   command=lambda: self._reset_editor()).pack(side="right")

        table_frame = ttk.Frame(box)
        table_frame.pack(fill="both", expand=True, pady=(6, 0))
        columns = ("station", "time", "field", "value")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                            height=6, selectmode="browse")
        tree.heading("station", text="Trạm")
        tree.heading("time", text="Thời gian")
        tree.heading("field", text="Trường dữ liệu")
        tree.heading("value", text="Bucket đã chọn")
        tree.column("station", width=120, anchor="w")
        tree.column("time", width=80, anchor="w")
        tree.column("field", width=150, anchor="w")
        tree.column("value", width=220, anchor="w")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda e: self._on_row_selected())
        self._tree = tree

        ttk.Label(box, foreground="#6b7280",
                  text="Chọn một dòng để nạp vào panel bên phải; \"Thêm dòng\" để bắt đầu dòng mới."
                  ).pack(anchor="w", pady=(6, 0))

    def _refresh_table(self):
        tree = self._tree
        tree.delete(*tree.get_children())
        for i, r in enumerate(self._records):
            station_name = STATIONS.get(r["station_code"], r["station_code"])
            time_str = f"{r['start_hour']:02d}-{r['end_hour']:02d}"
            tree.insert("", "end", iid=str(i), values=(
                station_name, time_str, FIELD_LABELS[r["field_name"]],
                bucket_label(r["field_name"], r["bucket_selected"])))

    def _on_row_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        index = int(sel[0])
        self._selected_index = index
        self._load_editor(self._records[index])

    # ----- RowEditorPanel --------------------------------------------------
    def _build_editor_panel(self, parent):
        box = ttk.LabelFrame(parent, text="Sửa / thêm dòng", padding=8)
        box.pack(fill="y")
        self._editor_mode_label = ttk.Label(box, text="", font=("", 9, "bold"))
        self._editor_mode_label.pack(anchor="w", pady=(0, 8))

        ttk.Label(box, text="Trạm:").pack(anchor="w")
        self._editor_station = tk.StringVar()
        ttk.Combobox(box, textvariable=self._editor_station, state="readonly",
                    values=STATION_NAMES, width=24).pack(anchor="w", pady=(0, 6))

        ttk.Label(box, text="Từ giờ:").pack(anchor="w")
        self._editor_start_hour = ttk.Combobox(box, state="readonly", values=HOURS, width=6)
        self._editor_start_hour.pack(anchor="w", pady=(0, 6))

        ttk.Label(box, text="Đến giờ:").pack(anchor="w")
        self._editor_end_hour = ttk.Combobox(box, state="readonly", values=HOURS, width=6)
        self._editor_end_hour.pack(anchor="w", pady=(0, 6))

        ttk.Label(box, text="Trường dữ liệu:").pack(anchor="w")
        self._editor_field = tk.StringVar()
        field_combo = ttk.Combobox(box, textvariable=self._editor_field, state="readonly",
                                   values=[FIELD_LABELS[f] for f in FIELD_ORDER], width=24)
        field_combo.pack(anchor="w", pady=(0, 6))
        field_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_bucket_widget())

        ttk.Label(box, text="Bucket:").pack(anchor="w")
        self._bucket_container = ttk.Frame(box)
        self._bucket_container.pack(anchor="w", fill="x", pady=(0, 8))
        self._bucket_get = None   # set by _rebuild_bucket_widget()

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Lưu dòng", command=lambda: self._on_save_row()).pack(fill="x")
        self._delete_btn = ttk.Button(btns, text="Xóa dòng", command=lambda: self._on_delete_row())
        self._delete_btn.pack(fill="x", pady=(4, 0))

    def _reset_editor(self):
        self._selected_index = None
        self._editor_mode_label.config(text="+ Thêm dòng mới")
        if self._tree.selection():
            self._tree.selection_remove(self._tree.selection())
        default_code = (config.CONFIG.get("station_code") or "").strip()
        self._editor_station.set(STATIONS.get(default_code, STATION_NAMES[0]))
        self._editor_start_hour.set(HOURS[0])
        self._editor_end_hour.set(HOURS[-1])
        self._editor_field.set(FIELD_LABELS[FIELD_ORDER[0]])
        self._rebuild_bucket_widget()
        self._delete_btn.config(state="disabled")

    def _load_editor(self, record: dict):
        self._editor_mode_label.config(
            text=f"Đang sửa: {record['start_hour']:02d}-{record['end_hour']:02d} · "
                 f"{FIELD_LABELS[record['field_name']]}")
        self._editor_station.set(STATIONS.get(record["station_code"], record["station_code"]))
        self._editor_start_hour.set(f"{record['start_hour']:02d}")
        self._editor_end_hour.set(f"{record['end_hour']:02d}")
        self._editor_field.set(FIELD_LABELS[record["field_name"]])
        self._rebuild_bucket_widget(initial=record["bucket_selected"])
        self._delete_btn.config(state="normal")

    def _rebuild_bucket_widget(self, initial=None):
        for w in self._bucket_container.winfo_children():
            w.destroy()
        field = _field_key_from_label(self._editor_field.get())
        widget, get, set_ = _build_bucket_widget(self._bucket_container, field)
        widget.pack(anchor="w")
        self._bucket_get = get
        if initial is not None:
            set_(initial)   # widget đã tự ở lựa chọn đầu tiên nếu initial=None (dòng mới)

    def _on_save_row(self):
        try:
            start_hour = int(self._editor_start_hour.get())
            end_hour = int(self._editor_end_hour.get())
        except ValueError:
            messagebox.showerror("Không lưu được dòng", "Chưa chọn Từ giờ/Đến giờ.")
            return
        if end_hour < start_hour:
            messagebox.showerror("Không lưu được dòng", "Đến giờ phải sau hoặc bằng Từ giờ.")
            return
        station_code = NAME_TO_CODE.get(self._editor_station.get())
        if not station_code:
            messagebox.showerror("Không lưu được dòng", "Chưa chọn Trạm.")
            return

        field = _field_key_from_label(self._editor_field.get())
        record = {
            "station_code": station_code, "start_hour": start_hour, "end_hour": end_hour,
            "field_name": field, "bucket_selected": self._bucket_get(),
        }
        if self._selected_index is None:
            self._records.append(record)
        else:
            self._records[self._selected_index] = record

        self._refresh_table()
        self._reset_editor()
        self._refresh_output_summary()
        self._refresh_preview()
        self.app._log("OK", f"Dự báo: lưu dòng {self._editor_station.get()} "
                            f"{start_hour:02d}-{end_hour:02d} {FIELD_LABELS[field]}")

    def _on_delete_row(self):
        if self._selected_index is None:
            return
        del self._records[self._selected_index]
        self._refresh_table()
        self._reset_editor()
        self._refresh_output_summary()
        self._refresh_preview()

    # ----- Khung Xuất CSV ----------------------------------------------
    def _build_output_section(self, parent):
        box = ttk.LabelFrame(parent, text="Xuất CSV", padding=8)
        box.pack(fill="x", pady=(8, 0))

        self._output_summary = ttk.Label(box, foreground="#374151")
        self._output_summary.pack(anchor="w")

        preview_frame = ttk.Frame(box)
        preview_frame.pack(fill="both", expand=True, pady=(6, 0))
        preview_cols = ["station", "hour"] + list(FIELD_ORDER)
        tree = ttk.Treeview(preview_frame, columns=preview_cols, show="headings", height=6)
        tree.heading("station", text="Trạm")
        tree.column("station", width=90, anchor="w")
        tree.heading("hour", text="Giờ")
        tree.column("hour", width=36, anchor="center")
        for f in FIELD_ORDER:
            tree.heading(f, text=FIELD_LABELS[f])
            tree.column(f, width=100, anchor="w")
        vsb = ttk.Scrollbar(preview_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self._preview_tree = tree

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Xuất CSV...", command=lambda: self._on_export()).pack(side="left")
        ttk.Button(btns, text="Nhập CSV...", command=lambda: self._on_import()).pack(
                  side="left", padx=(6, 0))

    def _refresh_output_summary(self):
        n = len(self._records)
        if n == 0:
            self._output_summary.config(text="Chưa có dòng nào trong bảng.")
            return
        stations = sorted({STATIONS.get(r["station_code"], r["station_code"]) for r in self._records})
        self._output_summary.config(text=f"{n} dòng · {len(stations)} trạm: {', '.join(stations)}")

    def _refresh_preview(self):
        """Xem trước theo bảng ĐANG CÓ trong bộ nhớ (chưa chắc đã ghi ra đĩa,
        xem log/"Xuất CSV..." để biết trạng thái ghi thật)."""
        tree = self._preview_tree
        tree.delete(*tree.get_children())
        try:
            rows = build_hourly_table(self._records)
        except ValueError as e:
            self.app._log("ERR", f"Dự báo: dữ liệu không hợp lệ để xem trước: {e}")
            return
        for r in rows:
            if all(r[f] is None for f in FIELD_ORDER):
                continue   # giờ chưa được dự báo field nào - bớt nhiễu bảng xem trước
            station_name = STATIONS.get(r["station_code"], r["station_code"])
            values = [station_name, f"{r['hour']:02d}"] + [
                bucket_label(f, r[f]) for f in FIELD_ORDER]
            tree.insert("", "end", values=values)

    def _on_export(self):
        if not self._records:
            messagebox.showinfo("Chưa có dòng", "Hãy thêm ít nhất một dòng trong bảng.")
            return
        date_str = self._current_date
        out_dir = self._current_output_dir()
        os.makedirs(out_dir, exist_ok=True)
        try:
            result = export_forecast_table(self._records, date_str, out_dir)
        except OSError as e:
            self.app._log("ERR", f"Không xuất được forecast_{date_str.replace('-', '')}.csv: {e}")
            messagebox.showerror("Lỗi", f"Không xuất được file:\n{e}")
            return
        self.app._log("OK", f"Đã xuất {result['records']} dòng vào {os.path.basename(result['csv'])}")
        self._refresh_date_options()

    def _on_import(self):
        path = filedialog.askopenfilename(
            title="Nhập CSV dự báo", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            imported = load_records_csv(path)
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("Không nhập được CSV", str(e))
            return
        if self._records and not messagebox.askyesno(
                "Ghi đè dữ liệu hiện tại?",
                f"Bảng hiện có {len(self._records)} dòng. Nhập CSV sẽ THAY THẾ toàn bộ. Tiếp tục?"):
            return
        self._records = imported
        self._refresh_table()
        self._reset_editor()
        self._refresh_output_summary()
        self._refresh_preview()
        self.app._log("OK", f"Đã nhập {len(imported)} dòng từ {os.path.basename(path)}")
