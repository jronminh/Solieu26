"""
pipeline/fetch.py
====================
Khối 1 (lấy file số liệu): toàn bộ tầng FTP, độc lập hoàn toàn với khối decode và khối chấm điểm.
Dùng qua fetch_files() (đầu vào cfg, log callback dùng level cố định INFO/OK/SKIP/MISS/WARN/ERR); không có demo CLI, chạy trực tiếp cần config FTP thật qua main.py.
"""

import datetime
import os
from ftplib import FTP, error_perm, error_temp

from utils.config_utils import FTP_TIMEOUT
from utils.filename_utils import quantrac_filename_at
from utils.ftp_utils import fetch_and_bucket


# =============================================================================
# FTP LAYER: FILE DOWNLOAD  (log/progress via callback)
# =============================================================================

def expected_hours(start_date: datetime.datetime, end_date: datetime.datetime) -> list:
    """Every hourly timestamp download_files() will attempt, in order (inclusive
    of both ends). Exposed so callers (the "Hàng đợi" queue table in main.py)
    can preview the file list before a download actually starts."""
    if start_date.date() == end_date.date():
        return [start_date.replace(hour=h) for h in range(24)]
    hours = []
    day = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last_day:
        for hour in range(24):
            hours.append(day.replace(hour=hour))
        day += datetime.timedelta(days=1)
    return hours


def download_files(ftp: FTP, cfg: dict, log, progress=None) -> dict:
    """
    Download hourly bulletin files into cfg['local_dir'], from cfg['start_date']
    through cfg['end_date'] (inclusive).

    Same day (start_date == end_date): cwd once into that date's remote
    directory and download the full day [00:00, 23:00], bailing out early if
    the directory is unreachable. Different days: walks every hour from
    00:00 of start_date through 23:00 of end_date, cwd'ing into
    "<remote_dir>/YYYY/MM" again only when the year/month actually changes.

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
        hours = expected_hours(start_date, end_date)
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
                status = fetch_and_bucket(ftp, filename, local_dir, retry_temp, retry_wait, log, buckets)
                if progress:
                    progress(i + 1, total, status, filename)
        finally:
            ftp.cwd(origin)
        return buckets

    hours = expected_hours(start_date, end_date)
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
                        progress(i + 1, total, 2, filename)
                    continue

            status = fetch_and_bucket(ftp, filename, local_dir, retry_temp, retry_wait, log, buckets)
            if progress:
                progress(i + 1, total, status, filename)
    finally:
        ftp.cwd(origin)

    return buckets


# =============================================================================
# ĐIỂM VÀO CHO CALLER: vòng đời FTP trọn vẹn (connect → login → download → quit)
# =============================================================================

def fetch_files(cfg: dict, log, progress=None) -> dict:
    """
    Connect FTP (cfg['ftp_host']/ftp_user/ftp_pass/ftp_timeout) → login →
    download_files() → quit. Raises on connect/login failure; caller (runner.py)
    tự bắt và báo lỗi riêng, không ảnh hưởng gì tới việc khối này đã tự chứa
    trọn vẹn tầng FTP.

    Trả về đúng dict bucket của download_files()
    ({"files","downloaded","skipped","missing"}): "files" là MỌI file cục bộ
    có sẵn (tải mới lẫn đã có từ trước), không phải chỉ file tải mới.
    """
    log("INFO", f"Thư mục tải tạm: {cfg.get('local_dir')}")
    log("INFO", "Đang kết nối FTP…")
    ftp = FTP(cfg["ftp_host"], timeout=cfg.get("ftp_timeout", FTP_TIMEOUT))
    ftp.login(cfg["ftp_user"], cfg["ftp_pass"])
    log("OK", "Đăng nhập FTP thành công")

    try:
        dl = download_files(ftp, cfg, log=log, progress=progress)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass

    if dl["files"]:
        log("INFO", f"Tổng số file có sẵn: {len(dl['files'])}")
    else:
        log("WARN", "Không tải được file nào")
    return dl
