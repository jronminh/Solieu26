"""
csv_pipeline.py
====================
CSV-export pipeline: FTP download + CSV export + the run_pipeline()
orchestrator. Named "csv_pipeline" (not just "pipeline") to stay distinct from
the forecast-scoring pipeline planned in score_tables.py/scorer.py — this
module produces the display-oriented CSV export only, unaffected by the type
coercion decode.py does for score_tables.py's benefit.

Built on config.py (settings/paths) and decode.py (bulletin → dict decoding).
GUI-only — not runnable standalone. gui.py calls config.apply_config_file() at
startup, builds a cfg dict from its own form fields for every run, and calls
csv_pipeline.run_pipeline() — never touching the FTP/decode internals directly.

Every function that does work takes a required `log(level, msg)` callback —
gui.py always passes its own (routing into the on-screen log widget); there is
no console fallback. LEVEL is a fixed 4-char-wide code:
    INFO  general info            OK    success
    SKIP  skipped (already there) MISS  file missing on server
    WARN  warning                 ERR   error
    ACT   user action (button click, option change) — GUI only
"""

import csv
import datetime
import os
import time
from ftplib import FTP, error_perm, error_temp

from config import DEFAULT_OUTPUT_DIR, FTP_TIMEOUT
from decode import decode_history


# =============================================================================
# FTP LAYER — FILE DOWNLOAD  (log/progress via callback)
# =============================================================================

def _download_one(ftp: FTP, filename: str, local_path: str,
                  retry_temp: int = 0, retry_wait: int = 2) -> int:
    """
    Download ONE file (bare name) from the FTP's current directory to local.
    Uses a '.part' temp file + atomic os.replace → no half-written file left behind.

    0 success · 1 already exists · 2 could not download.
    """
    if os.path.isfile(local_path):
        return 1

    tmp = local_path + ".part"
    attempts = retry_temp + 1
    for attempt in range(attempts):
        try:
            with open(tmp, "wb") as f:
                ftp.retrbinary(f"RETR {filename}", f.write)
        except error_temp:
            if os.path.exists(tmp):
                os.remove(tmp)
            if attempt < attempts - 1:
                time.sleep(retry_wait)
                continue
            return 2
        except (error_perm, OSError, EOFError):
            if os.path.exists(tmp):
                os.remove(tmp)
            return 2
        else:
            os.replace(tmp, local_path)
            return 0

    return 2


def _fetch_and_bucket(ftp: FTP, filename: str, local_dir: str, retry_temp: int, retry_wait: int,
                      log, buckets: dict) -> int:
    """Download one file, log the outcome, and sort it into the right bucket
    (buckets = {"files","downloaded","skipped","missing"}, each a list — shared
    across the whole batch). Returns the raw status for the progress callback."""
    local_path = os.path.join(local_dir, filename)
    status = _download_one(ftp, filename, local_path, retry_temp=retry_temp, retry_wait=retry_wait)
    if status == 0:
        log("OK", f"Tải về          {filename}")
        buckets["files"].append(local_path); buckets["downloaded"].append(filename)
    elif status == 1:
        log("SKIP", f"Đã có sẵn       {filename}")
        buckets["files"].append(local_path); buckets["skipped"].append(filename)
    else:
        log("MISS", f"Server chưa có  {filename}")
        buckets["missing"].append(filename)
    return status


def quantrac_filename_at(dt: datetime.datetime) -> str:
    """Qt<YY><MM><DD><HH>.txt — e.g. datetime(2026,4,1,13) → 'Qt26040113.txt'."""
    return f"Qt{dt.strftime('%y%m%d')}{dt.hour:02}.txt"


def parse_obs_dt(filename: str):
    """
    Extract the observation datetime from a 'QtYYMMDDHH.txt' filename.
    Returns a datetime, or None if the name doesn't match the pattern.
    Used to generate a real time column for the CSV (instead of burying it in source_file).
    """
    if not filename:
        return None
    base = os.path.basename(filename)
    try:
        return datetime.datetime.strptime(base[2:10], "%y%m%d%H")
    except (ValueError, IndexError):
        return None


def download_files(ftp: FTP, cfg: dict, log, progress=None) -> dict:
    """
    Download hourly bulletin files into cfg['local_dir'], from cfg['start_date']
    through cfg['end_date'] (inclusive).

    Same day (start_date == end_date): fast path — cwd ONCE into that date's
    remote directory and download the full day [00:00 → 23:00]; if the
    directory is unreachable, bail out early.

    Different days: walks every hour from 00:00 of start_date through 23:00 of
    end_date. The remote directory is "<remote_dir>/YYYY/MM" per timestamp, so
    it cwd's again only when the year/month actually changes (a range can span
    multiple months/years).

    Returns a dict: {"files","downloaded","skipped","missing"}.
    """
    start_date = cfg["start_date"]
    end_date   = cfg["end_date"]
    remote_dir = cfg["remote_dir"].rstrip("/")
    local_dir  = cfg["local_dir"]
    retry_temp = cfg.get("retry_temp", 0)
    retry_wait = cfg.get("retry_wait", 2)
    os.makedirs(local_dir, exist_ok=True)

    buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
    origin = ftp.pwd()

    if start_date.date() == end_date.date():
        hours = [start_date.replace(hour=h) for h in range(24)]
        total = len(hours)

        target_dir = f"{remote_dir}/{start_date:%Y}/{start_date:%m}"
        try:
            ftp.cwd(target_dir)
        except (error_perm, error_temp) as e:
            log("ERR", f"Không truy cập được thư mục {target_dir}: {e}")
            return buckets

        try:
            for i, ts in enumerate(hours):
                filename = quantrac_filename_at(ts)
                status = _fetch_and_bucket(ftp, filename, local_dir, retry_temp, retry_wait, log, buckets)
                if progress:
                    progress(i + 1, total, status)
        finally:
            ftp.cwd(origin)
        return buckets

    hours = []
    day = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last_day:
        for hour in range(24):
            hours.append(day.replace(hour=hour))
        day += datetime.timedelta(days=1)
    total = len(hours)

    current_dir = None
    try:
        for i, ts in enumerate(hours):
            target_dir = f"{remote_dir}/{ts:%Y}/{ts:%m}"
            filename   = quantrac_filename_at(ts)

            if target_dir != current_dir:
                try:
                    ftp.cwd(target_dir)
                    current_dir = target_dir
                except (error_perm, error_temp) as e:
                    log("ERR", f"Không truy cập được thư mục {target_dir}: {e}")
                    current_dir = target_dir   # avoid retrying cwd for every hour in this month
                    buckets["missing"].append(filename)
                    if progress:
                        progress(i + 1, total, 2)
                    continue

            status = _fetch_and_bucket(ftp, filename, local_dir, retry_temp, retry_wait, log, buckets)
            if progress:
                progress(i + 1, total, status)
    finally:
        ftp.cwd(origin)

    return buckets


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
      - 'total_cloud_N' replaces the old 'wind_N' (it's actually total cloud
        amount N, not a wind quantity).
      - *_hshs columns stay PURELY NUMERIC (rare qualitative values → left blank).
      - 'raw' is pushed to the END (for lookup only, not mixed into clean data).

    max_cloud_layers is normally computed per batch by cloud_layers_needed()
    below (so a day with only 1-layer reports doesn't drag along empty
    cloud_2_*/cloud_3_*/cloud_4_* columns) — the default of 4 here only
    applies when flatten_record is called on its own.
    """
    location = record.get("location") or {}
    head     = record.get("head") or {}
    wind     = record.get("wind") or {}
    weather  = record.get("weather") or {}
    storm    = record.get("storm") or {}
    pressure = record.get("pressure") or {}

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
        "total_cloud_N":  wind.get("wind_N"),    # total cloud amount (oktas)
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
        flat[f"cloud_{i+1}_Ns"]   = cloud.get("cloud_Ns")
        flat[f"cloud_{i+1}_C"]    = cloud.get("cloud_C")
        flat[f"cloud_{i+1}_hshs"] = _num_or_none(cloud.get("cloud_hshs"))

    # 'raw' goes last — for looking up the original bulletin only.
    flat["raw"] = record.get("raw")
    return flat


def cloud_layers_needed(records: list, cap: int = 4) -> int:
    """How many cloud_N_* column groups a batch actually needs (>=1, capped at
    `cap`). Keeps the common case — 0 or 1 reported layer — from carrying
    always-empty cloud_2_*/cloud_3_*/cloud_4_* columns into the CSV/viewer."""
    longest = max((len(r.get("cloud") or []) for r in records), default=0)
    return max(1, min(longest, cap))


def write_csv(file_path: str, rows: list):
    if not rows:
        return
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


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


# =============================================================================
# ORCHESTRATOR
# =============================================================================

def run_pipeline(cfg: dict, log, progress=None) -> dict:
    """
    Run it end to end: connect FTP → download (into temp) → decode → export CSV.
    Returns a result dict. Raises on FTP login/connect failure — gui.py's worker
    thread catches it and reports the error back to the main thread as an event.
    """
    result = {"ok": False, "files": [], "missing": [],
              "history_files": {}, "history_records": 0,
              "output_dir": cfg.get("output_dir", DEFAULT_OUTPUT_DIR)}

    log("INFO", f"Thư mục tải tạm: {cfg.get('local_dir')}")
    log("INFO", "Đang kết nối FTP…")
    ftp = FTP(cfg["ftp_host"], timeout=cfg.get("ftp_timeout", FTP_TIMEOUT))
    ftp.login(cfg["ftp_user"], cfg["ftp_pass"])
    log("OK", "Đăng nhập FTP thành công")

    files = []
    try:
        dl = download_files(ftp, cfg, log=log, progress=progress)
        files = dl["files"]
        result["files"]   = files
        result["missing"] = dl["missing"]

        if not files:
            log("WARN", "Không tải được file nào")
            return result

        files = sorted(files)
        log("INFO", f"Tổng số file có sẵn: {len(files)}")

        output_dir = os.path.abspath(cfg.get("output_dir") or DEFAULT_OUTPUT_DIR)
        os.makedirs(output_dir, exist_ok=True)
        result["output_dir"] = output_dir

        history_files = export_history_by_date(files, output_dir)
        result["history_files"] = history_files
        result["history_records"] = sum(v["records"] for v in history_files.values())
        log("INFO", f"Lịch sử đầy đủ: {result['history_records']} record "
                    f"(mọi trạm, mọi giờ, {len(history_files)} ngày)")
        for date_key in sorted(history_files):
            info = history_files[date_key]
            log("OK", f"Đã xuất lịch sử {date_key}: {info['csv']} ({info['records']} record)")

        result["ok"] = True
        return result

    finally:
        try:
            ftp.quit()
        except Exception:
            pass
