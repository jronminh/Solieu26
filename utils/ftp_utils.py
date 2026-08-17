"""
ftp_utils.py
====================
Generic FTP-download primitives: fetch one file with a '.part' + atomic
replace so no half-written file is ever left behind.
"""

import os
import time
from ftplib import FTP, error_perm, error_temp


def download_one(ftp: FTP, filename: str, local_path: str,
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


def fetch_and_bucket(ftp: FTP, filename: str, local_dir: str, retry_temp: int, retry_wait: int,
                      log, buckets: dict) -> int:
    """Download one file, log the outcome, and sort it into the right bucket
    (buckets = {"files","downloaded","skipped","missing"}, each a list — shared
    across the whole batch). Returns the raw status for the progress callback."""
    local_path = os.path.join(local_dir, filename)
    status = download_one(ftp, filename, local_path, retry_temp=retry_temp, retry_wait=retry_wait)
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
