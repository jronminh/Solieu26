"""
forecast_bucket_logic.py
====================
Pure logic behind forecast_bucket_generator.py's Tkinter GUI - no tkinter
import anywhere in this file. Everything here is plain data + functions over
dicts/lists: the 6-field bucket registry (labels, defaults, valid ranges),
the hour-range row model (covered_hours/merge_at_hour), the per-hour CSV
shape (csv_row_for_hour), and CSV import (collapse_to_ranges/import_csv_rows).

Split out on purpose so this can be imported repeatedly wherever the scoring
pipeline in TODO.md ("Nối buckets.py vào pipeline") needs it next - a
headless script, a future pipeline module, tests - without dragging a
tkinter dependency along for the ride. forecast_bucket_generator.py imports
this module for all of its non-widget logic; it does not duplicate any of it.

Only depends on buckets.py.
"""

from buckets import BUCKETS, sub_of_hour

INF = float("inf")


# =============================================================================
# Nhãn bucket - suy từ chính BUCKETS (không hardcode) để luôn khớp chỉ số
# với bucket_of()/score_field() bên buckets.py.
# =============================================================================

def window_labels(field: str) -> list:
    labels = []
    for lo, hi in BUCKETS[field]["windows"]:
        labels.append(f"{lo}+ tro len" if hi == INF else f"{lo}-{hi}")
    return labels


def linear_labels(field: str) -> list:
    spec = BUCKETS[field]
    bounds = spec["bounds"]
    labels = [f"<{bounds[0]}"]
    labels += [f"{bounds[i]}-{bounds[i + 1]}" for i in range(len(bounds) - 1)]
    labels.append(f">{bounds[-1]}")
    if spec.get("no_ceiling") is not None:
        labels.append(f"{spec['no_ceiling']} (không có trần)")
    return labels


def valid_index_count(field: str) -> int:
    kind = BUCKETS[field]["kind"]
    if kind == "forecast_window":
        return len(BUCKETS[field]["windows"])
    if kind == "linear":
        return len(linear_labels(field))
    if kind == "circular":
        return BUCKETS[field]["n"]
    raise ValueError(f"valid_index_count không áp cho kind={kind!r}")


HUONG_GIO_LABELS = BUCKETS["huong_gio"]["labels"]
PHENOMENON_MEGA_KEYS = BUCKETS["hien_tuong"]["mega_buckets"]
PHENOMENON_MEGA_LABEL_TEXT = [BUCKETS["hien_tuong"]["mega_labels"][k] for k in PHENOMENON_MEGA_KEYS]


# =============================================================================
# FIELD REGISTRY - dữ liệu thuần cho 6 trường được chấm (nhãn + bucket mặc
# định khi thêm dòng mới). forecast_bucket_generator.py tự ghép thêm 1
# widget-builder GUI cho mỗi field_key - KHÔNG đặt builder ở đây.
# =============================================================================

FIELD_ORDER = ["tong_luong_may", "do_cao_man_may", "hien_tuong",
               "huong_gio", "toc_do_gio", "tam_nhin"]

FIELD_LABELS = {
    "tong_luong_may": "Tổng lượng mây",
    "do_cao_man_may": "Độ cao màn mây (trần)",
    "hien_tuong":     "Hiện tượng",
    "huong_gio":      "Hướng gió",
    "toc_do_gio":     "Tốc độ gió",
    "tam_nhin":       "Tầm nhìn xa",
}

FIELD_DEFAULTS = {
    "tong_luong_may": 4,
    "do_cao_man_may": 0,
    "hien_tuong":     PHENOMENON_MEGA_KEYS[-1],
    "huong_gio":      0,
    "toc_do_gio":     0,
    "tam_nhin":       0,
}


def field_key_from_label(label: str):
    for k, v in FIELD_LABELS.items():
        if v == label:
            return k
    return None


def row_value_str(row: dict) -> str:
    key, v = row["field"], row["value"]
    if key == "hien_tuong":
        spec = BUCKETS["hien_tuong"]
        buoi_seen = []
        for h in range(row["start"], row["end"] + 1):
            b = sub_of_hour(h)
            if b is not None and b not in buoi_seen:
                buoi_seen.append(b)
        buoi_str = ", ".join(spec["sub_labels"][b] for b in buoi_seen)
        return f"{spec['mega_labels'][v]} (buổi: {buoi_str})"
    kind = BUCKETS[key]["kind"]
    if kind == "forecast_window":
        return window_labels(key)[v]
    if kind == "linear":
        return linear_labels(key)[v]
    if kind == "circular":
        return BUCKETS[key]["labels"][v]
    return str(v)


# =============================================================================
# Gộp theo giờ (thuần) - dùng cả khi sinh CSV lẫn (gián tiếp) khi nhập CSV.
# =============================================================================

def covered_hours(rows: list) -> list:
    """Every hour any row's [start, end] range touches (both ends included) -
    same rule as bulletin_generator.py's _covered_hours: a "07-09" row
    covers hours 07, 08 AND 09, each getting its own csv row."""
    hours = set()
    for r in rows:
        hours.update(range(r["start"], r["end"] + 1))
    return sorted(hours)


def merge_at_hour(rows: list, hour: int) -> dict:
    """One bucket per field: among rows covering `hour`, the one with the
    latest start wins (same rule as bulletin_generator.py's _merge_at_hour)."""
    state = {}
    for r in sorted(rows, key=lambda r: r["start"]):
        if r["start"] <= hour <= r["end"]:
            state[r["field"]] = r["value"]
    return state


# =============================================================================
# CSV shape - một cột máy (dùng thẳng cho score_field/score_wind/
# score_phenomenon) + một cột nhãn đọc được, cho từng trường.
# =============================================================================

def field_columns(key: str) -> list:
    if key == "hien_tuong":
        return ["hien_tuong_mega", "hien_tuong_mega_label",
                "hien_tuong_buoi", "hien_tuong_buoi_label"]
    return [f"{key}_bucket_idx", f"{key}_bucket_label"]


def field_row_values(key: str, value) -> dict:
    """Cho 5 trường bucket-đơn (không dùng cho hien_tuong - buổi của nó phụ
    thuộc GIỜ, xem hien_tuong_row_values)."""
    cols = field_columns(key)
    if value is None:
        return {c: "" for c in cols}
    return {f"{key}_bucket_idx": value, f"{key}_bucket_label": row_value_str({"field": key, "value": value})}


def hien_tuong_row_values(mega: str, hour: int) -> dict:
    """Mega là lựa chọn của dự báo viên; buổi LUÔN suy từ `hour` qua
    sub_of_hour() - không đọc từ riêng 1 lựa chọn buổi nào."""
    if mega is None:
        return {c: "" for c in field_columns("hien_tuong")}
    spec = BUCKETS["hien_tuong"]
    buoi = sub_of_hour(hour)
    return {
        "hien_tuong_mega": mega,
        "hien_tuong_mega_label": spec["mega_labels"][mega],
        "hien_tuong_buoi": buoi,
        "hien_tuong_buoi_label": spec["sub_labels"][buoi] if buoi is not None else "",
    }


CSV_FIELDNAMES = ["date", "hour", "station_code", "station"]
for _k in FIELD_ORDER:
    CSV_FIELDNAMES += field_columns(_k)


def csv_row_for_hour(state: dict, meta: dict, hour: int):
    """-> (row_dict, missing_field_keys)."""
    row = {
        "date": meta["date"],
        "hour": f"{hour:02d}",
        "station_code": meta["station_code"],
        "station": meta["station_name"],
    }
    missing = []
    for key in FIELD_ORDER:
        value = state.get(key)
        if value is None:
            missing.append(key)
        if key == "hien_tuong":
            row.update(hien_tuong_row_values(value, hour))
        else:
            row.update(field_row_values(key, value))
    return row, missing


# =============================================================================
# Nhập CSV - chiều ngược của covered_hours/merge_at_hour/csv_row_for_hour:
# gộp lại (run-length) các giờ liên tiếp cùng giá trị của mỗi trường thành 1
# dòng [start, end, field, value]. Vì CSV đã ở dạng "mỗi giờ 1 dòng" (đã trải
# phẳng), kết quả không nhất thiết trùng hệt các dòng gốc đã tạo ra nó (2
# dòng liền kề cùng giá trị sẽ gộp thành 1) - nhưng sinh lại đúng bucket cho
# từng giờ.
# =============================================================================

def collapse_to_ranges(pairs: list) -> list:
    """pairs: [(hour, value_or_None), ...] đã sắp theo hour tăng dần.
    -> [(start, end, value), ...], chỉ gộp các hour LIÊN TỤC cùng value."""
    ranges = []
    start = val = prev_hour = None
    for h, v in pairs:
        if v is not None and start is not None and v == val and h == prev_hour + 1:
            prev_hour = h
            continue
        if start is not None:
            ranges.append((start, prev_hour, val))
            start = val = prev_hour = None
        if v is not None:
            start, val, prev_hour = h, v, h
    if start is not None:
        ranges.append((start, prev_hour, val))
    return ranges


def import_csv_rows(records: list):
    """records: list[dict] từ csv.DictReader. -> (meta, rows, warnings).
    Ô nhiễm cột/giá trị bị bỏ qua (không làm hỏng cả file) và liệt kê trong
    warnings."""
    if not records:
        raise ValueError("File CSV rỗng.")
    required = {"date", "hour", "station_code", "station"}
    missing_cols = required - set(records[0].keys())
    if missing_cols:
        raise ValueError(f"Thiếu cột bắt buộc: {', '.join(sorted(missing_cols))}")

    records = sorted(records, key=lambda r: int(r["hour"]))
    meta = {
        "station_code": records[0]["station_code"],
        "station_name": records[0]["station"],
        "date": records[0]["date"],
    }

    warnings = []
    rows = []
    for key in FIELD_ORDER:
        pairs = []
        for r in records:
            hour = int(r["hour"])
            if key == "hien_tuong":
                raw = (r.get("hien_tuong_mega") or "").strip()
                if not raw:
                    pairs.append((hour, None))
                elif raw in BUCKETS["hien_tuong"]["mega_buckets"]:
                    pairs.append((hour, raw))
                else:
                    warnings.append(f"{hour:02d}h: mega '{raw}' không hợp lệ cho hiện tượng - bỏ qua")
                    pairs.append((hour, None))
                continue
            raw = (r.get(f"{key}_bucket_idx") or "").strip()
            if not raw:
                pairs.append((hour, None))
                continue
            try:
                idx = int(raw)
            except ValueError:
                warnings.append(f"{hour:02d}h: '{raw}' không phải số nguyên cho {FIELD_LABELS[key]} - bỏ qua")
                pairs.append((hour, None))
                continue
            if not (0 <= idx < valid_index_count(key)):
                warnings.append(f"{hour:02d}h: bucket #{idx} ngoài phạm vi cho {FIELD_LABELS[key]} - bỏ qua")
                pairs.append((hour, None))
                continue
            pairs.append((hour, idx))

        for start, end, val in collapse_to_ranges(pairs):
            rows.append({"start": start, "end": end, "field": key, "value": val})

    return meta, rows, warnings
