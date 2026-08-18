"""
pipeline_fetch.py
====================
Khối 1 (lấy file số liệu) — toàn bộ tầng FTP, đứng độc lập hoàn toàn: không
import pipeline_csv.py, bulletin/decode.py hay bất cứ gì thuộc khối "xử lý
readable" (pipeline_csv.py) hay khối chấm điểm (pipeline_scoring.py/
scoring/). Module này vỡ hay lành không phụ thuộc 2 khối kia, và ngược lại.

fetch_files() là điểm vào duy nhất caller (gui.py) cần: connect FTP → login
→ download_files() → quit, trả về danh sách file cục bộ đã có sẵn (tải mới
hoặc đã tồn tại từ trước). Không biết gì về decode/CSV — "tải xong" ở đây
chỉ có nghĩa là "có file trên đĩa hay không", ai dùng file đó làm gì là việc
của caller.

Mỗi lời gọi log(level, msg) dùng LEVEL 4 ký tự cố định:
    INFO  general info            OK    success
    SKIP  skipped (already there) MISS  file missing on server
    WARN  warning                 ERR   error

Chạy trực tiếp (python pipeline_fetch.py) không có demo CLI — cần config FTP
thật, dùng qua gui.py.
"""

import datetime
import os
from ftplib import FTP, error_perm, error_temp

from utils.config_utils import FTP_TIMEOUT
from bulletin.filename import quantrac_filename_at
from utils.ftp_utils import fetch_and_bucket


# =============================================================================
# FTP LAYER — FILE DOWNLOAD  (log/progress via callback)
# =============================================================================

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
                status = fetch_and_bucket(ftp, filename, local_dir, retry_temp, retry_wait, log, buckets)
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

            status = fetch_and_bucket(ftp, filename, local_dir, retry_temp, retry_wait, log, buckets)
            if progress:
                progress(i + 1, total, status)
    finally:
        ftp.cwd(origin)

    return buckets


# =============================================================================
# ĐIỂM VÀO CHO CALLER — vòng đời FTP trọn vẹn (connect → login → download → quit)
# =============================================================================

def fetch_files(cfg: dict, log, progress=None) -> dict:
    """
    Connect FTP (cfg['ftp_host']/ftp_user/ftp_pass/ftp_timeout) → login →
    download_files() → quit. Raises on connect/login failure — caller (gui.py)
    tự bắt và báo lỗi riêng, KHÔNG ảnh hưởng gì tới việc khối này đã tự chứa
    trọn vẹn tầng FTP.

    Trả về đúng dict bucket của download_files()
    ({"files","downloaded","skipped","missing"}) — "files" là MỌI file cục bộ
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
