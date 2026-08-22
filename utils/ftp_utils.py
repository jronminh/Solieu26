"""
ftp_utils.py
====================
Generic FTP-download primitives: fetch one file with a '.part' + atomic
replace so no half-written file is ever left behind.
"""

import os
import time
from ftplib import FTP, error_perm, error_temp


def _is_stable(ftp: FTP, filename: str, wait_seconds: float) -> bool:
    """False only when 2 SIZE calls `wait_seconds` apart both succeed and
    disagree — proof the file is still being written server-side right now.
    Any other outcome (SIZE unsupported/failing, file not there yet) returns
    True: not enough evidence to hold off, so the caller proceeds to the
    normal retrbinary attempt and lets ITS outcome (success/missing) decide."""
    try:
        first = ftp.size(filename)
    except (error_perm, error_temp, OSError):
        return True
    time.sleep(wait_seconds)
    try:
        second = ftp.size(filename)
    except (error_perm, error_temp, OSError):
        return True
    return first == second


def _size_ok(ftp: FTP, filename: str, tmp_path: str, log) -> bool:
    """True if the server's SIZE for `filename` matches the file just written
    to `tmp_path`, guarding against a file that looks complete locally but was
    caught mid-write server-side. SIZE itself failing or going unanswered is
    NOT treated as evidence of a truncated file (some servers just don't
    support it) — the file is accepted, same as before this check existed."""
    try:
        server_size = ftp.size(filename)
    except (error_perm, error_temp, OSError):
        if log:
            log("WARN", f"Không kiểm tra được SIZE {filename}, chấp nhận file đã tải")
        return True
    if server_size is None:
        return True
    return server_size == os.path.getsize(tmp_path)


def download_one(ftp: FTP, filename: str, local_path: str,
                  retry_temp: int = 0, retry_wait: int = 2, log=None,
                  stability_check: bool = True, stability_wait: float = 1) -> int:
    """
    Download ONE file (bare name) from the FTP's current directory to local.
    Uses a '.part' temp file + atomic os.replace → no half-written file left
    behind, plus a SIZE comparison before the replace (see _size_ok) so a file
    truncated server-side (caught mid-write) doesn't get accepted as complete.
    If stability_check, also polls SIZE twice stability_wait apart BEFORE
    attempting the transfer (see _is_stable), so a file still being written
    isn't grabbed mid-write in the first place. Both a SIZE mismatch and an
    unstable poll are treated as transient and share retry_temp's budget.

    0 success · 1 already exists · 2 could not download.
    """
    if os.path.isfile(local_path):
        return 1

    tmp = local_path + ".part"
    attempts = retry_temp + 1
    for attempt in range(attempts):
        if stability_check and not _is_stable(ftp, filename, stability_wait):
            transient = True
        else:
            try:
                with open(tmp, "wb") as f:
                    ftp.retrbinary(f"RETR {filename}", f.write)
            except error_temp:
                transient = True
            except (error_perm, OSError, EOFError):
                if os.path.exists(tmp):
                    os.remove(tmp)
                return 2
            else:
                transient = not _size_ok(ftp, filename, tmp, log)

        if not transient:
            os.replace(tmp, local_path)
            return 0

        if os.path.exists(tmp):
            os.remove(tmp)
        if attempt < attempts - 1:
            time.sleep(retry_wait)
            continue
        return 2

    return 2


def fetch_and_bucket(ftp: FTP, filename: str, local_dir: str, retry_temp: int, retry_wait: int,
                      log, buckets: dict, stability_check: bool = True, stability_wait: float = 1) -> int:
    """Download one file, log the outcome, and sort it into the right bucket
    (buckets = {"files","downloaded","skipped","missing"}, each a list, shared
    across the whole batch). Returns the raw status for the progress callback."""
    local_path = os.path.join(local_dir, filename)
    status = download_one(ftp, filename, local_path, retry_temp=retry_temp, retry_wait=retry_wait, log=log,
                           stability_check=stability_check, stability_wait=stability_wait)
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
