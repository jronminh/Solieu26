"""
core.py
====================
Core: fetch + decode surface weather observation bulletins (no UI, no tkinter).

Runs standalone:
    python core.py [config.ini path]

Uses the CONFIG dict defined below as defaults. If a config.ini file exists
(next to the downloaded-data folder, or the path given on the command line),
its keys override CONFIG — see "LOADING THE EXTERNAL CONFIG" below for the exact keys.
Logs go through the callback log(level, msg); the default _console_log prints
them to stdout as "HH:MM:SS  LEVEL  message".

gui.py is a thin Tkinter wrapper around this module (`import core`) — it
calls core.apply_config_file()/core.run_pipeline() and never touches the
FTP/decode internals directly.
"""

import csv
import datetime
import configparser
import os
import sys
import time
from ftplib import FTP, error_perm, error_temp

# Console output must survive non-UTF-8 terminals — Windows cmd.exe's default
# codepage (cp1252/cp437) can't encode Vietnamese diacritics and would otherwise
# crash the very first _console_log() call when running standalone.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# =============================================================================
# PATH & FTP CONSTANTS
# =============================================================================

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built exe: __file__ would point into the
    # temporary extraction folder, so anchor to the exe's own location instead.
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    try:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        SCRIPT_DIR = os.path.abspath(".")

# Everything the app persists lives under the user's home folder (works the
# same way on Windows and Linux via os.path.expanduser), not the OS temp dir or
# next to the script — so it survives temp-dir cleanup and doesn't depend on
# where the exe/script happens to sit.
USER_BASE_DIR = os.path.join(os.path.expanduser("~"), "solieu26_dl")

# Downloaded (raw) files; a fixed subfolder (NOT random) so a later run still
# recognizes old files and can SKIP instead of re-downloading.
TEMP_DL_DIR = os.path.join(USER_BASE_DIR, "data")

DEFAULT_OUTPUT_DIR = USER_BASE_DIR       # default CSV location

FTP_TIMEOUT = 30                         # seconds
RETRY_TEMP  = 1                          # extra retry attempts when server reports busy (4xx)
RETRY_WAIT  = 2                          # seconds to wait between retries


# =============================================================================
# LOGGING — SINGLE SHARED LOG FORMAT
# -----------------------------------------------------------------------------
# Every log line — from this module or from the GUI — goes through the callback
# log(level, msg) and is rendered in exactly ONE format: "HH:MM:SS  LEVEL  message".
# LEVEL is a fixed 4-char-wide code:
#     INFO  general info            OK    success
#     SKIP  skipped (already there) MISS  file missing on server
#     WARN  warning                 ERR   error
#     ACT   user action (button click, option change) — GUI only
# Running headless (no GUI) → _console_log prints to console in the same format.
# =============================================================================

def _console_log(level: str, msg: str):
    """Default log writer when running WITHOUT a GUI — prints to console, same format."""
    print(f"{time.strftime('%H:%M:%S')}  {level.upper():<4}  {msg}")


# =============================================================================
# DEFAULT CONFIG (also the schema written to/read from config.ini)
# =============================================================================

CONFIG = {
    "ftp_host": "",
    "ftp_user": "",
    "ftp_pass": "",
    "ftp_timeout": FTP_TIMEOUT,

    "retry_temp": RETRY_TEMP,
    "retry_wait": RETRY_WAIT,

    "remote_dir": "Quantrac",
    "local_dir":  TEMP_DL_DIR,           # downloads go under the user folder
    "output_dir": DEFAULT_OUTPUT_DIR,
    "delete_on_exit": False,

    "station_code": "k15",

    "start_date": datetime.datetime(2026, 8, 10),
    "end_date":   datetime.datetime(2026, 8, 10),
    "end_hour":   23,        # last hour to fetch, ONLY when start_date == end_date

    "viewer_hidden_columns": [],         # GUI-only: columns hidden in the CSV viewer

    "auto_query_value": 15,              # GUI-only: auto-query interval (0 = disabled)
    "auto_query_unit":  "minutes",       # GUI-only: "minutes" or "hours" — unit for auto_query_value
    "auto_query_on_startup": False,      # GUI-only: run once automatically right after launch
}

# Pristine snapshot of the hardcoded defaults, taken before anything (loaded
# config.ini, in-session edits) ever mutates CONFIG. Powers "Khôi phục mặc
# định" — restoring must come from the source code, not from whatever CONFIG
# currently holds.
DEFAULT_CONFIG = dict(CONFIG)


# =============================================================================
# LOADING THE EXTERNAL CONFIG (config.ini)
# -----------------------------------------------------------------------------
# If a config.ini file exists (in TEMP_DL_DIR, or passed on the command line),
# read it and OVERRIDE the defaults in CONFIG. Missing file → keep code defaults.
# Only the keys you want to change need to be present; absent keys keep their default.
# 'local_dir' is never read from config — downloads always go into TEMP_DL_DIR.
# =============================================================================

CONFIG_FILENAME = "config.ini"          # default name, looked up in TEMP_DL_DIR
CONFIG_SECTION  = "Solieu26"

_STR_KEYS  = ("ftp_host", "ftp_user", "ftp_pass",
              "remote_dir", "output_dir", "station_code", "auto_query_unit")
_INT_KEYS  = ("end_hour", "ftp_timeout", "retry_temp", "retry_wait",
              "auto_query_value")
_BOOL_KEYS = ("delete_on_exit", "auto_query_on_startup")


def _to_bool(v: str):
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise ValueError(v)


def load_config_file(path: str, log=_console_log) -> dict:
    """Read INI → override dict. Missing/broken file → {} (with a warning).

    Every warning goes through `log`, same as the rest of the module — so a
    caller with its own log sink (e.g. the GUI) sees WHICH key was skipped and
    why, instead of the message only ever reaching stdout.
    """
    if not path or not os.path.isfile(path):
        return {}

    parser = configparser.ConfigParser(interpolation=None)  # disable %(...)s so paths stay safe
    try:
        parser.read(path, encoding="utf-8")
    except Exception as e:
        log("WARN", f"Không đọc được config '{path}': {e}")
        return {}

    if parser.has_section(CONFIG_SECTION):
        raw = dict(parser.items(CONFIG_SECTION))
    else:
        raw = dict(parser.defaults())        # accept keys placed under [DEFAULT]

    out = {}
    for k in _STR_KEYS:
        if k in raw:
            out[k] = raw[k].strip()
    for k in _INT_KEYS:
        if k in raw:
            try:
                out[k] = int(raw[k])
            except ValueError:
                log("WARN", f"config '{k}' không phải số nguyên → bỏ qua")
    for k in _BOOL_KEYS:
        if k in raw:
            try:
                out[k] = _to_bool(raw[k])
            except ValueError:
                log("WARN", f"config '{k}' không phải true/false → bỏ qua")
    for k in ("start_date", "end_date"):
        if k in raw:
            try:
                out[k] = datetime.datetime.strptime(raw[k].strip(), "%Y-%m-%d")
            except ValueError:
                log("WARN", f"config '{k}' sai định dạng YYYY-MM-DD → bỏ qua")
    if "viewer_hidden_columns" in raw:
        val = raw["viewer_hidden_columns"].strip()
        out["viewer_hidden_columns"] = [c.strip() for c in val.split(",") if c.strip()]
    return out


def _default_config_lines() -> list:
    """Render DEFAULT_CONFIG as config.ini lines — the single source of truth
    for both auto-creating a missing config.ini and 'Khôi phục mặc định'."""
    d = DEFAULT_CONFIG
    return [
        "# config.ini cho Solieu26 — sửa giá trị rồi lưu lại.",
        "# Xóa dòng nào muốn dùng mặc định trong mã.",
        f"[{CONFIG_SECTION}]",
        f"ftp_host = {d['ftp_host']}",
        f"ftp_user = {d['ftp_user']}",
        f"ftp_pass = {d['ftp_pass']}",
        f"remote_dir = {d['remote_dir']}",
        f"output_dir = {d['output_dir']}",
        f"station_code = {d['station_code']}",
        f"end_hour = {d['end_hour']}",
        f"delete_on_exit = {'true' if d['delete_on_exit'] else 'false'}",
        f"auto_query_value = {d['auto_query_value']}",
        f"auto_query_unit = {d['auto_query_unit']}",
        f"auto_query_on_startup = {'true' if d['auto_query_on_startup'] else 'false'}",
    ]


def write_default_config(path: str = None) -> str:
    """Write a fresh config.ini from the hardcoded defaults (DEFAULT_CONFIG),
    overwriting whatever was there. Returns the path written."""
    path = path or os.path.join(TEMP_DL_DIR, CONFIG_FILENAME)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(_default_config_lines()) + "\n")
    return path


def apply_config_file(path: str = None, log=_console_log):
    """
    Resolve the config path (argument > default alongside the data folder),
    auto-creating it from DEFAULT_CONFIG if it doesn't exist yet, then load it
    and override CONFIG. Returns (path_used, dict_of_overridden_keys).

    Default location is TEMP_DL_DIR (same place downloaded bulletins land), not
    next to the script/exe — that folder is always writable, unlike an exe that
    might sit under Program Files.

    `log` is forwarded to load_config_file() for its per-key WARNs — pass the
    GUI's own log sink if one exists yet, otherwise it falls back to console.
    """
    path = path or os.path.join(TEMP_DL_DIR, CONFIG_FILENAME)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.isfile(path):
        write_default_config(path)
    overrides = load_config_file(path, log=log)
    CONFIG.update(overrides)
    return path, overrides


def update_ini_key(path: str, section: str, key: str, value: str):
    """
    Update/add a SINGLE key in an .ini file, preserving every other line (including
    comments) — unlike configparser.write(), which rewrites the whole file and
    drops all comments. Missing file/section → created at the end.
    """
    section_header = f"[{section}]"
    lines = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    sec_start = next((i for i, l in enumerate(lines) if l.strip() == section_header), None)
    new_line = f"{key} = {value}\n"

    if sec_start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines:
            lines.append("\n")
        lines.append(section_header + "\n")
        lines.append(new_line)
    else:
        sec_end = len(lines)
        for i in range(sec_start + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                sec_end = i
                break
        key_idx = next((i for i in range(sec_start + 1, sec_end)
                        if lines[i].split("=", 1)[0].strip().lower() == key.lower()), None)
        if key_idx is not None:
            lines[key_idx] = new_line
        else:
            lines.insert(sec_end, new_line)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


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
        log("OK", f"Tải về      {filename}")
        buckets["files"].append(local_path); buckets["downloaded"].append(filename)
    elif status == 1:
        log("SKIP", f"Đã có sẵn   {filename}")
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


def download_files(ftp: FTP, cfg: dict, log=_console_log, progress=None) -> dict:
    """
    Download hourly bulletin files into cfg['local_dir'], from cfg['start_date']
    through cfg['end_date'] (inclusive).

    Same day (start_date == end_date): fast path — cwd ONCE into that date's
    remote directory and download [00:00 → cfg.get('end_hour', 23)]; if the
    directory is unreachable, bail out early.

    Different days: walks every hour from 00:00 of start_date through 23:00 of
    end_date. The remote directory is "<remote_dir>/YYYY/MM" per timestamp, so
    it cwd's again only when the year/month actually changes (a range can span
    multiple months/years); end_hour is ignored — every day in a range is downloaded
    in full.

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
        end_hour = cfg.get("end_hour", 23)
        hours = [start_date.replace(hour=h) for h in range(end_hour + 1)]
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
# LOOKUP TABLES
# =============================================================================
TABLES = {
    "N_oktas": {
        '/': '/', '0': '0', '1': '1', '2': '3', '3': '4',
        '4': '5', '5': '6', '6': '8', '7': '9', '8': '10', '9': '/'
    },
    "cloud_type": {
        '0': 'Ci', '1': 'Cc', '2': 'Cs', '3': 'Ac', '4': 'As',
        '5': 'Ns', '6': 'Sc', '7': 'St', '8': 'Cu', '9': 'Cb'
    },
    "hshs_special": {
        '00': 30,
        '56': 1800,  '57': 2000,  '58': 2500,  '59': 2700,
        '60': 3000,  '61': 3300,  '62': 3500,  '63': 4000,  '64': 4200,
        '65': 4500,  '66': 4800,  '67': 5000,  '68': 5500,  '69': 5700,
        '70': 6000,  '71': 6300,  '72': 6500,  '73': 7000,  '74': 7200,
        '75': 7500,  '76': 7800,  '77': 8000,  '78': 8500,  '79': 8700,
        '80': 9000,  '81': 10000, '82': 12000, '83': 13000, '84': 15000,
        '85': 17000, '86': 18000, '87': 20000, '88': 21000, '89': 22000,
        '90': '<50', '91': 50,    '92': 100,   '93': 200,   '94': 300,
        '95': 600,   '96': 1000,  '97': 1500,  '98': 2000,
    },
    "ww": {
        '00': 'Không quan sát được mây',   '01': 'Mây tan (mỏng dần)',
        '02': 'Thời tiết không đổi',       '03': 'Mây hình thành (phát triển)',
        '04': 'Khói',                      '05': 'Mù khô',
        '06': 'Bụi lơ lửng',              '07': 'Bụi',
        '08': 'Lốc bụi',                  '09': 'Bão bụi',
        '10': 'Mù',                        '11': 'Sương mù mỏng',
        '12': 'Sương mù mỏng',             '13': 'Chớp',
        '14': 'Mưa xa',                    '15': 'Mưa xa',
        '16': 'Mưa xa',                    '17': 'Dông',
        '18': 'Tố',                        '19': 'Vòi rồng',
        '20': 'Mưa phùn giờ trước',        '21': 'Mưa giờ trước',
        '22': 'Tuyết giờ trước',           '23': 'Mưa lẫn tuyết giờ trước',
        '24': 'Mưa đông kết giờ trước',    '25': 'Mưa rào giờ trước',
        '26': 'Tuyết rào giờ trước',       '27': 'Mưa đá rào giờ trước',
        '28': 'Sương mù giờ trước',        '29': 'Dông giờ trước',
        '30': 'Bão bụi (cát)',             '31': 'Bão bụi (cát)',
        '32': 'Bão bụi (cát)',             '33': 'Bão bụi (cát) mạnh',
        '34': 'Bão bụi (cát) mạnh',       '35': 'Bão bụi (cát) mạnh',
        '36': 'Tuyết cuốn',               '37': 'Tuyết cuốn',
        '38': 'Tuyết cuốn',               '39': 'Tuyết cuốn',
        '40': 'Sương mù',                  '41': 'Sương mù',
        '42': 'Sương mù',                  '43': 'Sương mù',
        '44': 'Sương mù',                  '45': 'Sương mù',
        '46': 'Sương mù',                  '47': 'Sương mù',
        '48': 'Sương mù',                  '49': 'Sương mù',
        '50': 'Mưa phùn',                  '51': 'Mưa phùn',
        '52': 'Mưa phùn',                  '53': 'Mưa phùn',
        '54': 'Mưa phùn',                  '55': 'Mưa phùn',
        '56': 'Mưa phùn',                  '57': 'Mưa phùn',
        '58': 'Mưa phùn',                  '59': 'Mưa phùn',
        '60': 'Mưa nhẹ',                   '61': 'Mưa nhẹ',
        '62': 'Mưa vừa',                   '63': 'Mưa vừa',
        '64': 'Mưa to',                    '65': 'Mưa to',
        '66': 'Mưa đông kết',              '67': 'Mưa đông kết',
        '68': 'Mưa và tuyết',              '69': 'Mưa và tuyết',
        '70': 'Tuyết nhẹ',                 '71': 'Tuyết nhẹ',
        '72': 'Tuyết trung bình',          '73': 'Tuyết trung bình',
        '74': 'Tuyết mạnh',               '75': 'Tuyết mạnh',
        '76': 'Kim nước đá',               '77': 'Tuyết hạt',
        '78': 'Tuyết hình sao',            '79': 'Hạt nước đá',
        '80': 'Mưa rào nhẹ',              '81': 'Mưa rào vừa',
        '82': 'Mưa to',                    '83': 'Mưa rào lẫn tuyết',
        '84': 'Mưa rào lẫn tuyết',        '85': 'Tuyết rào nhẹ',
        '86': 'Tuyết rào mạnh',           '87': 'Mưa đá rào',
        '88': 'Mưa đá rào',               '89': 'Mưa đá rào',
        '90': 'Mưa đá rào',               '91': 'Mưa sau dông',
        '92': 'Mưa sau dông',             '93': 'Mưa đá sau dông',
        '94': 'Mưa đá sau dông',          '95': 'Dông nhẹ và mưa',
        '96': 'Dông nhẹ và mưa',          '97': 'Dông mạnh có mưa',
        '98': 'Dông với bão bụi',         '99': 'Dông mạnh có mưa đá',
    },
    "W1W2": {
        '0': 'Ít mây',              '1': 'Lượng mây thay đổi',
        '2': 'Nhiều mây',           '3': 'Bão cát',
        '4': 'Sương mù',            '5': 'Mưa phùn',
        '6': 'Mưa',                 '7': 'Tuyết',
        '8': 'Mưa rào',             '9': 'Dông',
    },
    "VV_special": {
        '90': '0.0', '91': '0.1', '92': '0.2', '93': '0.5', '94': '1',
        '95': '2',   '96': '4',   '97': '10',  '98': '20',  '99': '50'
    },
}


# =============================================================================
# DECODING
# =============================================================================

def is_pressure_token(t: str) -> bool:
    return len(t) == 4 and t.isdigit() and t.startswith('7')


def split_record(record: str) -> dict:
    tokens = record.split()
    if not tokens:
        return {"head": None, "wind": None, "indicators": [],
                "pressure": None, "name": [], "tail": None}

    n = len(tokens)
    tail = tokens[-1]
    name_start = next((i for i, t in enumerate(tokens) if t.startswith('t')), n - 1)
    name = tokens[name_start:n - 1]

    if tokens[0].startswith('k'):
        head = tokens[0]
        wind = tokens[1] if n > 1 else None
        block_start = 2
    else:
        head = wind = None
        block_start = name_start

    middle = tokens[block_start:name_start]

    pressure = None
    indicators = list(middle)
    for j in range(len(middle) - 1, -1, -1):
        if is_pressure_token(middle[j]):
            pressure = middle[j]
            indicators = middle[:j] + middle[j + 1:]
            break

    return {"head": head, "wind": wind, "indicators": indicators,
            "pressure": pressure, "name": name, "tail": tail}


def _temp_value(token: str):
    if len(token) < 5 or token[0] not in ('1', '2') or token[1] not in ('0', '1'):
        return None
    s = f"{token[2:4]}.{token[4]}"
    if token[1] == '1':
        s = f"-{s}"
    try:
        return float(s)
    except ValueError:
        return None


def _hshs_value(code: str, tables: dict):
    try:
        h = int(code)
    except ValueError:
        return None
    if 1 <= h <= 5:
        return h * 30
    if 6 <= h <= 50:
        return round(h * 30 / 50) * 50
    return tables["hshs_special"].get(code)


def _vv_value(vv_code: str, tables: dict):
    if len(vv_code) < 2:
        return None
    try:
        vv = int(vv_code)
    except ValueError:
        return None
    if vv < 51:
        return f"{vv_code[0]}.{vv_code[1]}"
    if vv <= 55:
        return None
    if vv <= 80:
        return str(vv - 50)
    if vv <= 89:
        return str(vv - 40)
    return tables["VV_special"].get(vv_code)


def decode_head(token: str, tables: dict):
    if not token or not token.startswith('k'):
        return None
    return {"iii": token[:3], "VV": _vv_value(token[3:], tables)}


def decode_wind(token: str, tables: dict):
    if not token or len(token) < 5:
        return None
    N = tables["N_oktas"].get(token[0])
    try:
        dd = int(token[1:3]) * 10
        ff = int(token[3:5])
    except ValueError:
        return {"wind_N": N, "wind_dd": None, "wind_ff": None}
    return {"wind_N": N, "wind_dd": dd, "wind_ff": ff}


def decode_weather(token: str, tables: dict):
    if len(token) < 5:
        return None
    return {"ww": tables["ww"].get(token[1:3]),
            "W1": tables["W1W2"].get(token[3]),
            "W2": tables["W1W2"].get(token[4])}


def decode_cloud(token: str, tables: dict):
    if len(token) < 5:
        return None
    return {"cloud_Ns": tables["N_oktas"].get(token[1]),
            "cloud_C":  tables["cloud_type"].get(token[2]),
            "cloud_hshs": _hshs_value(token[3:5], tables)}


def decode_pressure(token: str):
    if not token or len(token) != 4:
        return None
    try:
        raw = float(f"{token[0:3]}.{token[3]}")
        return {"pressure_raw": raw, "pressure_hpa": round(raw * 4 / 3, 1)}
    except ValueError:
        return None


def decode_name(name_tokens: list):
    if not name_tokens:
        return None
    return ' '.join(name_tokens)[1:]


def decode_tail(token: str):
    """
    kXX + DDMM + DDDMM → {station_code, lat, lon}.

    Coordinates in the bulletin are DEGREES-MINUTES (DDMM), NOT decimal. We
    convert straight to decimal degrees (dd + mm/60) so the lat/lon columns are
    directly usable — ready for mapping / distance calculations without error.
    """
    if not token or not token.startswith('k') or len(token) != 12:
        return None
    try:
        lat_d, lat_m = int(token[3:5]),  int(token[5:7])
        lon_d, lon_m = int(token[7:10]), int(token[10:12])
        return {"station_code": token[0:3],
                "lat": round(lat_d + lat_m / 60, 4),
                "lon": round(lon_d + lon_m / 60, 4)}
    except ValueError:
        return None


def h_temp(t, out, tb):    out["temperature"] = _temp_value(t)
def h_dew(t, out, tb):     out["dewpoint"]    = _temp_value(t)
def h_weather(t, out, tb): out["weather"]     = decode_weather(t, tb)


def h_cloud(t, out, tb):
    out.setdefault("cloud", [])
    layer = decode_cloud(t, tb)
    if layer:
        out["cloud"].append(layer)


def h_group9(t, out, tb): out.setdefault("g9", []).append(t)
def h_group5(t, out, tb): out.setdefault("g5", []).append(t)
def h_groupA(t, out, tb): out.setdefault("gA", []).append(t)


DISPATCH = {'1': h_temp, '2': h_dew, '7': h_weather, '8': h_cloud,
            '9': h_group9, '5': h_group5, 'A': h_groupA}


def decode_indicators(indicators: list, tables: dict) -> dict:
    out = {"temperature": None, "dewpoint": None, "weather": None}
    for t in indicators:
        if not t:
            continue
        h = DISPATCH.get(t[0])
        if h:
            h(t, out, tables)
        else:
            out.setdefault("unknown", []).append(t)
    return out


def decode_record(record: str, tables: dict = TABLES) -> dict:
    p = split_record(record)
    out = {"raw": record}
    out["head"]     = decode_head(p["head"], tables) if p["head"] else None
    out["wind"]     = decode_wind(p["wind"], tables) if p["wind"] else None
    out.update(decode_indicators(p["indicators"], tables))
    out["pressure"] = decode_pressure(p["pressure"]) if p["pressure"] else None
    out["station"]  = decode_name(p["name"])
    out["location"] = decode_tail(p["tail"])
    return out


# =============================================================================
# PIPELINE
# =============================================================================

def get_qt_data(file_path: str) -> list:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = f.read()
    if not data:
        return []
    sep = ';' if ';' in data else '='
    return data.split(sep)[:-1]


def decode_qt_file(file_path: str, tables: dict = TABLES) -> list:
    records = get_qt_data(file_path)
    results = []
    for record in records:
        try:
            results.append(decode_record(record, tables))
        except Exception as e:
            results.append({"error": str(e), "raw": record})
    return results


def decode_history(local_files: list) -> list:
    """
    Decode every downloaded file and keep EVERY station's record (not just one) —
    the full day's station × hour matrix. Station filtering happens later, in the
    CSV viewer, not here: the FTP download is already not station-specific (each
    hourly file bundles every station), so there is nothing to gain by filtering
    before export.
    """
    results = []
    for file_path in sorted(local_files):
        for record in decode_qt_file(file_path):
            if record.get("location"):
                results.append({"file": file_path, "data": record})
    return results


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
      - lat/lon coordinates are DECIMAL DEGREES (already converted in decode_tail).
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
    Decode every downloaded file (decode_history) and split the result into one
    history_YYYYMMDD.csv per observation date — a day only gets written once every
    file belonging to it has been decoded, so a query spanning N days produces N
    files instead of one growing history.csv.

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

def run_pipeline(cfg: dict, log=_console_log, progress=None) -> dict:
    """
    Run it end to end: connect FTP → download (into temp) → decode → export CSV.
    Returns a result dict. Raises on FTP login/connect failure (the GUI catches
    it to show a dialog; a headless caller can just let it propagate).
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
        if cfg.get("delete_on_exit"):
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass


# =============================================================================
# CLI — run standalone, no GUI
# =============================================================================

def main():
    # Allows: python core.py [config_ini_path]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    path_used, overrides = apply_config_file(config_path)
    if overrides:
        _console_log("OK", f"Đã nạp {len(overrides)} thiết lập từ config: {path_used}")
    else:
        _console_log("INFO", f"Không thấy config ({path_used}) — dùng mặc định trong mã.")
    run_pipeline(CONFIG, log=_console_log)


if __name__ == "__main__":
    main()
