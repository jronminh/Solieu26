"""
forecast_bucket_generator.py — FILE THAM KHẢO, KHÔNG CHẠY ĐƯỢC
====================
Archived 2026-08-18: its logic module `pipeline_forecast.py` (the imports
below) was deleted after `scoring/score_tables.py` dropped the "kind" field
its dispatch depended on and the tool was judged not worth fixing — it had
never been integrated into gui.py/dialogs.py anyway (see TODO.md). Kept here
only as a design reference for the widget layout / CRUD shape when stage 2
("Dự báo") of the scoring pipeline gets a real UI.

Standalone Tkinter tool that lets a dự báo viên (forecaster) pick a bucket
for each of the 6 scored fields over a time range, and exports the result
to CSV - a hand-built stand-in for the "Dự báo" stage of the scoring
pipeline, which has no other UI yet (see TODO.md).

GUI vs helper split: this file is Tkinter ONLY - every non-widget rule
(bucket labels, hour-range merge, CSV shape/import/export, record CRUD)
lives in a separate logic module and is imported here, not reimplemented.
This file only adds: 4 widget-builder functions (one per bucket "kind")
that wrap a logic label-list in a Combobox, and the RowEditorPanel/App
classes that wire widgets to the imported CRUD functions.

Data model: the whole program is 1 micro-database - a list of dicts
{start_hour, end_hour, data_name, bucket_selected}. This App operates
directly on that list, no separate copy: add/remove/edit all go through
the imported CRUD functions, which take/return a plain list index, not a
synthetic id. The table is never re-sorted, so a row's index stays stable
as long as no row before it is removed.

No station/trạm or ngày dự báo anywhere - the micro-database is scoped to
1 station/1 day implicitly (by whoever is running the tool); the schema
intentionally carries only start_hour/end_hour/data_name/bucket_selected.

Imports only the logic module above and nothing else project-local. Run:
    python forecast_bucket_generator.py
"""

import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from pipeline_forecast import (
    forecast_db,
    FIELD_ORDER, FIELD_LABELS, FIELD_DEFAULTS,
    HUONG_GIO_LABELS, PHENOMENON_MEGA_KEYS, PHENOMENON_MEGA_LABEL_TEXT,
    window_labels, linear_labels, field_key_from_label, bucket_label,
    import_csv, export_csv, add_record, remove_record, edit_record,
)


# =============================================================================
# Widget builders - 1 / kind trong BUCKETS ("forecast_window", "linear",
# "circular", "phenomenon"). Mỗi builder(parent) -> (widget, get() -> bucket
# value, set_(value)) - chỉ đọc nhãn/khóa đã tra sẵn, không tự tính lại gì
# từ BUCKETS.
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
    """Chỉ chọn MEGA (loại hiện tượng). Buổi (sub-bucket) KHÔNG chọn/lưu ở
    đây - nó chỉ được suy sau này, ở tầng chấm điểm, từ cột "hour"."""
    frame = ttk.Frame(parent)
    mega_cb = ttk.Combobox(frame, width=30, state="readonly", values=PHENOMENON_MEGA_LABEL_TEXT)
    mega_cb.current(0)
    mega_cb.pack(anchor="w")
    ttk.Label(frame, text="(buổi suy từ giờ lúc chấm điểm - không chọn ở đây)",
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
# RowEditorPanel - khung thời gian áp dụng + trường dữ liệu + bucket, luôn
# hiện, không phải popup. load_new()/load_row() chuyển đổi mode, Lưu dòng
# gọi on_save(record, editing_index) - editing_index None = thêm mới, số =
# sửa bản ghi tại đúng vị trí đó trong data_base.
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
        self.editing_index = None
        self.mode_label.config(text="+ Thêm dòng mới")
        self.start_hour.current(7)
        self.end_hour.current(9)
        self.field_var.set(FIELD_LABELS[FIELD_ORDER[0]])
        self._rebuild_value_widget()

    def load_row(self, record: dict, index: int):
        self.editing_index = index
        self.mode_label.config(
            text=f"Đang sửa: {record['start_hour']:02d}-{record['end_hour']:02d} - "
                 f"{FIELD_LABELS[record['data_name']]}")
        self.start_hour.set(f"{record['start_hour']:02d}")
        self.end_hour.set(f"{record['end_hour']:02d}")
        self.field_var.set(FIELD_LABELS[record["data_name"]])
        self._rebuild_value_widget(initial=record["bucket_selected"])

    def _save(self):
        key = field_key_from_label(self.field_var.get())
        record = {
            "start_hour": int(self.start_hour.get()),
            "end_hour": int(self.end_hour.get()),
            "data_name": key,
            "bucket_selected": self._value_get(),
        }
        self.on_save(record, self.editing_index)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sinh CSV bucket dự báo (dựa trên bulletin_generator.py)")
        root.minsize(1040, 660)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.isfile(icon_path):
            try:
                root.iconbitmap(icon_path)
            except tk.TclError:
                pass

        self.data_base = forecast_db     # tham chiếu THẲNG micro-database chung
        self._last_result = None         # result trả về từ lần "Xuất CSV..." gần nhất
        self._last_csv_text = None       # nội dung file vừa ghi, để "Chép tất cả" dùng lại

        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)

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

    def _selected_index(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _selected_index_or_warn(self):
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Chưa chọn dòng", "Hãy chọn một dòng trong bảng trước.")
        return index

    def _edit_selected(self):
        index = self._selected_index_or_warn()
        if index is not None:
            self.editor.load_row(self.data_base[index], index)

    def _delete_selected(self):
        index = self._selected_index_or_warn()
        if index is None:
            return
        remove_record(self.data_base, index)
        if self.editor.editing_index == index:
            self.editor.load_new()
        self._refresh_table()

    def _on_editor_save(self, record: dict, editing_index):
        try:
            if editing_index is None:
                add_record(self.data_base, **record)
            else:
                edit_record(self.data_base, editing_index, **record)
        except ValueError as e:
            messagebox.showerror("Không lưu được dòng", str(e))
            return
        self._refresh_table()
        self.editor.load_new()

    def _refresh_table(self):
        # KHÔNG sắp xếp lại - đúng thứ tự thêm vào self.data_base, iid = index
        # hiện tại của dòng đó (luôn khớp vì bảng được dựng lại toàn bộ mỗi lần).
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.data_base):
            time_str = f"{r['start_hour']:02d}-{r['end_hour']:02d}"
            value_str = bucket_label(r["data_name"], r["bucket_selected"])
            self.tree.insert("", "end", iid=str(i),
                              values=(time_str, FIELD_LABELS[r["data_name"]], value_str))

    def _import_from_file(self):
        """Replaces the whole table - the imported file must validate
        strictly (raises on the first bad row) before anything is applied,
        so a rejected import leaves the current table untouched."""
        path = filedialog.askopenfilename(
            title="Nhập CSV dự báo",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            imported = import_csv(path)
        except (ValueError, OSError) as e:
            messagebox.showerror("Không nhập được CSV", str(e))
            return

        if self.data_base and not messagebox.askyesno(
                "Ghi đè dữ liệu hiện tại?",
                f"Bảng hiện có {len(self.data_base)} dòng. Nhập CSV sẽ THAY THẾ toàn bộ. Tiếp tục?"):
            return

        self.data_base[:] = imported
        self._refresh_table()
        messagebox.showinfo("Đã nhập CSV", f"Đã nhập {len(imported)} dòng từ:\n{path}")

    # ----- output: xuất CSV / chép -----------------------------------
    def _build_output_section(self, parent):
        box = ttk.LabelFrame(parent, text="Xuất CSV (gộp các dòng theo mốc giờ thay đổi)", padding=8)
        box.pack(fill="both", expand=False)

        btns = ttk.Frame(box)
        btns.pack(fill="x")
        ttk.Button(btns, text="Xuất CSV...", command=self._export_to_file).pack(side="left")
        ttk.Button(btns, text="Chép tất cả", command=self._copy_all).pack(side="left", padx=(6, 0))

        self.summary_label = ttk.Label(box, foreground="#374151")
        self.summary_label.pack(anchor="w", pady=(6, 0))

        self.preview_text = tk.Text(box, height=12, wrap="none", font=("Consolas", 9))
        self.preview_text.pack(fill="both", expand=True, pady=(4, 0))
        self.preview_text.config(state="disabled")

    def _export_to_file(self):
        """Writes straight to the chosen path - no separate preview step;
        the rows shown afterwards are read-only confirmation of what was
        written, not a proposal to approve."""
        if not self.data_base:
            messagebox.showinfo("Chưa có dòng", "Hãy thêm ít nhất một dòng trong bảng.")
            return
        path = filedialog.asksaveasfilename(
            title="Xuất file CSV dự báo",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return

        result = export_csv(self.data_base, path)
        with open(path, encoding="utf-8-sig") as f:
            self._last_csv_text = f.read()
        self._last_result = result

        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", self._last_csv_text)
        self.preview_text.config(state="disabled")

        self.summary_label.config(
            text=f"Đã xuất {len(result)} dòng (giờ {result[0]['hour']:02d}-{result[-1]['hour']:02d}) vào:\n{path}")
        messagebox.showinfo("Đã xuất CSV", f"Đã ghi {len(result)} dòng vào:\n{path}")

    def _copy_all(self):
        if not self._last_csv_text:
            messagebox.showwarning("Chưa có CSV", "Hãy bấm 'Xuất CSV...' trước.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._last_csv_text)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
