"""
headless/cli_runner.py
====================
One-shot CLI entry point for pipeline.fetch -> pipeline.decode_files, with no
Tkinter/GUI dependency: all inputs come from command-line arguments, output
goes to stdout (plus the usual rotating file log from utils/log_utils.py).

Runs synchronously on the main thread - fetch_files()/download_files() already
use their own worker threads internally for parallel_workers > 1, so no extra
queue/poll layer (like runner.py's worker+poll split, which exists only to
keep a Tkinter mainloop responsive) is needed here.

Usage:
    python -m headless.cli_runner --ftp-host HOST --ftp-user USER --ftp-pass PASS \
        --start-date 2026-08-20 --end-date 2026-08-24
"""

import argparse
import datetime
import os
import sys

from utils import config_utils as config
from utils import log_utils
from utils.filename_utils import parse_obs_dt
from pipeline import fetch as pipeline_fetch

_logger = log_utils.get_logger("cli_runner")


def _log(level: str, msg: str):
    print(f"[{level}] {msg}")


def _progress(done, total, status, filename):
    print(f"\r{done}/{total} {filename}", end="", flush=True)
    if done == total:
        print()


def _parse_args(argv=None):
    today = datetime.date.today().strftime("%Y-%m-%d")
    p = argparse.ArgumentParser(description="Tải và giải mã số liệu Quantrac, không GUI.")
    p.add_argument("--ftp-host", required=True)
    p.add_argument("--ftp-user", required=True)
    p.add_argument("--ftp-pass", required=True)
    p.add_argument("--remote-dir", default="/Quantrac")
    p.add_argument("--output-dir", default=config.DEFAULT_OUTPUT_DIR)
    p.add_argument("--parallel-workers", type=int, default=1)
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

    return {
        "ftp_host": args.ftp_host,
        "ftp_user": args.ftp_user,
        "ftp_pass": args.ftp_pass,
        "ftp_timeout": config.FTP_TIMEOUT,
        "retry_temp": config.RETRY_TEMP,
        "retry_wait": config.RETRY_WAIT,
        "stability_check": config.STABILITY_CHECK,
        "stability_wait": config.STABILITY_WAIT,
        "parallel_workers": max(args.parallel_workers, 1),
        "remote_dir": args.remote_dir,
        "local_dir": config.TEMP_DL_DIR,
        "output_dir": args.output_dir,
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
