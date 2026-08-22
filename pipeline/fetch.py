"""
pipeline/fetch.py
====================
Khối 1 (lấy file số liệu): toàn bộ tầng FTP, độc lập hoàn toàn với khối decode và khối chấm điểm.
Dùng qua fetch_files() (đầu vào cfg, log callback dùng level cố định INFO/OK/SKIP/MISS/WARN/ERR); không có demo CLI, chạy trực tiếp cần config FTP thật qua main.py.

download_files() tự quản lý mọi kết nối FTP nó cần: một hàng đợi cụm
(năm/tháng) dùng chung, N worker (cfg['parallel_workers'], mặc định 1) mỗi
worker tự connect+login một connection riêng rồi rút cụm tới khi hết việc.
N=1 vẫn đi qua đúng cơ chế này — chỉ 1 worker rút hàng đợi FIFO tuần tự,
không có tranh chấp — nên không cần nhánh code riêng cho N=1: thứ tự cwd/tải
giống hệt một vòng lặp tuần tự vì các cụm được xếp sẵn theo đúng thứ tự thời
gian trước khi đưa vào hàng đợi.
"""

import datetime
import os
import queue
import threading
import time
from ftplib import FTP, error_perm, error_temp

from utils.config_utils import FTP_TIMEOUT
from utils.filename_utils import quantrac_filename_at
from utils.ftp_utils import fetch_and_bucket
from utils.mtime_index import load_index, save_index

MTIME_INDEX_FILENAME = "mtime_index.json"
_CONNECT_MAX_ATTEMPTS = 3   # 1 lần thử đầu + tối đa 2 lần thử lại khi gặp lỗi tạm (vd 421)


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


def _worker_connect(cfg: dict, log):
    """One connect+login for a single worker. Retries specifically on
    error_temp (covers FTP 421 'too many connections') with cfg's retry_wait
    as backoff — IIS FTP enforces a per-user/per-IP connection cap, so a busy
    pool can legitimately see this transiently. Any other failure (bad
    credentials, host unreachable) is not retried. Raises on final failure;
    caller decides whether that's fatal for the whole run or just this worker."""
    host = cfg["ftp_host"]
    timeout = cfg.get("ftp_timeout", FTP_TIMEOUT)
    retry_wait = cfg.get("retry_wait", 2)
    last_exc = None
    for attempt in range(_CONNECT_MAX_ATTEMPTS):
        try:
            ftp = FTP(host, timeout=timeout)
            ftp.login(cfg["ftp_user"], cfg["ftp_pass"])
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


def download_files(cfg: dict, log, progress=None, stop_event: threading.Event = None) -> dict:
    """
    Download hourly bulletin files into cfg['local_dir'], from cfg['start_date']
    through cfg['end_date'] (inclusive), using cfg.get('parallel_workers', 1)
    worker threads (each with its own FTP connection) draining a shared
    queue of (năm, tháng) clusters in chronological order.

    Before each file, compares server MLSD facts (fetched once per cluster)
    against cfg['local_dir']'s mtime index (utils/mtime_index.py) and drops
    the local copy if the server's is newer/different in size, so a
    corrected/re-uploaded file gets re-fetched instead of skipped forever.

    stop_event, if given, lets a caller ask running workers to stop early
    between clusters/files — they close their connection and return, no
    UI wiring for this yet (no "Hủy" button), just the mechanism.

    Raises iff EVERY worker failed to even connect — nothing could be
    attempted at all; a partial failure (some workers connected, one hit a
    persistent 421) instead reports those hours as missing and returns
    normally, since the other workers made real progress.

    Returns a dict: {"files","downloaded","skipped","missing"}.
    """
    start_date = cfg["start_date"]
    end_date   = cfg["end_date"]
    remote_dir = cfg["remote_dir"].rstrip("/")
    local_dir  = cfg["local_dir"]
    retry_temp = cfg.get("retry_temp", 0)
    retry_wait = cfg.get("retry_wait", 2)
    stability_check = cfg.get("stability_check", True)
    stability_wait = cfg.get("stability_wait", 1)
    n_workers = max(1, cfg.get("parallel_workers", 1))
    os.makedirs(local_dir, exist_ok=True)

    index_path = os.path.join(local_dir, MTIME_INDEX_FILENAME)
    index = load_index(index_path)
    index_lock = threading.Lock()

    hours = expected_hours(start_date, end_date)
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
            ftp = _worker_connect(cfg, log)
        except Exception as e:
            with connect_lock:
                connect_errors.append(e)
            return   # queue untouched; other workers (if any) still drain it fully

        with connect_lock:
            connected_count["n"] += 1
        local_buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
        try:
            while not (stop_event is not None and stop_event.is_set()):
                try:
                    target_dir, cluster_hours = q.get_nowait()
                except queue.Empty:
                    break

                try:
                    ftp.cwd(target_dir)
                except (error_perm, error_temp) as e:
                    log("ERR", f"Không truy cập được thư mục {target_dir}: {e}")
                    _mark_cluster_missing(cluster_hours, local_buckets, progress,
                                          counter, counter_lock, total)
                    continue

                dir_facts = _dir_facts(ftp)
                for ts in cluster_hours:
                    if stop_event is not None and stop_event.is_set():
                        break
                    filename = quantrac_filename_at(ts)
                    with index_lock:
                        _refresh_stale_local(filename, local_dir, dir_facts, index)
                    status = fetch_and_bucket(
                        ftp, filename, local_dir, retry_temp, retry_wait, log, local_buckets,
                        stability_check=stability_check, stability_wait=stability_wait)
                    with index_lock:
                        _record_index(filename, dir_facts, index)
                    with counter_lock:
                        counter["done"] += 1
                        done = counter["done"]
                    if progress:
                        progress(done, total, status, filename)
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
        raise connect_errors[0]

    buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
    for b in buckets_list:
        for key in buckets:
            buckets[key].extend(b[key])

    save_index(index_path, index)
    return buckets


# =============================================================================
# ĐIỂM VÀO CHO CALLER
# =============================================================================

def fetch_files(cfg: dict, log, progress=None) -> dict:
    """
    Chạy trọn khối 1 qua download_files() (tự quản lý kết nối/worker).
    Raises nếu KHÔNG worker nào kết nối được; caller (runner.py) tự bắt và
    báo lỗi riêng, không ảnh hưởng gì tới việc khối này đã tự chứa trọn vẹn
    tầng FTP.

    Trả về đúng dict bucket của download_files()
    ({"files","downloaded","skipped","missing"}): "files" là MỌI file cục bộ
    có sẵn (tải mới lẫn đã có từ trước), không phải chỉ file tải mới.
    """
    log("INFO", f"Thư mục tải tạm: {cfg.get('local_dir')}")
    dl = download_files(cfg, log=log, progress=progress)

    if dl["files"]:
        log("INFO", f"Tổng số file có sẵn: {len(dl['files'])}")
    else:
        log("WARN", "Không tải được file nào")
    return dl
