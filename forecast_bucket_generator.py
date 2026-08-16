"""
forecast_bucket_generator.py
====================
Standalone Tkinter tool that lets a dự báo viên (forecaster) pick a BUCKET
(from buckets.py's BUCKETS, via forecast_bucket_logic.py) for each of the 6
scored fields over a time range, and exports one CSV row per HOUR covered -
this is a hand-built stand-in for stage 2 ("Dự báo") of the scoring pipeline
mapped out in TODO.md, which currently has no UI at all.

GUI vs helper split: this file is Tkinter ONLY - every non-widget rule
(bucket labels, hour-range merge, CSV shape, CSV import) lives in
forecast_bucket_logic.py and is imported here, not reimplemented. The only
things this file adds on top of that pure logic are: 4 widget-builder
functions (_build_*_bucket_field, one per BUCKETS "kind") that wrap a logic
label-list in a Combobox, and the RowEditorPanel/App classes that wire
widgets to user actions. If forecast_bucket_logic.py's functions ever need
reuse outside a GUI (a headless script, a future pipeline module, tests),
they can be imported straight from there with no tkinter dependency along
for the ride.

Backbone and pipeline mirror bulletin_generator.py on purpose (same table +
always-visible side editor + "merge by hour" flow), just pointed at bucket
choices instead of raw mã "Qt..." field values:

  - Table (_build_table_section-style): Thời gian / Trường dữ liệu / Bucket
    đã chọn. One row = "field F is bucket B from giờ START to giờ END, both
    included" - same hourly, overlap-allowed shape as bulletin_generator.py
    (a "07-09" row covers hours 07, 08 AND 09).
  - RowEditorPanel: same always-visible add/edit panel, double-click a row
    to edit it. The value widget per field is a Combobox built from
    forecast_bucket_logic's label helpers (themselves derived from
    BUCKETS[...]["windows"]/["bounds"]/["labels"], not hardcoded, so they
    can't drift from bucket_of()) instead of a raw-value widget from
    tables.py.
  - "Sinh CSV theo giờ" (_build_output_section-style): for every hour any
    row covers, merge whichever rows currently cover that hour (one bucket
    per field, last-started row wins on overlap - same rule as
    bulletin_generator.py) into ONE csv row. Missing fields at an hour are
    left BLANK (not defaulted) and flagged in a warning, since a forecaster
    not yet having picked a bucket is meaningfully different from picking
    bucket 0.
  - "Nhập CSV..." is the inverse: reads a CSV built to this same schema,
    run-length-encodes each field's per-hour value back into rows, and
    REPLACES whatever is currently in the table/station fields. Malformed
    cells are skipped with a warning rather than aborting the whole import.

hien_tuong is special: the forecaster only picks the MEGA bucket (loại hiện
tượng). The SUB bucket (buổi) is never picked by hand - it is derived per
HOUR from "Khung giờ áp dụng" via buckets.sub_of_hour() (inside
forecast_bucket_logic.hien_tuong_row_values), since buổi is tightly coupled
to giờ and a free-standing choice could silently disagree with the time
range already set on the row.

Deliberately narrow, same spirit as bulletin_generator.py and
buckets_scoring_lab.py: exercises ONLY the forecast-entry step. Does not
touch the observation adapter (stage 3), matcher (stage 4), the scorer
itself (stage 5 - see buckets_scoring_lab.py), or storage (stage 6).

Imports forecast_bucket_logic.py (which itself only imports buckets.py) and
nothing else project-local - no gui.py/decode.py/encode.py/csv_pipeline.py/
config.py/tables.py/bulletin_generator.py. Run:
    python forecast_bucket_generator.py
"""

import csv
import io
import os
from datetime import date

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from forecast_bucket_logic import (
    FIELD_ORDER, FIELD_LABELS, FIELD_DEFAULTS,
    HUONG_GIO_LABELS, PHENOMENON_MEGA_KEYS, PHENOMENON_MEGA_LABEL_TEXT,
    CSV_FIELDNAMES,
    window_labels, linear_labels, field_key_from_label, row_value_str,
    covered_hours, merge_at_hour, csv_row_for_hour, import_csv_rows,
)


# =============================================================================
# Widget builders - 1 / kind trong BUCKETS ("forecast_window", "linear",
# "circular", "phenomenon"). Mỗi builder(parent) -> (widget, get() -> bucket
# value, set_(value)) - CHỈ đọc nhãn/khóa từ forecast_bucket_logic, không tự
# tính lại gì từ BUCKETS.
# =============================================================================

def _build_window_bucket_field(field_key: str, width: int = 16):
    labels = window_labels(field_key)

    def builder(parent):
        cb = ttk.Combobox(parent, width=width, state="readonly", values=labels)
        cb.current(0)
        cb.pack(anchor="w")

        def get():
            return cb.current()

        def set_(idx):
            cb.current(int(idx))

        return cb, get, set_
    return builder


def _build_linear_bucket_field(field_key: str, width: int = 20):
    labels = linear_labels(field_key)

    def builder(parent):
        cb = ttk.Combobox(parent, width=width, state="readonly", values=labels)
        cb.current(0)
        cb.pack(anchor="w")

        def get():
            return cb.current()

        def set_(idx):
            cb.current(int(idx))

        return cb, get, set_
    return builder


def _build_circular_bucket_field(parent):
    cb = ttk.Combobox(parent, width=8, state="readonly", values=HUONG_GIO_LABELS)
    cb.current(0)
    cb.pack(anchor="w")

    def get():
        return cb.current()

    def set_(idx):
        cb.current(int(idx))

    return cb, get, set_


def _build_phenomenon_bucket_field(parent):
    """Chỉ chọn MEGA (loại hiện tượng). Buổi (sub-bucket) KHÔNG chọn ở đây -
    nó luôn suy trực tiếp từ "Khung giờ áp dụng" phía trên (qua
    forecast_bucket_logic.hien_tuong_row_values -> buckets.sub_of_hour()),
    vì buổi vốn gắn chặt với giờ, chọn tay thêm dễ lệch với khung giờ đã
    đặt."""
    frame = ttk.Frame(parent)
    mega_cb = ttk.Combobox(frame, width=30, state="readonly", values=PHENOMENON_MEGA_LABEL_TEXT)
    mega_cb.current(0)
    mega_cb.pack(anchor="w")
    ttk.Label(frame, text="(buổi tự suy từ \"Khung giờ áp dụng\" ở trên)",
              foreground="#6b7280").pack(anchor="w", pady=(2, 0))
    frame.pack(anchor="w")

    def get():
        return PHENOMENON_MEGA_KEYS[mega_cb.current()]

    def set_(v):
        mega_cb.current(PHENOMENON_MEGA_KEYS.index(v))

    return frame, get, set_


FIELD_WIDGET_BUILDERS = {
    "tong_luong_may": _build_window_bucket_field("tong_luong_may"),
    "do_cao_man_may": _build_linear_bucket_field("do_cao_man_may", width=24),
    "hien_tuong": _build_phenomenon_bucket_field,
    "huong_gio": _build_circular_bucket_field,
    "toc_do_gio": _build_window_bucket_field("toc_do_gio"),
    "tam_nhin": _build_linear_bucket_field("tam_nhin"),
}


# =============================================================================
# RowEditorPanel - giống hệt vai trò trong bulletin_generator.py: khung thời
# gian áp dụng + trường dữ liệu + giá trị (ở đây là bucket), luôn hiện, không
# phải popup. load_new()/load_row() chuyển đổi mode, Lưu dòng gọi on_save.
# =============================================================================

class RowEditorPanel(ttk.Frame):
    HOURS = [f"{h:02d}" for h in range(24)]

    def __init__(self, parent, on_save):
        super().__init__(parent)
        self.on_save = on_save

        self.mode_label = ttk.Label(self, font=("", 9, "bold"))
        self.mode_label.pack(anchor="w", pady=(0, 8))

        time_box = ttk.LabelFrame(self, text="Khung giờ áp dụng", padding=8)
        time_box.pack(fill="x")
        ttk.Label(time_box, text="Từ giờ:").grid(row=0, column=0, sticky="w")
        self.start_hour = ttk.Combobox(time_box, width=4, state="readonly", values=self.HOURS)
        self.start_hour.grid(row=0, column=1, sticky="w")
        ttk.Label(time_box, text="Đến giờ (gồm):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.end_hour = ttk.Combobox(time_box, width=4, state="readonly", values=self.HOURS)
        self.end_hour.grid(row=1, column=1, sticky="w", pady=(4, 0))

        field_box = ttk.LabelFrame(self, text="Trường dữ liệu & bucket", padding=8)
        field_box.pack(fill="x", pady=(8, 0))
        ttk.Label(field_box, text="Trường:").pack(anchor="w")
        self.field_var = tk.StringVar()
        self.field_combo = ttk.Combobox(field_box, state="readonly", textvariable=self.field_var,
                                         values=[FIELD_LABELS[k] for k in FIELD_ORDER], width=26)
        self.field_combo.pack(anchor="w", pady=(0, 6), fill="x")
        self.field_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_value_widget())

        ttk.Label(field_box, text="Bucket:").pack(anchor="w")
        self.value_container = ttk.Frame(field_box)
        self.value_container.pack(anchor="w", fill="x", pady=(0, 4))

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Lưu dòng", command=self._save).pack(side="left")
        ttk.Button(btns, text="Dòng mới", command=self.load_new).pack(side="left", padx=(6, 0))

        self.load_new()

    def _rebuild_value_widget(self, initial=None):
        for w in self.value_container.winfo_children():
            w.destroy()
        key = field_key_from_label(self.field_var.get())
        widget, get, set_ = FIELD_WIDGET_BUILDERS[key](self.value_container)
        widget.pack(anchor="w")
        self._value_get = get
        set_(initial if initial is not None else FIELD_DEFAULTS[key])

    def load_new(self):
        self.editing_id = None
        self.mode_label.config(text="+ Thêm dòng mới")
        self.start_hour.current(7)
        self.end_hour.current(9)
        self.field_var.set(FIELD_LABELS[FIELD_ORDER[0]])
        self._rebuild_value_widget()

    def load_row(self, row: dict):
        self.editing_id = row["_id"]
        self.mode_label.config(
            text=f"Đang sửa: {row['start']:02d}-{row['end']:02d} - "
                 f"{FIELD_LABELS[row['field']]}")
        self.start_hour.set(f"{row['start']:02d}")
        self.end_hour.set(f"{row['end']:02d}")
        self.field_var.set(FIELD_LABELS[row["field"]])
        self._rebuild_value_widget(initial=row["value"])

    def _save(self):
        try:
            start = int(self.start_hour.get())
            end = int(self.end_hour.get())
            if end < start:
                raise ValueError("giờ kết thúc phải lớn hơn hoặc bằng giờ bắt đầu")
            key = field_key_from_label(self.field_var.get())
            value = self._value_get()
        except ValueError as e:
            messagebox.showerror("Không lưu được dòng", str(e))
            return
        self.on_save({"start": start, "end": end, "field": key, "value": value}, self.editing_id)
        self.load_new()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sinh CSV bucket dự báo theo giờ (dựa trên bulletin_generator.py)")
        root.minsize(1040, 660)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.isfile(icon_path):
            try:
                root.iconbitmap(icon_path)
            except tk.TclError:
                pass

        self.rows = []      # list of {"_id", "start", "end", "field", "value"}
        self._next_id = 1
        self._last_rows = []     # csv row dicts from the last "Sinh CSV theo giờ"

        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)

        self._build_station_section(body)

        main_row = ttk.Frame(body)
        main_row.pack(fill="both", expand=True)

        left = ttk.Frame(main_row)
        left.pack(side="left", fill="both", expand=True)

        right_box = ttk.LabelFrame(main_row, text="Thêm / sửa dòng", padding=8)
        right_box.pack(side="left", fill="y", padx=(10, 0))
        self.editor = RowEditorPanel(right_box, self._on_editor_save)
        self.editor.pack(fill="both", expand=True)

        self._build_table_section(left)
        self._build_output_section(left)

    # ----- trạm & ngày dự báo (global, áp dụng cho mọi dòng csv) --------
    def _build_station_section(self, parent):
        box = ttk.LabelFrame(parent, text="Trạm & ngày dự báo (áp dụng cho mọi dòng)", padding=8)
        box.pack(fill="x", pady=(0, 8))

        ttk.Label(box, text="Trạm (mã, vd k31):").grid(row=0, column=0, sticky="w")
        self.station_code = ttk.Entry(box, width=18)
        self.station_code.insert(0, "k31")
        self.station_code.grid(row=0, column=1, sticky="w")

        ttk.Label(box, text="Tên trạm:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.station_name = ttk.Entry(box, width=18)
        self.station_name.insert(0, "Yên Bái")
        self.station_name.grid(row=0, column=3, sticky="w")

        ttk.Label(box, text="Ngày dự báo (YYYY-MM-DD):").grid(row=0, column=4, sticky="w", padx=(12, 0))
        self.forecast_date = ttk.Entry(box, width=12)
        self.forecast_date.insert(0, date.today().isoformat())
        self.forecast_date.grid(row=0, column=5, sticky="w")

    # ----- table backbone: thời gian / trường dữ liệu / bucket ----------
    def _build_table_section(self, parent):
        box = ttk.LabelFrame(parent, text="Bảng thời gian - trường dữ liệu - bucket dự báo", padding=8)
        box.pack(fill="both", expand=True, pady=(0, 8))

        toolbar = ttk.Frame(box)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="+ Thêm dòng", command=self.editor.load_new).pack(side="left")
        ttk.Button(toolbar, text="Sửa dòng", command=self._edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Xóa dòng", command=self._delete_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Nhập CSV...", command=self._import_from_file).pack(side="left", padx=(6, 0))

        table_frame = ttk.Frame(box)
        table_frame.pack(fill="both", expand=True, pady=(6, 0))

        columns = ("time", "field", "value")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  height=10, selectmode="browse")
        self.tree.heading("time", text="Thời gian")
        self.tree.heading("field", text="Trường dữ liệu")
        self.tree.heading("value", text="Bucket đã chọn")
        self.tree.column("time", width=90, anchor="w")
        self.tree.column("field", width=180, anchor="w")
        self.tree.column("value", width=380, anchor="w")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

    def _selected_row_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _find_row(self, row_id):
        return next((r for r in self.rows if r["_id"] == row_id), None)

    def _selected_row_id_or_warn(self):
        row_id = self._selected_row_id()
        if row_id is None:
            messagebox.showinfo("Chưa chọn dòng", "Hãy chọn một dòng trong bảng trước.")
        return row_id

    def _edit_selected(self):
        row_id = self._selected_row_id_or_warn()
        if row_id is not None:
            self.editor.load_row(self._find_row(row_id))

    def _delete_selected(self):
        row_id = self._selected_row_id_or_warn()
        if row_id is None:
            return
        self.rows = [r for r in self.rows if r["_id"] != row_id]
        if self.editor.editing_id == row_id:
            self.editor.load_new()
        self._refresh_table()

    def _on_editor_save(self, row_dict: dict, editing_id):
        if editing_id is None:
            self._on_row_added(row_dict)
        else:
            self._on_row_edited(editing_id, row_dict)

    def _on_row_added(self, row: dict):
        row["_id"] = self._next_id
        self._next_id += 1
        self.rows.append(row)
        self._refresh_table()

    def _on_row_edited(self, row_id, new_row: dict):
        new_row["_id"] = row_id
        self.rows = [new_row if r["_id"] == row_id else r for r in self.rows]
        self._refresh_table()

    def _refresh_table(self):
        self.rows.sort(key=lambda r: (r["start"], FIELD_LABELS[r["field"]]))
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            time_str = f"{r['start']:02d}-{r['end']:02d}"
            self.tree.insert("", "end", iid=str(r["_id"]),
                              values=(time_str, FIELD_LABELS[r["field"]], row_value_str(r)))

    def _import_from_file(self):
        path = filedialog.askopenfilename(
            title="Nhập CSV dự báo",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                records = list(csv.DictReader(f))
            meta, imported_rows, warnings = import_csv_rows(records)
        except (ValueError, OSError) as e:
            messagebox.showerror("Không nhập được CSV", str(e))
            return

        if self.rows and not messagebox.askyesno(
                "Ghi đè dữ liệu hiện tại?",
                f"Bảng hiện có {len(self.rows)} dòng. Nhập CSV sẽ THAY THẾ toàn bộ. Tiếp tục?"):
            return

        self.station_code.delete(0, "end")
        self.station_code.insert(0, meta["station_code"])
        self.station_name.delete(0, "end")
        self.station_name.insert(0, meta["station_name"])
        self.forecast_date.delete(0, "end")
        self.forecast_date.insert(0, meta["date"])

        self.rows = []
        self._next_id = 1
        for r in imported_rows:
            r["_id"] = self._next_id
            self._next_id += 1
            self.rows.append(r)
        self._refresh_table()

        msg = f"Đã nhập {len(imported_rows)} dòng từ:\n{path}"
        if warnings:
            shown = warnings[:20]
            msg += f"\n\n{len(warnings)} cảnh báo (đã bỏ qua ô lỗi):\n" + "\n".join(shown)
            if len(warnings) > len(shown):
                msg += f"\n... và {len(warnings) - len(shown)} cảnh báo khác."
        messagebox.showinfo("Đã nhập CSV", msg)

    # ----- output: generate csv rows / copy / save -----------------------
    def _build_output_section(self, parent):
        box = ttk.LabelFrame(parent, text="CSV dự báo sinh ra (gộp các dòng theo mốc giờ thay đổi)", padding=8)
        box.pack(fill="both", expand=False)

        btns = ttk.Frame(box)
        btns.pack(fill="x")
        ttk.Button(btns, text="Sinh CSV theo giờ", command=self._generate_all).pack(side="left")
        ttk.Button(btns, text="Chép tất cả", command=self._copy_all).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Lưu vào file...", command=self._save_to_file).pack(side="left", padx=(6, 0))

        self.summary_label = ttk.Label(box, foreground="#374151")
        self.summary_label.pack(anchor="w", pady=(6, 0))

        self.preview_text = tk.Text(box, height=12, wrap="none", font=("Consolas", 9))
        self.preview_text.pack(fill="both", expand=True, pady=(4, 0))
        self.preview_text.config(state="disabled")

    def _meta(self):
        return {
            "station_code": self.station_code.get().strip(),
            "station_name": self.station_name.get().strip(),
            "date": self.forecast_date.get().strip(),
        }

    def _generate_all(self):
        if not self.rows:
            messagebox.showinfo("Chưa có dòng", "Hãy thêm ít nhất một dòng trong bảng.")
            return
        meta = self._meta()

        rows, all_missing = [], []
        for h in covered_hours(self.rows):
            state = merge_at_hour(self.rows, h)
            row, missing = csv_row_for_hour(state, meta, h)
            rows.append(row)
            if missing:
                missing_labels = ", ".join(FIELD_LABELS[k] for k in missing)
                all_missing.append(f"{h:02d}h: thiếu {missing_labels}")

        self._last_rows = rows
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", buf.getvalue())
        self.preview_text.config(state="disabled")

        self.summary_label.config(
            text=f"Đã sinh {len(rows)} dòng (giờ {rows[0]['hour']}-{rows[-1]['hour']}). "
                 f"{len(all_missing)} giờ còn thiếu ít nhất 1 trường.")
        if all_missing:
            messagebox.showwarning("Một số giờ còn thiếu trường", "\n".join(all_missing))

    def _copy_all(self):
        if not self._last_rows:
            messagebox.showwarning("Chưa có CSV", "Hãy bấm 'Sinh CSV theo giờ' trước.")
            return
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(self._last_rows)
        self.root.clipboard_clear()
        self.root.clipboard_append(buf.getvalue())

    def _save_to_file(self):
        if not self._last_rows:
            messagebox.showwarning("Chưa có CSV", "Hãy bấm 'Sinh CSV theo giờ' trước.")
            return
        path = filedialog.asksaveasfilename(
            title="Lưu vào file CSV dự báo",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        # Cùng quy ước với csv_pipeline.write_csv(): utf-8-sig + DictWriter.
        # Nối vào file đã có (không ghi lại header) để gộp nhiều phiên làm
        # việc thành 1 file forecasts.csv dần lớn dần, giống cách
        # bulletin_generator.py append vào file .txt.
        file_exists = os.path.isfile(path) and os.path.getsize(path) > 0
        with open(path, "a" if file_exists else "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerows(self._last_rows)
        messagebox.showinfo("Đã lưu", f"Đã thêm {len(self._last_rows)} dòng vào:\n{path}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
