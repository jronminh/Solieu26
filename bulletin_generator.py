"""
bulletin_generator.py
====================
Small standalone Tkinter tool that generates a synthetic raw "Qt..." bulletin
record — the reverse of decode.py — for testing decode.py/pipeline.py without
needing a real FTP download.

Fill in the form, hit "Sinh mã": encode.py assembles the raw token string,
then decode.py immediately decodes it again so you can visually confirm the
round-trip matches what you typed. "Lưu vào file..." appends the record
(';'-terminated) to a .txt file in the same shape decode.get_qt_data() reads,
so you can point gui.py's output folder at it (or feed it straight into
decode.decode_qt_file) to sanity-check the whole pipeline.

Standalone — does not import gui.py/pipeline.py/config.py, does not touch FTP
or the app's config. Run:  python bulletin_generator.py
"""

import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from decode import TABLES, decode_record, _vv_value, _hshs_value
from encode import encode_record
from gui_common import STATIONS, STATION_NAMES, NAME_TO_CODE


def _code_desc_values(table: dict) -> list:
    """'code — description' strings for a Combobox, in table order."""
    return [f"{code} — {desc}" for code, desc in table.items()]


def _code_from_selection(text: str) -> str:
    return text.split(" — ", 1)[0].strip()


class CloudRow:
    """One 'lớp mây' row: N oktas / loại mây / mã hshs + a live height preview."""

    def __init__(self, parent, on_remove):
        self.frame = ttk.Frame(parent)
        self.N = ttk.Combobox(self.frame, width=6, state="readonly",
                               values=_code_desc_values(TABLES["N_oktas"]))
        self.N.current(0)
        self.C = ttk.Combobox(self.frame, width=10, state="readonly",
                               values=_code_desc_values(TABLES["cloud_type"]))
        self.C.current(0)
        self.hshs = ttk.Entry(self.frame, width=5)
        self.hshs.insert(0, "00")
        self.preview = ttk.Label(self.frame, foreground="#6b7280")
        self.N.grid(row=0, column=0, padx=2)
        self.C.grid(row=0, column=1, padx=2)
        self.hshs.grid(row=0, column=2, padx=2)
        self.preview.grid(row=0, column=3, padx=(6, 2), sticky="w")
        ttk.Button(self.frame, text="x", width=2,
                   command=lambda: on_remove(self)).grid(row=0, column=4, padx=2)
        self.hshs.bind("<KeyRelease>", lambda e: self._update_preview())
        self._update_preview()

    def _update_preview(self):
        h = _hshs_value(self.hshs.get().strip(), TABLES)
        self.preview.config(text=f"≈ {h} m" if h is not None else "mã không hợp lệ")

    def to_dict(self):
        return {"N": _code_from_selection(self.N.get()),
                "C": _code_from_selection(self.C.get()),
                "hshs": self.hshs.get().strip()}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sinh mã bulletin (thử nghiệm — đảo ngược decode.py)")
        root.minsize(760, 560)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.isfile(icon_path):
            try:
                root.iconbitmap(icon_path)
            except tk.TclError:
                pass

        self.cloud_rows = []
        self._last_raw = None

        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", anchor="n")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        self._build_station_section(left)
        self._build_wind_vv_section(left)
        self._build_temp_section(left)
        self._build_weather_section(left)
        self._build_cloud_section(left)
        self._build_pressure_section(left)

        ttk.Button(left, text="Sinh mã", command=self._generate).pack(fill="x", pady=(10, 0))

        self._build_output(right)

    # ----- form sections -----------------------------------------------
    def _build_station_section(self, parent):
        box = ttk.LabelFrame(parent, text="Trạm & vị trí", padding=8)
        box.pack(fill="x", pady=(0, 8))

        ttk.Label(box, text="Trạm:").grid(row=0, column=0, sticky="w")
        self.station = ttk.Combobox(box, width=18, state="readonly", values=STATION_NAMES)
        self.station.current(0)
        self.station.grid(row=0, column=1, columnspan=2, sticky="w")
        self.station.bind("<<ComboboxSelected>>", self._on_station_change)

        ttk.Label(box, text="Vĩ độ (độ thập phân):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lat = ttk.Entry(box, width=10)
        self.lat.insert(0, "21.7")
        self.lat.grid(row=1, column=1, sticky="w", pady=(4, 0))

        ttk.Label(box, text="Kinh độ (độ thập phân):").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.lon = ttk.Entry(box, width=10)
        self.lon.insert(0, "104.85")
        self.lon.grid(row=2, column=1, sticky="w", pady=(4, 0))

        ttk.Label(box, text="Tên trạm (in trong mã):").grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.station_name = ttk.Entry(box, width=18)
        self.station_name.grid(row=3, column=1, columnspan=2, sticky="w", pady=(4, 0))
        self._on_station_change()

    def _on_station_change(self, event=None):
        self.station_name.delete(0, "end")
        self.station_name.insert(0, self.station.get())

    def _build_wind_vv_section(self, parent):
        box = ttk.LabelFrame(parent, text="Gió & tầm nhìn xa", padding=8)
        box.pack(fill="x", pady=(0, 8))

        ttk.Label(box, text="Mây tổng lượng (N):").grid(row=0, column=0, sticky="w")
        self.wind_N = ttk.Combobox(box, width=14, state="readonly",
                                    values=_code_desc_values(TABLES["N_oktas"]))
        self.wind_N.current(0)
        self.wind_N.grid(row=0, column=1, sticky="w")

        ttk.Label(box, text="Hướng gió (độ):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.wind_dd = ttk.Spinbox(box, from_=0, to=360, increment=10, width=6)
        self.wind_dd.set(0)
        self.wind_dd.grid(row=1, column=1, sticky="w", pady=(4, 0))

        ttk.Label(box, text="Tốc độ gió:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.wind_ff = ttk.Spinbox(box, from_=0, to=99, width=6)
        self.wind_ff.set(0)
        self.wind_ff.grid(row=2, column=1, sticky="w", pady=(4, 0))

        ttk.Label(box, text="Mã VV (00-99):").grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.vv_code = ttk.Spinbox(box, from_=0, to=99, width=6, command=self._update_vv_preview)
        self.vv_code.set(0)
        self.vv_code.grid(row=3, column=1, sticky="w", pady=(4, 0))
        self.vv_preview = ttk.Label(box, foreground="#6b7280")
        self.vv_preview.grid(row=3, column=2, sticky="w", padx=(6, 0), pady=(4, 0))
        self.vv_code.bind("<KeyRelease>", lambda e: self._update_vv_preview())
        self._update_vv_preview()

    def _update_vv_preview(self):
        v = _vv_value(f"{int(self.vv_code.get() or 0):02d}", TABLES)
        self.vv_preview.config(text=f"≈ {v} km" if v is not None else "không xác định")

    def _build_temp_section(self, parent):
        box = ttk.LabelFrame(parent, text="Nhiệt độ", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Label(box, text="Nhiệt độ (°C):").grid(row=0, column=0, sticky="w")
        self.temp_c = ttk.Entry(box, width=8)
        self.temp_c.insert(0, "28.5")
        self.temp_c.grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="Điểm sương (°C):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.dew_c = ttk.Entry(box, width=8)
        self.dew_c.insert(0, "24.1")
        self.dew_c.grid(row=1, column=1, sticky="w", pady=(4, 0))

    def _build_weather_section(self, parent):
        box = ttk.LabelFrame(parent, text="Thời tiết hiện tại", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Label(box, text="ww:").grid(row=0, column=0, sticky="w")
        self.ww = ttk.Combobox(box, width=28, state="readonly",
                                values=_code_desc_values(TABLES["ww"]))
        self.ww.current(0)
        self.ww.grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="W1:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.w1 = ttk.Combobox(box, width=18, state="readonly",
                                values=_code_desc_values(TABLES["W1W2"]))
        self.w1.current(0)
        self.w1.grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(box, text="W2:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.w2 = ttk.Combobox(box, width=18, state="readonly",
                                values=_code_desc_values(TABLES["W1W2"]))
        self.w2.current(0)
        self.w2.grid(row=2, column=1, sticky="w", pady=(4, 0))

    def _build_cloud_section(self, parent):
        box = ttk.LabelFrame(parent, text="Các lớp mây", padding=8)
        box.pack(fill="x", pady=(0, 8))
        self.cloud_container = ttk.Frame(box)
        self.cloud_container.pack(fill="x")
        ttk.Button(box, text="+ Thêm lớp mây", command=self._add_cloud_row).pack(anchor="w", pady=(4, 0))

    def _add_cloud_row(self):
        if len(self.cloud_rows) >= 4:
            return
        row = CloudRow(self.cloud_container, self._remove_cloud_row)
        row.frame.pack(fill="x", pady=1)
        self.cloud_rows.append(row)

    def _remove_cloud_row(self, row):
        row.frame.destroy()
        self.cloud_rows.remove(row)

    def _build_pressure_section(self, parent):
        box = ttk.LabelFrame(parent, text="Áp suất", padding=8)
        box.pack(fill="x")
        ttk.Label(box, text="Áp suất (hPa):").grid(row=0, column=0, sticky="w")
        self.pressure = ttk.Entry(box, width=10)
        self.pressure.insert(0, "1005.3")
        self.pressure.grid(row=0, column=1, sticky="w")

    def _build_output(self, parent):
        ttk.Label(parent, text="Mã sinh ra (raw record):").pack(anchor="w")
        self.raw_text = tk.Text(parent, height=3, wrap="word", font=("Consolas", 10))
        self.raw_text.pack(fill="x", pady=(2, 8))
        self.raw_text.config(state="disabled")

        btns = ttk.Frame(parent)
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="Chép mã", command=self._copy_raw).pack(side="left")
        ttk.Button(btns, text="Lưu vào file...", command=self._save_to_file).pack(side="left", padx=(6, 0))

        ttk.Label(parent, text="Giải mã lại để kiểm tra (decode.py):").pack(anchor="w")
        self.preview_text = tk.Text(parent, wrap="word", font=("Consolas", 9))
        self.preview_text.pack(fill="both", expand=True, pady=(2, 0))
        self.preview_text.config(state="disabled")

    # ----- actions --------------------------------------------------------
    def _generate(self):
        try:
            station_code = NAME_TO_CODE[self.station.get()]
            raw = encode_record(
                station_code=station_code,
                lat=float(self.lat.get()),
                lon=float(self.lon.get()),
                vv_code=self.vv_code.get(),
                wind_N_code=_code_from_selection(self.wind_N.get()),
                wind_dd=float(self.wind_dd.get()),
                wind_ff=float(self.wind_ff.get()),
                temp_c=float(self.temp_c.get()) if self.temp_c.get().strip() else None,
                dew_c=float(self.dew_c.get()) if self.dew_c.get().strip() else None,
                ww_code=_code_from_selection(self.ww.get()),
                w1_code=_code_from_selection(self.w1.get()),
                w2_code=_code_from_selection(self.w2.get()),
                clouds=[row.to_dict() for row in self.cloud_rows],
                pressure_hpa=float(self.pressure.get()) if self.pressure.get().strip() else None,
                station_name=self.station_name.get().strip(),
            )
        except ValueError as e:
            messagebox.showerror("Không sinh được mã", str(e))
            return

        self._last_raw = raw
        self._set_text(self.raw_text, raw)

        decoded = decode_record(raw)
        import json
        self._set_text(self.preview_text, json.dumps(decoded, ensure_ascii=False, indent=2))

    @staticmethod
    def _set_text(widget: tk.Text, text: str):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")

    def _copy_raw(self):
        if not self._last_raw:
            messagebox.showwarning("Chưa có mã", "Hãy bấm 'Sinh mã' trước.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._last_raw)

    def _save_to_file(self):
        if not self._last_raw:
            messagebox.showwarning("Chưa có mã", "Hãy bấm 'Sinh mã' trước.")
            return
        path = filedialog.asksaveasfilename(
            title="Lưu vào file bulletin",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        # ';'-terminated so decode.get_qt_data() (data.split(';')[:-1]) reads it back.
        with open(path, "a", encoding="utf-8") as f:
            f.write(self._last_raw + ";")
        messagebox.showinfo("Đã lưu", f"Đã thêm bản ghi vào:\n{path}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
