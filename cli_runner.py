"""
cli_runner.py
====================
One-shot CLI entry point for pipeline.fetch -> pipeline.decode_files, with no
Tkinter/GUI dependency. FTP host/user/pass/remote_dir/output_dir/
parallel_workers come from config.ini (next to this file); any matching
--ftp-host/... argument overrides the value in config.ini. If config.ini is
missing, a template is written to CONFIG_PATH on first run for the user to
fill in.

Runs synchronously on the main thread - fetch_files()/download_files() already
use their own worker threads internally for parallel_workers > 1, so no extra
queue/poll layer (like runner.py's worker+poll split, which exists only to
keep a Tkinter mainloop responsive) is needed here.

Usage:
    python -m cli_runner --start-date 2026-08-20 --end-date 2026-08-24
    python -m cli_runner --ftp-host HOST --ftp-user USER --ftp-pass PASS
"""

import argparse
import configparser
import datetime
import os
import sys

from utils import log_utils
from utils.filename_utils import parse_obs_dt
from pipeline import fetch as pipeline_fetch

_logger = log_utils.get_logger("cli_runner")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.ini")
CONFIG_SECTION = "Solieu26"

# Downloaded data + log files stay under the user's home (survive the project
# folder being moved/reinstalled), unlike config.ini which now lives with the code.
DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "solieu26_dl")
TEMP_DL_DIR = os.path.join(DEFAULT_OUTPUT_DIR, "data")

FTP_TIMEOUT = 30          # seconds
RETRY_TEMP  = 1           # extra retry attempts when server reports busy (4xx)
RETRY_WAIT  = 2           # seconds to wait between retries
STABILITY_CHECK = True    # poll-size-hai-lần trước khi tải, xem download_one() trong utils/ftp_utils.py
STABILITY_WAIT  = 1       # seconds between the 2 SIZE calls

_DEFAULT_REMOTE_DIR = "/Quantrac"
_DEFAULT_PARALLEL_WORKERS = 1


def _log(level: str, msg: str):
    print(f"[{level}] {msg}")


def _progress(done, total, status, filename):
    print(f"\r{done}/{total} {filename}", end="", flush=True)
    if done == total:
        print()


# =============================================================================
# CONFIG.INI (project root; CLI args override its values)
# =============================================================================

def _write_default_config(path: str):
    lines = [
        "# config.ini cho Solieu26, sửa giá trị rồi lưu lại.",
        "# Xóa dòng nào muốn dùng mặc định/truyền qua CLI arg thay vào đó.",
        f"[{CONFIG_SECTION}]",
        "ftp_host = ",
        "ftp_user = ",
        "ftp_pass = ",
        f"remote_dir = {_DEFAULT_REMOTE_DIR}",
        f"output_dir = {DEFAULT_OUTPUT_DIR}",
        f"parallel_workers = {_DEFAULT_PARALLEL_WORKERS}",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_config_file(path: str) -> dict:
    """Đọc config.ini -> dict override; {} nếu file thiếu/hỏng/không có section."""
    if not os.path.isfile(path):
        return {}
    parser = configparser.ConfigParser(interpolation=None)  # disable %(...)s so paths stay safe
    try:
        parser.read(path, encoding="utf-8")
    except Exception as e:
        _log("WARN", f"Không đọc được config '{path}': {e}")
        return {}
    if not parser.has_section(CONFIG_SECTION):
        return {}

    raw = dict(parser.items(CONFIG_SECTION))
    out = {}
    for k in ("ftp_host", "ftp_user", "ftp_pass", "remote_dir", "output_dir"):
        if raw.get(k, "").strip():
            out[k] = raw[k].strip()
    if raw.get("parallel_workers", "").strip():
        try:
            out["parallel_workers"] = int(raw["parallel_workers"])
        except ValueError:
            _log("WARN", "config 'parallel_workers' không phải số nguyên -> bỏ qua")
    return out


# =============================================================================
# ARGS + CONFIG MERGE
# =============================================================================

def _parse_args(argv=None):
    today = datetime.date.today().strftime("%Y-%m-%d")
    p = argparse.ArgumentParser(description="Tải và giải mã số liệu Quantrac, không GUI.")
    p.add_argument("--config", default=None,
                    help=f"đường dẫn config.ini (mặc định: {CONFIG_PATH})")
    p.add_argument("--ftp-host", default=None, help="bắt buộc, trừ khi đã có trong config.ini")
    p.add_argument("--ftp-user", default=None, help="bắt buộc, trừ khi đã có trong config.ini")
    p.add_argument("--ftp-pass", default=None, help="bắt buộc, trừ khi đã có trong config.ini")
    p.add_argument("--remote-dir", default=None)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--parallel-workers", type=int, default=None)
    p.add_argument("--start-date", default=today, help="YYYY-MM-DD, mặc định hôm nay")
    p.add_argument("--end-date", default=today, help="YYYY-MM-DD, mặc định hôm nay")
    return p.parse_args(argv)


def _build_cfg(args) -> dict:
    try:
        start = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("--start-date/--end-date phải theo định dạng YYYY-MM-DD")
    if end < start:
        raise ValueError("--end-date phải sau hoặc bằng --start-date")

    config_path = args.config or CONFIG_PATH
    if not os.path.isfile(config_path):
        _write_default_config(config_path)
        _log("INFO", f"Đã tạo config.ini mẫu tại {config_path}, điền FTP host/user/pass rồi chạy lại.")
    overrides = load_config_file(config_path)

    ftp_host = args.ftp_host or overrides.get("ftp_host", "")
    ftp_user = args.ftp_user or overrides.get("ftp_user", "")
    ftp_pass = args.ftp_pass or overrides.get("ftp_pass", "")
    if not (ftp_host and ftp_user and ftp_pass):
        raise ValueError(
            "Thiếu ftp_host/ftp_user/ftp_pass - điền vào "
            f"{config_path} hoặc truyền qua --ftp-host/--ftp-user/--ftp-pass")

    return {
        "ftp_host": ftp_host,
        "ftp_user": ftp_user,
        "ftp_pass": ftp_pass,
        "ftp_timeout": FTP_TIMEOUT,
        "retry_temp": RETRY_TEMP,
        "retry_wait": RETRY_WAIT,
        "stability_check": STABILITY_CHECK,
        "stability_wait": STABILITY_WAIT,
        "parallel_workers": max(
            args.parallel_workers or overrides.get("parallel_workers", _DEFAULT_PARALLEL_WORKERS), 1),
        "remote_dir": args.remote_dir or overrides.get("remote_dir", _DEFAULT_REMOTE_DIR),
        "local_dir": TEMP_DL_DIR,
        "output_dir": args.output_dir or overrides.get("output_dir", DEFAULT_OUTPUT_DIR),
        "start_date": start,
        "end_date": end,
    }


def _dates_in_range(start: datetime.datetime, end: datetime.datetime) -> list:
    """Every calendar date (as 'YYYY-MM-DD') from start to end, inclusive."""
    dates = []
    day, last = start.date(), end.date()
    while day <= last:
        dates.append(day.strftime("%Y-%m-%d"))
        day += datetime.timedelta(days=1)
    return dates


def _score_days(local_files: list, start_date: datetime.datetime,
                 end_date: datetime.datetime, output_dir: str) -> dict:
    """Score every date in range that already has a forecast_YYYYMMDD.csv on
    disk - dates without one are skipped, same rule as runner.py's Runner._score_days."""
    from pipeline import match_score as pipeline_score

    exported = {}
    for date_key in _dates_in_range(start_date, end_date):
        ymd = date_key.replace("-", "")
        forecast_path = os.path.join(output_dir, f"forecast_{ymd}.csv")
        if not os.path.isfile(forecast_path):
            continue
        date_files = [f for f in local_files
                      if (dt := parse_obs_dt(f)) and dt.strftime("%Y-%m-%d") == date_key]
        if not date_files:
            continue
        try:
            exported.update(pipeline_score.export_forecast_score(
                date_files, forecast_path, output_dir))
        except Exception as e:
            _logger.exception("export_forecast_score thất bại cho %s", date_key)
            _log("ERR", f"Chấm điểm dự báo {date_key} thất bại: {type(e).__name__}: {e}")
    return exported


def run(cfg: dict) -> int:
    """Runs fetch, then decode+score if there's anything to process. Returns
    a process exit code (0 ok, 1 fetch failed, 2 fetch ok but decode failed)."""
    try:
        dl = pipeline_fetch.fetch_files(cfg, log=_log, progress=_progress)
    except Exception as e:
        _logger.exception("fetch_files thất bại")
        _log("ERR", f"{type(e).__name__}: {e}")
        return 1

    miss = dl.get("missing") or []
    if miss:
        _log("WARN", f"Thiếu {len(miss)} file trên server")
    if not dl["files"]:
        _log("WARN", "Không có dữ liệu để xử lý")
        return 0

    try:
        from pipeline import decode_files as pipeline_decode
        output_dir = os.path.abspath(cfg["output_dir"])
        os.makedirs(output_dir, exist_ok=True)
        history_files = pipeline_decode.export_history_by_date(sorted(dl["files"]), output_dir)
        score_files = _score_days(dl["files"], cfg["start_date"], cfg["end_date"], output_dir)
    except Exception as e:
        _logger.exception("export_history_by_date thất bại")
        _log("ERR", f"Xử lý số liệu thất bại (đã tải xong file): {type(e).__name__}: {e}")
        return 2

    for date_key, info in sorted(history_files.items()):
        _log("OK", f"{os.path.basename(info['csv'])} ({info['records']} record)")
    for date_key, info in sorted(score_files.items()):
        _log("OK", f"{os.path.basename(info['csv'])} ({info['records']} dòng chấm điểm)")
    return 0


def main(argv=None) -> int:
    log_utils.setup_file_logging()
    args = _parse_args(argv)
    try:
        cfg = _build_cfg(args)
    except ValueError as e:
        _log("ERR", str(e))
        return 1
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
