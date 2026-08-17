"""
config.py
====================
Path/FTP constants + the CONFIG dict + config.ini load/save.

No FTP calls, no decoding — this is the settings layer everything else
(decode.py, pipeline_csv.py, gui.py) reads from. gui.py is the only writer: it calls
apply_config_file() once at startup and write_default_config() whenever the
user restores default settings from the "Thiết lập" dialog (saving individual
keys goes through utils.ini_utils.update_ini_key() instead).
"""

import configparser
import os
import sys


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

    "station_code": "k15",

    "viewer_hidden_columns": [],         # GUI-only: columns hidden in the CSV viewer

    "auto_query_value": 15,              # GUI-only: auto-query interval (0 = disabled)
    "auto_query_unit":  "minutes",       # GUI-only: "minutes" or "hours" — unit for auto_query_value
    "auto_query_on_startup": True,       # GUI-only: run once automatically right after launch
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
_INT_KEYS  = ("ftp_timeout", "retry_temp", "retry_wait", "auto_query_value")
_BOOL_KEYS = ("auto_query_on_startup",)


def _to_bool(v: str):
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise ValueError(v)


def load_config_file(path: str, log) -> dict:
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
        f"auto_query_value = {d['auto_query_value']}",
        f"auto_query_unit = {d['auto_query_unit']}",
        f"auto_query_on_startup = {'true' if d['auto_query_on_startup'] else 'false'}",
    ]


def write_default_config(path: str) -> str:
    """Write a fresh config.ini from the hardcoded defaults (DEFAULT_CONFIG),
    overwriting whatever was there. Returns the path written."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(_default_config_lines()) + "\n")
    return path


def apply_config_file(path: str, log):
    """
    Resolve the config path (argument > default alongside the data folder),
    auto-creating it from DEFAULT_CONFIG if it doesn't exist yet, then load it
    and override CONFIG. Returns (path_used, dict_of_overridden_keys).

    Default location is TEMP_DL_DIR (same place downloaded bulletins land), not
    next to the script/exe — that folder is always writable, unlike an exe that
    might sit under Program Files.

    `log` is forwarded to load_config_file() for its per-key WARNs — pass the
    GUI's own log sink (gui.py buffers calls made before its log widget exists yet).
    """
    path = path or os.path.join(TEMP_DL_DIR, CONFIG_FILENAME)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.isfile(path):
        write_default_config(path)
    overrides = load_config_file(path, log=log)
    CONFIG.update(overrides)
    return path, overrides
