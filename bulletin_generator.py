"""
bulletin_generator.py
====================
Standalone Tkinter tool that generates synthetic raw "Qt..." bulletin
records — the reverse of decode.py — for testing without needing a real
FTP download.

The backbone is a table of Thời gian / Trường dữ liệu / Giá trị: each row
says "field F holds value V from giờ START to giờ END, both included" for
the (single, fixed) station entered at the top. Rows can be added, edited
(double-click, or "Sửa dòng") and deleted freely. Editing happens in the
"Thêm / sửa dòng" panel docked on the right — always visible, not a popup.

"Sinh tất cả mã" merges the rows into one record per hour (see
_covered_hours/_merge_at_hour for the merge rule) and decodes each one back
for a live sanity preview. "Lưu vào file..." appends the generated records
to a .txt file, so you can feed it into the same decode pipeline used for
real downloads to sanity-check against a hand-built time series.

Standalone — does not import gui.py/pipeline_csv.py/config.py, does not touch FTP
or the app's config. Run:  python bulletin_generator.py
"""

import json
import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from bulletin.decode import decode_record, vv_value, hshs_value
from bulletin.encode import encode_record
from bulletin.code_tables import TABLES


def _code_desc_values(table: dict) -> list:
    """'code — description' strings for a Combobox, in table order."""
    return [f"{code} — {desc}" for code, desc in table.items()]


def _code_from_selection(text: str) -> str:
    return text.split(" — ", 1)[0].strip()


def _select_code(combo: ttk.Combobox, table: dict, code: str):
    """Point a 'code — desc' Combobox at the entry whose code matches."""
    for i, k in enumerate(table.keys()):
        if k == code:
            combo.current(i)
            return
    combo.current(0)


def _set_text(widget: tk.Text, text: str):
    widget.config(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.config(state="disabled")


# =============================================================================
# FIELD REGISTRY — one entry per selectable "trường dữ liệu". Each builder
# creates the value-editing widget(s) for that field inside a given parent
# and returns (widget, get() -> value, set(value)) so RowEditorPanel can stay
# generic across every field type (code lookups, floats, composite cloud).
# =============================================================================

def _build_code_field(table: dict, width: int = 30):
    def builder(parent):
        cb = ttk.Combobox(parent, width=width, state="readonly",
                           values=_code_desc_values(table))
        cb.current(0)
        cb.pack(anchor="w")

        def get():
            return _code_from_selection(cb.get())

        def set_(code):
            _select_code(cb, table, code)

        return cb, get, set_
    return builder


def _build_float_field(width: int = 10):
    def builder(parent):
        e = ttk.Entry(parent, width=width)
        e.pack(anchor="w")

        def get():
            return float(e.get())

        def set_(v):
            e.delete(0, "end")
            e.insert(0, str(v))

        return e, get, set_
    return builder


def _build_spinbox_field(to: int, increment: int = 1, width: int = 8):
    def builder(parent):
        sp = ttk.Spinbox(parent, from_=0, to=to, increment=increment, width=width)
        sp.set(0)
        sp.pack(anchor="w")

        def get():
            return float(sp.get())

        def set_(v):
            sp.set(v)

        return sp, get, set_
    return builder


def _build_vv_field(parent):
    frame = ttk.Frame(parent)
    sp = ttk.Spinbox(frame, from_=0, to=99, width=6)
    sp.set(0)
    sp.pack(side="left")
    preview = ttk.Label(frame, foreground="#6b7280")
    preview.pack(side="left", padx=(6, 0))

    def _update_preview(*_):
        v = vv_value(f"{int(sp.get() or 0):02d}", TABLES)
        preview.config(text=f"\u2248 {v} km" if v is not None else "không xác định")

    sp.config(command=_update_preview)
    sp.bind("<KeyRelease>", _update_preview)
    _update_preview()

    def get():
        return f"{int(sp.get()):02d}"

    def set_(code):
        sp.set(int(code))
        _update_preview()

    return frame, get, set_


def _build_cloud_field(parent):
    frame = ttk.Frame(parent)
    N = ttk.Combobox(frame, width=6, state="readonly", values=_code_desc_values(TABLES["N_oktas"]))
    N.current(0)
    N.pack(side="left", padx=2)
    C = ttk.Combobox(frame, width=10, state="readonly", values=_code_desc_values(TABLES["cloud_type"]))
    C.current(0)
    C.pack(side="left", padx=2)
    hshs = ttk.Entry(frame, width=5)
    hshs.insert(0, "00")
    hshs.pack(side="left", padx=2)
    preview = ttk.Label(frame, foreground="#6b7280")
    preview.pack(side="left", padx=(6, 2))

    def _update_preview(*_):
        h = hshs_value(hshs.get().strip(), TABLES)
        preview.config(text=f"\u2248 {h} m" if h is not None else "mã không hợp lệ")

    hshs.bind("<KeyRelease>", _update_preview)
    _update_preview()

    def get():
        return {"N": _code_from_selection(N.get()), "C": _code_from_selection(C.get()),
                "hshs": hshs.get().strip()}

    def set_(v):
        _select_code(N, TABLES["N_oktas"], v["N"])
        _select_code(C, TABLES["cloud_type"], v["C"])
        hshs.delete(0, "end")
        hshs.insert(0, v["hshs"])
        _update_preview()

    return frame, get, set_


FIELD_DEFS = {
    "wind_dd": {"label": "Hướng gió (độ)", "builder": _build_spinbox_field(360, increment=10), "default": 0.0},
    "wind_ff": {"label": "Tốc độ gió", "builder": _build_spinbox_field(99), "default": 0.0},
    "N_total": {"label": "Mây tổng lượng (N)", "builder": _build_code_field(TABLES["N_oktas"], 20), "default": "0"},
    "vv":      {"label": "Tầm nhìn xa (VV)", "builder": _build_vv_field, "default": "00"},
    "temp":    {"label": "Nhiệt độ (°C)", "builder": _build_float_field(), "default": 28.5},
    "dew":     {"label": "Điểm sương (°C)", "builder": _build_float_field(), "default": 24.1},
    "ww":      {"label": "Thời tiết hiện tại", "builder": _build_code_field(TABLES["ww"], 32), "default": "00"},
    "w1":      {"label": "Thời tiết đã qua 1", "builder": _build_code_field(TABLES["W1W2"], 22), "default": "0"},
    "w2":      {"label": "Thời tiết đã qua 2", "builder": _build_code_field(TABLES["W1W2"], 22), "default": "0"},
    "pressure": {"label": "Áp suất (mmHg)", "builder": _build_float_field(), "default": 754.0},
    "cloud1":  {"label": "Mây — lớp 1", "builder": _build_cloud_field, "default": {"N": "0", "C": "0", "hshs": "00"}},
    "cloud2":  {"label": "Mây — lớp 2", "builder": _build_cloud_field, "default": {"N": "0", "C": "0", "hshs": "00"}},
    "cloud3":  {"label": "Mây — lớp 3", "builder": _build_cloud_field, "default": {"N": "0", "C": "0", "hshs": "00"}},
    "cloud4":  {"label": "Mây — lớp 4", "builder": _build_cloud_field, "default": {"N": "0", "C": "0", "hshs": "00"}},
}

CLOUD_FIELD_KEYS = ("cloud1", "cloud2", "cloud3", "cloud4")


def _field_key_from_label(label: str):
    for k, d in FIELD_DEFS.items():
        if d["label"] == label:
            return k
    return None


def _row_value_str(row: dict) -> str:
    key, v = row["field"], row["value"]
    if key in CLOUD_FIELD_KEYS:
        h = hshs_value(v["hshs"], TABLES)
        return (f"N={TABLES['N_oktas'].get(v['N'], v['N'])} "
                f"{TABLES['cloud_type'].get(v['C'], v['C'])} "
                f"h\u2248{h}m" if h is not None else f"hshs={v['hshs']}")
    if key == "N_total":
        return f"{v} — {TABLES['N_oktas'].get(v, '?')}"
    if key == "vv":
        km = vv_value(v, TABLES)
        return f"{v} (\u2248{km} km)" if km is not None else v
    if key == "ww":
        return f"{v} — {TABLES['ww'].get(v, '?')}"
    if key in ("w1", "w2"):
        return f"{v} — {TABLES['W1W2'].get(v, '?')}"
    if key == "wind_dd":
        return f"{v:.0f}\u00b0"
    if key == "wind_ff":
        return f"{v:.0f}"
    if key in ("temp", "dew"):
        return f"{v}\u00b0C"
    if key == "pressure":
        return f"{v} mmHg"
    return str(v)


def _covered_hours(rows: list) -> list:
    """Every hour any row's [start, end] range touches (both ends included)
    — a mã gets generated per HOUR, not once per row: a "07–09" row covers
    hours 07, 08 AND 09, each getting its own record (the format is
    inherently hourly)."""
    hours = set()
    for r in rows:
        hours.update(range(r["start"], r["end"] + 1))
    return sorted(hours)


def _merge_at_hour(rows: list, hour: int) -> dict:
    """One value per field: among rows covering `hour` ([start, end], both
    ends included), the one with the latest start wins (rows are pre-sorted
    by start ascending, so later-in-list overwrites earlier on a tie/overlap)."""
    state = {}
    for r in sorted(rows, key=lambda r: r["start"]):
        if r["start"] <= hour <= r["end"]:
            state[r["field"]] = r["value"]
    return state


def _encode_state(state: dict, station_code: str, lat: float, lon: float, station_name: str) -> str:
    clouds = [state[k] for k in CLOUD_FIELD_KEYS if k in state]
    return encode_record(
        station_code=station_code, lat=lat, lon=lon,
        vv_code=state.get("vv", "00"),
        total_cloud_N_code=state.get("N_total", "0"),
        wind_dd=state.get("wind_dd", 0.0),
        wind_ff=state.get("wind_ff", 0.0),
        temp_c=state.get("temp"),
        dew_c=state.get("dew"),
        ww_code=state.get("ww"),
        w1_code=state.get("w1", "/"),
        w2_code=state.get("w2", "/"),
        clouds=clouds,
        pressure_mmhg=state.get("pressure"),
        station_name=station_name,
    )


class RowEditorPanel(ttk.Frame):
    """Always-visible sidebar (not a popup) for adding/editing one Thời
    gian+Trường dữ liệu+Giá trị row — one field, one value, one [start, end]
    hour range (both ends included).

    load_new() resets it to "add a row" mode; load_row(row) switches it to
    "edit this row" mode. Either way, Lưu dòng calls
    on_save(row_dict, editing_id) — editing_id is None for a new row, or the
    _id of the row being replaced — and then resets back to add-mode so the
    panel is immediately ready for the next row."""

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

        field_box = ttk.LabelFrame(self, text="Trường dữ liệu & giá trị", padding=8)
        field_box.pack(fill="x", pady=(8, 0))
        ttk.Label(field_box, text="Trường:").pack(anchor="w")
        self.field_var = tk.StringVar()
        self.field_combo = ttk.Combobox(field_box, state="readonly", textvariable=self.field_var,
                                         values=[d["label"] for d in FIELD_DEFS.values()], width=26)
        self.field_combo.pack(anchor="w", pady=(0, 6), fill="x")
        self.field_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_value_widget())

        ttk.Label(field_box, text="Giá trị:").pack(anchor="w")
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
        key = _field_key_from_label(self.field_var.get())
        widget, get, set_ = FIELD_DEFS[key]["builder"](self.value_container)
        widget.pack(anchor="w")
        self._value_get = get
        set_(initial if initial is not None else FIELD_DEFS[key]["default"])

    def load_new(self):
        """Reset the panel to add-a-new-row mode."""
        self.editing_id = None
        self.mode_label.config(text="+ Thêm dòng mới")
        self.start_hour.current(7)
        self.end_hour.current(9)
        self.field_var.set(next(iter(FIELD_DEFS.values()))["label"])
        self._rebuild_value_widget()

    def load_row(self, row: dict):
        """Switch the panel to edit-this-row mode, prefilled from `row`."""
        self.editing_id = row["_id"]
        self.mode_label.config(
            text=f"Đang sửa: {row['start']:02d}–{row['end']:02d} — "
                 f"{FIELD_DEFS[row['field']]['label']}")
        self.start_hour.set(f"{row['start']:02d}")
        self.end_hour.set(f"{row['end']:02d}")
        self.field_var.set(FIELD_DEFS[row["field"]]["label"])
        self._rebuild_value_widget(initial=row["value"])

    def _save(self):
        try:
            start = int(self.start_hour.get())
            end = int(self.end_hour.get())
            if end < start:
                raise ValueError("giờ kết thúc phải lớn hơn hoặc bằng giờ bắt đầu")
            key = _field_key_from_label(self.field_var.get())
            value = self._value_get()
        except ValueError as e:
            messagebox.showerror("Không lưu được dòng", str(e))
            return
        self.on_save({"start": start, "end": end, "field": key, "value": value}, self.editing_id)
        self.load_new()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sinh mã bulletin theo dòng thời gian (dựa trên bulletin_generator.py)")
        root.minsize(1020, 640)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.isfile(icon_path):
            try:
                root.iconbitmap(icon_path)
            except tk.TclError:
                pass

        self.rows = []      # list of {"_id", "start", "end", "field", "value"}
        self._next_id = 1
        self._last_lines = []  # raw records from the last "Sinh tất cả mã", in hour order

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

    # ----- station (global, applies to every generated mã) --------------
    def _build_station_section(self, parent):
        box = ttk.LabelFrame(parent, text="Trạm & vị trí (áp dụng cho mọi mã)", padding=8)
        box.pack(fill="x", pady=(0, 8))

        ttk.Label(box, text="Trạm (mã, vd k31):").grid(row=0, column=0, sticky="w")
        self.station = ttk.Entry(box, width=18)
        self.station.insert(0, "k31")
        self.station.grid(row=0, column=1, sticky="w")

        ttk.Label(box, text="Vĩ độ:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.lat = ttk.Entry(box, width=10)
        self.lat.insert(0, "21.7")
        self.lat.grid(row=0, column=3, sticky="w")

        ttk.Label(box, text="Kinh độ:").grid(row=0, column=4, sticky="w", padx=(12, 0))
        self.lon = ttk.Entry(box, width=10)
        self.lon.insert(0, "104.85")
        self.lon.grid(row=0, column=5, sticky="w")

        ttk.Label(box, text="Tên trạm (in trong mã):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.station_name = ttk.Entry(box, width=18)
        self.station_name.insert(0, "Yên Bái")
        self.station_name.grid(row=1, column=1, sticky="w", pady=(4, 0))

    # ----- table backbone: thời gian / trường dữ liệu / giá trị ---------
    def _build_table_section(self, parent):
        box = ttk.LabelFrame(parent, text="Bảng thời gian — trường dữ liệu — giá trị", padding=8)
        box.pack(fill="both", expand=True, pady=(0, 8))

        toolbar = ttk.Frame(box)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="+ Thêm dòng", command=self.editor.load_new).pack(side="left")
        ttk.Button(toolbar, text="Sửa dòng", command=self._edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Xóa dòng", command=self._delete_selected).pack(side="left", padx=(6, 0))

        table_frame = ttk.Frame(box)
        table_frame.pack(fill="both", expand=True, pady=(6, 0))

        columns = ("time", "field", "value")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  height=10, selectmode="browse")
        self.tree.heading("time", text="Thời gian")
        self.tree.heading("field", text="Trường dữ liệu")
        self.tree.heading("value", text="Giá trị")
        self.tree.column("time", width=90, anchor="w")
        self.tree.column("field", width=200, anchor="w")
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

    def _station_ctx(self):
        return {
            "station_code": self.station.get().strip(),
            "lat": self.lat.get().strip(),
            "lon": self.lon.get().strip(),
            "station_name": self.station_name.get().strip(),
        }

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
            self.editor.load_new()  # was editing the row that just got deleted
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
        self.rows.sort(key=lambda r: (r["start"], FIELD_DEFS[r["field"]]["label"]))
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            time_str = f"{r['start']:02d}\u2013{r['end']:02d}"
            self.tree.insert("", "end", iid=str(r["_id"]),
                              values=(time_str, FIELD_DEFS[r["field"]]["label"], _row_value_str(r)))

    # ----- output: generate all / copy / save ----------------------------
    def _build_output_section(self, parent):
        box = ttk.LabelFrame(parent, text="Mã sinh ra (gộp các dòng theo mốc giờ thay đổi)", padding=8)
        box.pack(fill="both", expand=False)

        btns = ttk.Frame(box)
        btns.pack(fill="x")
        ttk.Button(btns, text="Sinh tất cả mã", command=self._generate_all).pack(side="left")
        ttk.Button(btns, text="Chép tất cả", command=self._copy_all).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Lưu vào file...", command=self._save_to_file).pack(side="left", padx=(6, 0))

        self.raw_text = tk.Text(box, height=5, wrap="word", font=("Consolas", 10))
        self.raw_text.pack(fill="x", pady=(6, 4))
        self.raw_text.config(state="disabled")

        self.preview_text = tk.Text(box, height=8, wrap="word", font=("Consolas", 9))
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.config(state="disabled")

    def _generate_all(self):
        if not self.rows:
            messagebox.showinfo("Chưa có dòng", "Hãy thêm ít nhất một dòng trong bảng.")
            return
        ctx = self._station_ctx()
        try:
            lat = float(ctx["lat"])
            lon = float(ctx["lon"])
        except ValueError:
            messagebox.showerror("Lỗi", "Vĩ độ/kinh độ trạm không hợp lệ.")
            return

        display_lines, raw_lines, decoded_all, errors = [], [], [], []
        for h in _covered_hours(self.rows):
            state = _merge_at_hour(self.rows, h)
            try:
                raw = _encode_state(state, ctx["station_code"], lat, lon, ctx["station_name"])
            except ValueError as e:
                errors.append(f"{h:02d}h: {e}")
                continue
            display_lines.append(f"[{h:02d}h] {raw}")
            raw_lines.append(raw)
            decoded_all.append({"hour": f"{h:02d}h", **decode_record(raw)})

        self._last_lines = raw_lines
        _set_text(self.raw_text, "\n".join(display_lines) if display_lines else "(không có mã nào được sinh)")
        _set_text(self.preview_text, json.dumps(decoded_all, ensure_ascii=False, indent=2))
        if errors:
            messagebox.showwarning("Một số mốc giờ lỗi", "\n".join(errors))

    def _copy_all(self):
        if not self._last_lines:
            messagebox.showwarning("Chưa có mã", "Hãy bấm 'Sinh tất cả mã' trước.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(self._last_lines))

    def _save_to_file(self):
        if not self._last_lines:
            messagebox.showwarning("Chưa có mã", "Hãy bấm 'Sinh tất cả mã' trước.")
            return
        path = filedialog.asksaveasfilename(
            title="Lưu vào file bulletin",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        # ';'-terminated to match the format the decoder expects when reading it back.
        with open(path, "a", encoding="utf-8") as f:
            for raw in self._last_lines:
                f.write(raw + ";")
        messagebox.showinfo("Đã lưu", f"Đã thêm {len(self._last_lines)} bản ghi vào:\n{path}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
