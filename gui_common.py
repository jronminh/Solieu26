"""
gui_common.py
====================
Constants + small OS-integration helpers shared across the GUI modules. No
Tkinter App state lives here (only the stdlib `tkinter` messagebox, used by
report_open) — keeps this module import-safe from all of them without any
risk of a circular import.
"""

import os
import re
import subprocess
import sys
from tkinter import messagebox


# =============================================================================
# LOG COLORS — Tkinter Text tag color per log level (INFO/OK/SKIP/MISS/WARN/ERR/ACT)
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
# Feeds the station filter dropdown in the "Xem lịch sử" viewer (each history_*.csv
# holds every station already — the dropdown just filters rows client-side, it no
# longer drives what gets downloaded/decoded). Add/remove a station by editing this table.
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

# Names feed the dropdown — order KEPT the same as the STATIONS table above;
# also builds the reverse lookup name → code.
STATION_NAMES = list(STATIONS.values())
NAME_TO_CODE  = {name: code for code, name in STATIONS.items()}

ALL_STATIONS = "Tất cả các trạm"   # station-filter dropdown option that disables filtering

# Hours feed the hour-filter dropdown in the "Xem lịch sử" viewer — each
# history_*.csv's "hour" column is a zero-padded string ("00".."23"), so the
# dropdown values match.
HOURS = [f"{h:02d}" for h in range(24)]
ALL_HOURS = "Tất cả các giờ"   # hour-filter dropdown option that disables filtering

# Matches the per-day history CSV filenames this app writes (one file per day).
# The viewer's Ngày dropdown lists dates found this way and picks which file to
# load, rather than filtering rows within a single file.
HISTORY_CSV_RE = re.compile(r"^history_(\d{8})\.csv$")


# Numeric columns in the CSV viewer — right-aligned + compared as NUMBERS when
# sorting (instead of as strings). *_hshs columns are numeric too but their names
# aren't fixed (cloud_1_hshs, cloud_2_hshs...) so they're detected by suffix instead
# of being listed here.
NUMERIC_VIEWER_COLUMNS = {
    "lat", "lon", "visibility_km", "total_cloud_N", "wind_dd_deg",
    "wind_ff", "temperature_c", "dewpoint_c", "pressure_hpa",
    "cloud_layers", "hour",
}

# Columns that never appear in the CSV viewer — not shown in either mode, and
# not offered in the "Hiển thị" picker either, so they can't be toggled back on
# from the GUI. They stay in the exported CSV file untouched; the only way to
# see them is opening a history_*.csv file directly (e.g. in Excel).
ALWAYS_HIDDEN_VIEWER_COLUMNS = {
    "date", "hour", "source_file", "station_code", "lat", "lon", "cloud_layers",
}


def _is_numeric_viewer_column(col: str) -> bool:
    """*_hshs columns are numeric too, but their names aren't fixed
    (cloud_1_hshs, cloud_2_hshs...), so they're matched by suffix instead of
    being listed in NUMERIC_VIEWER_COLUMNS."""
    return col in NUMERIC_VIEWER_COLUMNS or col.endswith("_hshs")


def _os_open(path: str):
    """Hand `path` to the OS's default handler — file manager for a folder, the
    associated app for a file. Returns (ok: bool, reason/path)."""
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


def open_folder(path: str):
    """Open a folder with the OS's file manager. Returns (ok: bool, reason/path)."""
    if not path:
        return False, "chưa có thư mục xuất (cần chạy thành công ít nhất một lần)"
    path = os.path.abspath(path)                      # './x' → absolute (Windows dislikes relative paths)
    if not os.path.isdir(path):
        return False, f"thư mục không tồn tại: {path}"
    return _os_open(path)


def open_in_editor(path: str):
    """Open a FILE with its default application (for editing). Returns (ok, reason/path)."""
    if not path:
        return False, "chưa có đường dẫn file"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, f"file không tồn tại: {path}"
    return _os_open(path)


def report_open(log, ok: bool, info: str, what: str = None, warn: bool = False):
    """Log the result of an open_folder()/open_in_editor() call in the standard
    'Đã mở <what>: ...' / 'Không mở được <what>: ...' shape; optionally also
    pop a warning dialog on failure. `log` is the caller's App._log callback."""
    suffix = f" {what}" if what else ""
    if ok:
        log("OK", f"Đã mở{suffix}: {info}")
    else:
        log("ERR", f"Không mở được{suffix}: {info}")
        if warn:
            messagebox.showwarning("Không mở được", info)
