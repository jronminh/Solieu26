"""
fetch/fetch.py
====================
CLI độc lập để tải file số liệu Quantrac qua FTP. Không có API để import —
mọi tham số (host/user/pass, khoảng ngày, thư mục, số worker, timeout, số
lần thử lại, kiểm tra file ổn định...) truyền trực tiếp qua cờ dòng lệnh,
không đọc config file.

Chạy: python fetch/fetch.py --ftp-host <host> --ftp-user <user> --ftp-pass <mat_khau> \
    --start-date 2026-08-20 --end-date 2026-08-24

Tự quản lý mọi kết nối FTP nó cần: một hàng đợi cụm (năm/tháng) dùng chung,
N worker (--parallel-workers, mặc định 1) mỗi worker tự connect+login một
connection riêng rồi rút cụm tới khi hết việc. N=1 vẫn đi qua đúng cơ chế
này — chỉ 1 worker rút hàng đợi FIFO tuần tự, không có tranh chấp — nên
không cần nhánh code riêng cho N=1: thứ tự cwd/tải giống hệt một vòng lặp
tuần tự vì các cụm được xếp sẵn theo đúng thứ tự thời gian trước khi đưa vào
hàng đợi.
"""

import argparse
import datetime
import os
import queue
import sys
import threading
import time
from ftplib import FTP, error_perm, error_temp

try:
    from .filename_utils import quantrac_filename_at
    from .ftp_utils import fetch_and_bucket
    from .mtime_index import load_index, save_index
    from . import log_utils
except ImportError:
    # chạy trực tiếp "python fetch/fetch.py" (không phải -m fetch.fetch) thì
    # đây không phải package, không import relative được — fallback sang
    # import tuyệt đối, hoạt động vì Python tự thêm thư mục chứa fetch.py
    # (fetch/) vào sys.path khi chạy trực tiếp.
    from filename_utils import quantrac_filename_at
    from ftp_utils import fetch_and_bucket
    from mtime_index import load_index, save_index
    import log_utils

MTIME_INDEX_FILENAME = "mtime_index.json"
_CONNECT_MAX_ATTEMPTS = 3   # 1 lần thử đầu + tối đa 2 lần thử lại khi gặp lỗi tạm (vd 421)
_DEFAULT_FTP_TIMEOUT = 30   # seconds; giá trị mặc định của cờ --ftp-timeout
_logger = log_utils.get_logger("fetch")


# =============================================================================
# FTP LAYER: FILE DOWNLOAD  (log/progress via callback)
# =============================================================================

def _expected_hours(start_date: datetime.datetime, end_date: datetime.datetime) -> list:
    """Every hourly timestamp the download loop will attempt, in order
    (inclusive of both ends)."""
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


def _group_into_clusters(hours: list, remote_dir: str) -> list:
    """Group `hours` (already chronological) into (target_dir, [hours in that
    dir]) clusters by year/month, preserving their original order. This is
    the cwd-once-per-month optimization expressed as clustering instead of a
    per-hour "did the dir change" check — a single worker draining these in
    order reproduces the exact same cwd call sequence as the old sequential
    per-hour loop did."""
    clusters = []
    current_dir = None
    current_hours = []
    for ts in hours:
        target_dir = f"{remote_dir}/{ts:%Y}/{ts:%m}"
        if target_dir != current_dir:
            if current_hours:
                clusters.append((current_dir, current_hours))
            current_dir = target_dir
            current_hours = []
        current_hours.append(ts)
    if current_hours:
        clusters.append((current_dir, current_hours))
    return clusters


def _worker_connect(ftp_host: str, ftp_user: str, ftp_pass: str,
                     ftp_timeout: int, retry_wait: int, log) -> FTP:
    """One connect+login for a single worker. Retries specifically on
    error_temp (covers FTP 421 'too many connections') with retry_wait as
    backoff — IIS FTP enforces a per-user/per-IP connection cap, so a busy
    pool can legitimately see this transiently. Any other failure (bad
    credentials, host unreachable) is not retried. Raises on final failure;
    caller decides whether that's fatal for the whole run or just this worker."""
    last_exc = None
    for attempt in range(_CONNECT_MAX_ATTEMPTS):
        try:
            ftp = FTP(ftp_host, timeout=ftp_timeout)
            ftp.login(ftp_user, ftp_pass)
            return ftp
        except error_temp as e:
            last_exc = e
            if attempt < _CONNECT_MAX_ATTEMPTS - 1:
                log("WARN", f"Kết nối FTP tạm thời bị từ chối (có thể vượt trần kết nối), "
                            f"thử lại sau {retry_wait}s: {e}")
                time.sleep(retry_wait)
                continue
            raise
    raise last_exc


def _dir_facts(ftp: FTP) -> dict:
    """{filename: MLSD facts} for the FTP's CURRENT directory, fetched once
    via MLSD (RFC 3659) — reused for every file in that directory, never
    queried per-file. {} if the server doesn't support MLSD (older/non-
    compliant FTP servers): callers then just trust local files, same as
    before the mtime index existed."""
    try:
        return dict(ftp.mlsd())
    except (error_perm, error_temp, OSError):
        return {}


def _refresh_stale_local(filename: str, local_dir: str, dir_facts: dict, index: dict):
    """Delete the local copy of `filename` iff: the server reports facts for
    it, the local file exists, AND the index already has an OLDER/different
    entry for it — so fetch_and_bucket() re-downloads it fresh right after.
    No index entry yet (never indexed — e.g. upgrading from a version
    without this index) → trust the local file as-is, don't force a refetch;
    the entry gets backfilled by _record_index() below regardless."""
    facts = dir_facts.get(filename)
    if not facts:
        return
    local_path = os.path.join(local_dir, filename)
    if not os.path.isfile(local_path):
        return
    entry = index.get(filename)
    if entry is None:
        return
    if (facts.get("modify", "") > entry.get("mtime", "")
            or str(facts.get("size", "")) != str(entry.get("size", ""))):
        os.remove(local_path)


def _record_index(filename: str, dir_facts: dict, index: dict):
    """Record the just-observed server facts for `filename`, if any — runs
    after every fetch_and_bucket() call, downloaded or skipped alike, so the
    index catches up ("lazy backfill") even for files it had no prior entry
    for."""
    facts = dir_facts.get(filename)
    if not facts:
        return
    try:
        size = int(facts.get("size"))
    except (TypeError, ValueError):
        size = None
    index[filename] = {"mtime": facts.get("modify", ""), "size": size}


def _mark_cluster_missing(cluster_hours: list, buckets: dict, progress,
                           counter: dict, counter_lock: threading.Lock, total: int):
    """Every hour in a cluster that could never be attempted (cwd failed, or
    no worker ever connected) goes straight to missing — no per-file RETR
    attempt. Fixes a quirk in the old per-hour loop: a failed cwd used to
    mark only the first hour of that month via a clear error, while the rest
    silently fell through to a RETR in the wrong directory (still ending up
    missing, just via a confusing 550 instead of one clear reason)."""
    for ts in cluster_hours:
        filename = quantrac_filename_at(ts)
        buckets["missing"].append(filename)
        with counter_lock:
            counter["done"] += 1
            done = counter["done"]
        if progress:
            progress(done, total, 2, filename)


# =============================================================================
# CLI
# =============================================================================

DEFAULT_LOCAL_DIR = os.path.join(os.path.expanduser("~"), "solieu26_dl", "data")

_EXAMPLE_CMD = (
    "python fetch/fetch.py --ftp-host <host> --ftp-user <user> --ftp-pass <mat_khau> "
    "--start-date 2026-08-20 --end-date 2026-08-24"
)


def _cli_log(level: str, msg: str):
    print(f"[{level}] {msg}")


def _cli_progress(done, total, status, filename):
    print(f"\r{done}/{total} {filename}", end="", flush=True)
    if done == total:
        print()


def _parse_args(argv=None):
    today = datetime.date.today().strftime("%Y-%m-%d")
    p = argparse.ArgumentParser(
        description="Tải file số liệu Quantrac qua FTP, không GUI, không decode/chấm điểm.",
        epilog=f"Ví dụ: {_EXAMPLE_CMD}")
    p.add_argument("--ftp-host", default=None)
    p.add_argument("--ftp-user", default=None)
    p.add_argument("--ftp-pass", default=None)
    p.add_argument("--remote-dir", default="/Quantrac")
    p.add_argument("--local-dir", default=DEFAULT_LOCAL_DIR)
    p.add_argument("--parallel-workers", type=int, default=1)
    p.add_argument("--start-date", default=today, help="YYYY-MM-DD, mặc định hôm nay")
    p.add_argument("--end-date", default=today, help="YYYY-MM-DD, mặc định hôm nay")
    p.add_argument("--ftp-timeout", type=int, default=_DEFAULT_FTP_TIMEOUT,
                    help="giây chờ kết nối FTP, mặc định %(default)s")
    p.add_argument("--retry-temp", type=int, default=0,
                    help="số lần thử lại khi server báo bận (lỗi tạm thời), mặc định %(default)s")
    p.add_argument("--retry-wait", type=int, default=2,
                    help="giây chờ giữa các lần thử lại, mặc định %(default)s")
    p.add_argument("--stability-check", action=argparse.BooleanOptionalAction, default=True,
                    help="poll SIZE 2 lần trước khi tải để tránh tải file server đang ghi dở, mặc định bật")
    p.add_argument("--stability-wait", type=float, default=1,
                    help="giây chờ giữa 2 lần poll SIZE, mặc định %(default)s")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if not (args.ftp_host and args.ftp_user and args.ftp_pass):
        _cli_log("ERR", f"Thiếu --ftp-host/--ftp-user/--ftp-pass. Ví dụ câu lệnh đầy đủ:\n  {_EXAMPLE_CMD}")
        return 1
    try:
        start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        _cli_log("ERR", "--start-date/--end-date phải theo định dạng YYYY-MM-DD. Ví dụ câu lệnh đầy đủ:\n"
                         f"  {_EXAMPLE_CMD}")
        return 1
    if end_date < start_date:
        _cli_log("ERR", "--end-date phải sau hoặc bằng --start-date")
        return 1

    remote_dir = args.remote_dir.rstrip("/")
    local_dir = args.local_dir
    n_workers = max(1, args.parallel_workers)
    os.makedirs(local_dir, exist_ok=True)
    _cli_log("INFO", f"Thư mục tải tạm: {local_dir}")
    _logger.debug("fetch: %s -> %s, remote_dir=%s, %d worker",
                   start_date, end_date, remote_dir, n_workers)

    index_path = os.path.join(local_dir, MTIME_INDEX_FILENAME)
    index = load_index(index_path)
    index_lock = threading.Lock()

    hours = _expected_hours(start_date, end_date)
    total = len(hours)
    clusters = _group_into_clusters(hours, remote_dir)
    q = queue.Queue()
    for cluster in clusters:
        q.put(cluster)

    counter = {"done": 0}
    counter_lock = threading.Lock()
    buckets_list = []
    buckets_lock = threading.Lock()
    connected_count = {"n": 0}
    connect_lock = threading.Lock()
    connect_errors = []

    def worker():
        try:
            ftp = _worker_connect(args.ftp_host, args.ftp_user, args.ftp_pass,
                                   args.ftp_timeout, args.retry_wait, _cli_log)
        except Exception as e:
            _logger.exception("Kết nối FTP thất bại")
            with connect_lock:
                connect_errors.append(e)
            return   # queue untouched; other workers (if any) still drain it fully

        with connect_lock:
            connected_count["n"] += 1
        local_buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
        try:
            while True:
                try:
                    target_dir, cluster_hours = q.get_nowait()
                except queue.Empty:
                    break

                try:
                    ftp.cwd(target_dir)
                except (error_perm, error_temp) as e:
                    _logger.debug("cwd %s thất bại: %s", target_dir, e)
                    _cli_log("ERR", f"Không truy cập được thư mục {target_dir}: {e}")
                    _mark_cluster_missing(cluster_hours, local_buckets, _cli_progress,
                                          counter, counter_lock, total)
                    continue

                dir_facts = _dir_facts(ftp)
                _logger.debug("cwd %s ok, %d giờ trong cụm", target_dir, len(cluster_hours))
                for ts in cluster_hours:
                    filename = quantrac_filename_at(ts)
                    with index_lock:
                        _refresh_stale_local(filename, local_dir, dir_facts, index)
                    status = fetch_and_bucket(
                        ftp, filename, local_dir, args.retry_temp, args.retry_wait, _cli_log, local_buckets,
                        stability_check=args.stability_check, stability_wait=args.stability_wait)
                    with index_lock:
                        _record_index(filename, dir_facts, index)
                    with counter_lock:
                        counter["done"] += 1
                        done = counter["done"]
                    _cli_progress(done, total, status, filename)
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
            with buckets_lock:
                buckets_list.append(local_buckets)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if connected_count["n"] == 0:
        save_index(index_path, index)
        e = connect_errors[0]
        _cli_log("ERR", f"{type(e).__name__}: {e}")
        return 1

    buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
    for b in buckets_list:
        for key in buckets:
            buckets[key].extend(b[key])
    save_index(index_path, index)

    if buckets["files"]:
        _cli_log("INFO", f"Tổng số file có sẵn: {len(buckets['files'])}")
    else:
        _cli_log("WARN", "Không tải được file nào")
    return 0


if __name__ == "__main__":
    sys.exit(main())
