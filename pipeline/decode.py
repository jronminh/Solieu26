"""
pipeline/decode.py
====================
Khối 2 (xử lý số liệu thành readable) — decode file bulletin đã có sẵn trên
đĩa (`bulletin/decode.py`, KHÔNG PHẢI module này dù trùng tên "decode") rồi
làm phẳng thành CSV. Nhận thẳng 1 list đường dẫn file cục bộ; không biết gì
về FTP (khối 1, xem `pipeline/fetch.py`) và không import module đó — độc
lập hoàn toàn, module này vỡ không ảnh hưởng khối lấy file, và ngược lại.
This module produces the display-oriented CSV export only, unaffected by
the type coercion bulletin/decode.py does for score_tables.py's benefit.

Built on bulletin/decode.py (bulletin → dict decoding) only — no
config_utils.py dependency, no log(level, msg) callback (unlike
pipeline/fetch.py, nothing here reports progress; a caller that wants
per-step logging does it around these calls).
GUI-only — not runnable standalone. runner.py imports this module lazily (right
where export_history_by_date() is called) so a decode-layer failure here
can't take down the fetch step or main.py's own startup — see runner.py::_work().
"""

import os

from bulletin.decode import decode_history
from bulletin.filename import parse_obs_dt
from utils.csv_utils import write_csv


# =============================================================================
# CSV EXPORT
# =============================================================================

def _num_or_none(v):
    """Coerce to a number so the column has a consistent type; qualitative values (e.g. '<50') → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def flatten_record(record: dict, source_file: str = None,
                   max_cloud_layers: int = 4) -> dict:
    """
    Flatten a record into one CSV row with a clean schema:

      - Time & meta come FIRST (obs_time / date / hour / source_file).
      - lat/lon coordinates are DECIMAL DEGREES (already converted upstream).
      - Column names carry their UNIT; drops the duplicate 'iii' column and the
        debug column 'pressure_raw'.
      - *_hshs columns stay PURELY NUMERIC (rare qualitative values → left blank).
      - 'raw' is pushed to the END (for lookup only, not mixed into clean data).

    max_cloud_layers is normally computed per batch by cloud_layers_needed()
    below (so a day with only 1-layer reports doesn't drag along empty
    cloud_2_*/cloud_3_*/cloud_4_* columns) — the default of 4 here only
    applies when flatten_record is called on its own.
    """
    location    = record.get("location") or {}
    head        = record.get("head") or {}
    total_cloud = record.get("total_cloud") or {}
    wind        = record.get("wind") or {}
    weather     = record.get("weather") or {}
    storm       = record.get("storm") or {}
    pressure    = record.get("pressure") or {}

    obs_dt   = parse_obs_dt(source_file)

    flat = {
        # --- Time & meta ---
        "obs_time":     obs_dt.strftime("%Y-%m-%d %H:%M") if obs_dt else None,
        "date":         obs_dt.strftime("%Y-%m-%d") if obs_dt else None,
        "hour":         f"{obs_dt.hour:02d}" if obs_dt else None,
        "source_file":  os.path.basename(source_file) if source_file else None,

        # --- Station identity ---
        "station":      record.get("station"),
        "station_code": location.get("station_code"),
        "lat":          location.get("lat"),     # decimal degrees
        "lon":          location.get("lon"),     # decimal degrees

        # --- Visibility / wind ---
        "visibility_km":  _num_or_none(head.get("VV")),
        "total_cloud_N":  total_cloud.get("total_cloud_N"),  # total cloud amount (tenths)
        "wind_dd_deg":    wind.get("wind_dd"),   # wind direction (degrees)
        "wind_ff":        wind.get("wind_ff"),   # wind speed (unit per station)

        # --- Temperature ---
        "temperature_c":  record.get("temperature"),
        "dewpoint_c":     record.get("dewpoint"),

        # --- Weather ---
        "weather_ww":   weather.get("ww"),
        "weather_W1":   weather.get("W1"),
        "weather_W2":   weather.get("W2"),

        # --- Storm (mây dông Cb quan sát quanh trạm, nhóm A) ---
        "storm_dd_deg":  storm.get("storm_dd"),
        "storm_distance": storm.get("storm_L"),
        "storm_trend":    storm.get("storm_Cg"),

        # --- Pressure ---
        "pressure_hpa": pressure.get("pressure_hpa"),

        # --- Cloud ---
        "cloud_layers": len(record.get("cloud") or []),
    }

    clouds = record.get("cloud") or []
    for i in range(max_cloud_layers):
        cloud = clouds[i] if i < len(clouds) else {}
        flat[f"cloud_{i+1}_Ns"]   = cloud.get("amount")
        flat[f"cloud_{i+1}_C"]    = cloud.get("type")
        flat[f"cloud_{i+1}_hshs"] = _num_or_none(cloud.get("height"))

    # 'raw' goes last — for looking up the original bulletin only.
    flat["raw"] = record.get("raw")
    return flat


def cloud_layers_needed(records: list, cap: int = 4) -> int:
    """How many cloud_N_* column groups a batch actually needs (>=1, capped at
    `cap`). Keeps the common case — 0 or 1 reported layer — from carrying
    always-empty cloud_2_*/cloud_3_*/cloud_4_* columns into the CSV/viewer."""
    longest = max((len(r.get("cloud") or []) for r in records), default=0)
    return max(1, min(longest, cap))


def export_history_by_date(local_files: list, out_dir: str) -> dict:
    """
    Decode every downloaded file (decode.decode_history) and split the result
    into one history_YYYYMMDD.csv per observation date — a day only gets
    written once every file belonging to it has been decoded, so a query
    spanning N days produces N files instead of one growing history.csv.

    The sole remaining CSV-producing function now that "latest" export is gone.
    Returns {"YYYY-MM-DD": {"csv": path, "records": n}, ...}, one entry per date
    actually present in local_files (a file whose name doesn't parse as a
    QtYYMMDDHH.txt timestamp falls under the "unknown" bucket instead of being
    dropped).
    """
    by_date = {}
    for item in decode_history(local_files):
        obs_dt = parse_obs_dt(item["file"])
        date_key = obs_dt.strftime("%Y-%m-%d") if obs_dt else "unknown"
        by_date.setdefault(date_key, []).append(item)

    exported = {}
    for date_key, items in sorted(by_date.items()):
        n_cloud = cloud_layers_needed([item["data"] for item in items])
        rows = [flatten_record(item["data"], source_file=item["file"], max_cloud_layers=n_cloud)
                for item in items]
        out_path = os.path.join(out_dir, f"history_{date_key.replace('-', '')}.csv")
        write_csv(out_path, rows)
        exported[date_key] = {"csv": out_path, "records": len(rows)}
    return exported
