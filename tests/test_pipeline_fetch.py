"""
test_pipeline_fetch.py
====================
Tests for pipeline/fetch.py: expected_hours, the unified queue/worker
download_files() (Phase 5 — cluster hàng đợi + N worker, N=1 là trường hợp
suy biến), and fetch_files()'s connect/login/quit lifecycle.

download_files() now owns every FTP connection it needs (one per worker) —
it no longer accepts a pre-connected `ftp`, so every test drives it through
`patch_ftp(ftp_world)` (patches pipeline.fetch.FTP) instead of constructing a
FakeFTP by hand. fetch_files()'s own signature never changed, so its tests
are the strongest "N=1 behaves like before" anchor: same call, same asserts.

Two tests from before Phase 5 don't carry forward, by design (see their
history in git log if needed): "restores origin dir" no longer applies
(connections are per-worker and closed right after use, nothing shared to
restore for); the old cwd-failure test documented a quirk (RETR attempted in
the wrong directory for hours after the first in a failed month) that this
phase deliberately fixes — see test_pool_cwd_failure_marks_whole_cluster_
missing_with_one_log_line below for the replacement.
"""

import datetime
import os
import threading
from ftplib import error_perm, error_temp

import pytest

from tests.fake_ftp import FakeFTP, FakeFTPWorld
from pipeline.fetch import _worker_connect, download_files, expected_hours, fetch_files
from utils import config_utils as config
from utils.mtime_index import load_index, save_index

REMOTE_DIR = "/Quantrac"


def _cfg(start, end, local_dir, **overrides):
    cfg = {
        "start_date": start,
        "end_date": end,
        "remote_dir": REMOTE_DIR,
        "local_dir": local_dir,
        "retry_temp": 0,
        "retry_wait": 0,
        "stability_check": False,   # real poll-size-hai-lần delay tested separately elsewhere
        "ftp_host": "host", "ftp_user": "u", "ftp_pass": "p",
    }
    cfg.update(overrides)
    return cfg


def _fill_day(world, dt: datetime.date, hours=range(24)):
    path = f"{REMOTE_DIR}/{dt:%Y}/{dt:%m}"
    for h in hours:
        world.add_file(path, f"Qt{dt:%y%m%d}{h:02}.txt", b"data")


# =============================================================================
# expected_hours
# =============================================================================

def test_expected_hours_same_day_is_24_hours():
    d = datetime.datetime(2026, 8, 10)
    hours = expected_hours(d, d)
    assert len(hours) == 24
    assert hours[0].hour == 0 and hours[-1].hour == 23
    assert all(h.date() == d.date() for h in hours)


def test_expected_hours_multi_day_spans_full_days():
    start = datetime.datetime(2026, 7, 31)
    end = datetime.datetime(2026, 8, 1)
    hours = expected_hours(start, end)
    assert len(hours) == 48
    assert hours[0] == datetime.datetime(2026, 7, 31, 0)
    assert hours[-1] == datetime.datetime(2026, 8, 1, 23)


# =============================================================================
# download_files: N=1 (default) — same-day
# =============================================================================

def test_download_files_same_day_downloads_all_present_files(ftp_world, patch_ftp, tmp_path):
    day = datetime.date(2026, 8, 10)
    _fill_day(ftp_world, day)
    patch_ftp(ftp_world)

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), str(tmp_path))
    result = download_files(cfg, log=lambda *a: None)

    assert len(result["downloaded"]) == 24
    assert result["missing"] == []
    assert len(ftp_world.connections) == 1
    assert ftp_world.connections[0].cwd_calls == [f"{REMOTE_DIR}/2026/08"]


# =============================================================================
# download_files: N=1 (default) — multi-day cwd-once-per-month optimization
# =============================================================================

def test_download_files_multi_day_cwds_once_per_month(ftp_world, patch_ftp, tmp_path):
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    _fill_day(ftp_world, datetime.date(2026, 8, 1))
    patch_ftp(ftp_world)

    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path))
    result = download_files(cfg, log=lambda *a: None)

    assert len(result["downloaded"]) == 48
    assert len(ftp_world.connections) == 1   # N=1 -> exactly 1 connection, whole run
    # 48 hours, 2 distinct months -> exactly 2 cwd calls, not 48
    assert ftp_world.connections[0].cwd_calls == [f"{REMOTE_DIR}/2026/07", f"{REMOTE_DIR}/2026/08"]


# =============================================================================
# download_files: cwd failure for a cluster — the FIXED behavior (Phase 5).
#
# Before this phase, a failed cwd only logged one clear ERR for the first
# hour of that month; the other hours in the same month silently fell
# through to a RETR attempted in the wrong directory (still ending up
# missing, just via a confusing extra MISS line each, not a clear reason).
# Clustering fixes this: a cwd failure marks the WHOLE cluster missing
# up front, no RETR attempted for any of its hours.
# =============================================================================

def test_pool_cwd_failure_marks_whole_cluster_missing_with_one_log_line(ftp_world, patch_ftp, tmp_path):
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    ftp_world.mark_unreachable(f"{REMOTE_DIR}/2026/08")
    patch_ftp(ftp_world)

    logs = []
    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path))
    result = download_files(cfg, log=lambda lvl, msg: logs.append((lvl, msg)))

    assert len(result["downloaded"]) == 24   # July still fine
    assert len(result["missing"]) == 24      # all 24 August hours end up missing
    err_lines = [l for l in logs if l[0] == "ERR"]
    miss_lines = [l for l in logs if l[0] == "MISS"]
    assert len(err_lines) == 1     # exactly 1 line for the whole failed cluster
    assert len(miss_lines) == 0    # no per-file MISS lines — no RETR attempted at all


# =============================================================================
# fetch_files: connect -> login -> download -> quit lifecycle (N=1, unchanged
# call convention — the strongest "still behaves like before" anchor)
# =============================================================================

def test_fetch_files_logs_in_and_quits(ftp_world, tmp_path, patch_ftp):
    _fill_day(ftp_world, datetime.date(2026, 8, 10))
    patch_ftp(ftp_world)

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), str(tmp_path),
               ftp_host="host", ftp_user="u", ftp_pass="p")
    result = fetch_files(cfg, log=lambda *a: None)

    assert len(result["downloaded"]) == 24
    assert len(ftp_world.connections) == 1
    conn = ftp_world.connections[0]
    assert conn.login_calls == [("u", "p")]
    assert conn.closed is True


def test_fetch_files_raises_when_connect_fails(ftp_world, patch_ftp, tmp_path):
    """Preserves the old documented contract: fetch_files() raises when
    nothing could be attempted at all, letting runner.py's existing
    try/except (around fetch_files()) keep handling it unchanged."""
    patch_ftp(ftp_world)
    ftp_world.login_failures = [error_perm("530 bad credentials")]
    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), str(tmp_path))

    with pytest.raises(error_perm):
        fetch_files(cfg, log=lambda *a: None)


# =============================================================================
# download_files: mtime index (Phase 3) — 4 branches from the plan
# =============================================================================

def _index_path(local_dir):
    return os.path.join(local_dir, "mtime_index.json")


def test_mtime_index_backfills_for_fresh_downloads(ftp_world, patch_ftp, tmp_path):
    """File local chưa có → tải bình thường, index được ghi nhận."""
    _fill_day(ftp_world, datetime.date(2026, 8, 10), hours=[0])
    patch_ftp(ftp_world)
    local_dir = str(tmp_path / "dl")

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), local_dir)
    result = download_files(cfg, log=lambda *a: None)

    assert "Qt26081000.txt" in result["downloaded"]
    index = load_index(_index_path(local_dir))
    assert index["Qt26081000.txt"]["size"] == len(b"data")
    assert index["Qt26081000.txt"]["mtime"] == "20260810000000"


def test_mtime_index_no_prior_entry_does_not_force_redownload(ftp_world, patch_ftp, tmp_path):
    """File local có, KHÔNG có trong index → không ép tải lại, chỉ backfill."""
    _fill_day(ftp_world, datetime.date(2026, 8, 10), hours=[0])   # server content: b"data"
    patch_ftp(ftp_world)
    local_dir = str(tmp_path / "dl")
    os.makedirs(local_dir)
    local_path = os.path.join(local_dir, "Qt26081000.txt")
    with open(local_path, "wb") as f:
        f.write(b"stale local content, never indexed")

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), local_dir)
    result = download_files(cfg, log=lambda *a: None)

    assert "Qt26081000.txt" in result["skipped"]
    with open(local_path, "rb") as f:
        assert f.read() == b"stale local content, never indexed"   # untouched
    index = load_index(_index_path(local_dir))
    assert "Qt26081000.txt" in index   # backfilled even though not force-redownloaded


def test_mtime_index_redownloads_when_server_mtime_newer(ftp_world, patch_ftp, tmp_path):
    """File local có, có trong index, mtime server mới hơn → tải lại, ghi đè."""
    path = f"{REMOTE_DIR}/2026/08"
    ftp_world.add_file(path, "Qt26081000.txt", b"new content", mtime="20260810120000")
    patch_ftp(ftp_world)
    local_dir = str(tmp_path / "dl")
    os.makedirs(local_dir)
    local_path = os.path.join(local_dir, "Qt26081000.txt")
    with open(local_path, "wb") as f:
        f.write(b"old content")
    save_index(_index_path(local_dir),
               {"Qt26081000.txt": {"mtime": "20260810000000", "size": len(b"old content")}})

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), local_dir)
    result = download_files(cfg, log=lambda *a: None)

    assert "Qt26081000.txt" in result["downloaded"]   # re-fetched, not skipped
    with open(local_path, "rb") as f:
        assert f.read() == b"new content"
    index = load_index(_index_path(local_dir))
    assert index["Qt26081000.txt"]["mtime"] == "20260810120000"


def test_mtime_index_skips_when_matching(ftp_world, patch_ftp, tmp_path):
    """Khớp → skip như hiện tại, không đụng tới file local."""
    path = f"{REMOTE_DIR}/2026/08"
    content = b"same content"
    ftp_world.add_file(path, "Qt26081000.txt", content, mtime="20260810000000")
    patch_ftp(ftp_world)
    local_dir = str(tmp_path / "dl")
    os.makedirs(local_dir)
    local_path = os.path.join(local_dir, "Qt26081000.txt")
    with open(local_path, "wb") as f:
        f.write(b"local copy, should stay untouched")
    save_index(_index_path(local_dir),
               {"Qt26081000.txt": {"mtime": "20260810000000", "size": len(content)}})

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), local_dir)
    result = download_files(cfg, log=lambda *a: None)

    assert "Qt26081000.txt" in result["skipped"]
    with open(local_path, "rb") as f:
        assert f.read() == b"local copy, should stay untouched"   # NOT overwritten


def test_mtime_index_falls_back_gracefully_without_mlsd_support(ftp_world, patch_ftp, tmp_path, monkeypatch):
    """Server không hỗ trợ MLSD → coi như trước khi có index (tin file local)."""
    _fill_day(ftp_world, datetime.date(2026, 8, 10), hours=[0])
    patch_ftp(ftp_world)
    local_dir = str(tmp_path / "dl")

    def _no_mlsd(self, *args, **kwargs):
        raise error_perm("500 MLSD not understood")
    monkeypatch.setattr(FakeFTP, "mlsd", _no_mlsd)

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), local_dir)
    result = download_files(cfg, log=lambda *a: None)

    assert "Qt26081000.txt" in result["downloaded"]
    assert load_index(_index_path(local_dir)) == {}   # nothing to backfill, MLSD unsupported


# =============================================================================
# download_files: cfg["stability_check"]/["stability_wait"] reach download_one
# (Phase 4) — stability_wait=0 keeps this instant.
# =============================================================================

def test_download_files_wires_stability_check_through_to_download_one(ftp_world, patch_ftp, tmp_path):
    day = datetime.date(2026, 8, 10)
    _fill_day(ftp_world, day, hours=[0])
    ftp_world.dirs[f"{REMOTE_DIR}/2026/08"]["Qt26081000.txt"].size_sequence = [1, 2, 3, 4]
    patch_ftp(ftp_world)
    local_dir = str(tmp_path / "dl")

    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), local_dir,
               stability_check=True, stability_wait=0, retry_temp=1)
    result = download_files(cfg, log=lambda *a: None)

    # size_sequence never settles (1,2,3,4 all differ) -> stays unstable through both
    # attempts -> the cfg-level toggle really did reach download_one, not just accepted.
    assert "Qt26081000.txt" in result["missing"]


# =============================================================================
# _worker_connect: connect+login retry logic in isolation (deterministic,
# no threading race — the pool-level 421 test below covers the concurrent case)
# =============================================================================

def test_worker_connect_retries_on_421_then_succeeds(ftp_world, patch_ftp):
    patch_ftp(ftp_world)
    ftp_world.login_failures = [error_temp("421 Too many connections"), None]
    cfg = {"ftp_host": "host", "ftp_user": "u", "ftp_pass": "p", "ftp_timeout": 5, "retry_wait": 0}

    ftp = _worker_connect(cfg, log=lambda *a: None)

    assert ftp is not None
    assert len(ftp_world.connections) == 2   # 1st attempt (failed) + 2nd (succeeded)


def test_worker_connect_gives_up_after_max_attempts(ftp_world, patch_ftp):
    patch_ftp(ftp_world)
    ftp_world.login_failures = [error_temp("421") for _ in range(5)]   # more than _CONNECT_MAX_ATTEMPTS
    cfg = {"ftp_host": "host", "ftp_user": "u", "ftp_pass": "p", "ftp_timeout": 5, "retry_wait": 0}

    with pytest.raises(error_temp):
        _worker_connect(cfg, log=lambda *a: None)


def test_worker_connect_does_not_retry_non_temp_errors(ftp_world, patch_ftp):
    patch_ftp(ftp_world)
    ftp_world.login_failures = [error_perm("530 bad credentials")]
    cfg = {"ftp_host": "host", "ftp_user": "u", "ftp_pass": "p", "ftp_timeout": 5, "retry_wait": 0}

    with pytest.raises(error_perm):
        _worker_connect(cfg, log=lambda *a: None)
    assert len(ftp_world.connections) == 1   # no retry attempted for a non-error_temp failure


# =============================================================================
# download_files: parallel_workers (Phase 5) — default, N=1 connection count,
# and the actual pool (N>=2) behavior.
# =============================================================================

def test_default_parallel_workers_is_1():
    assert config.DEFAULT_CONFIG["parallel_workers"] == 1


def test_n1_single_connection_for_multi_cluster_range(ftp_world, patch_ftp, tmp_path):
    """N=1 (default, no override) opens exactly 1 connection even across
    multiple clusters — proves N=1 doesn't secretly touch the pool machinery."""
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    _fill_day(ftp_world, datetime.date(2026, 8, 1))
    patch_ftp(ftp_world)

    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path))
    result = download_files(cfg, log=lambda *a: None)

    assert len(ftp_world.connections) == 1
    assert len(result["downloaded"]) == 48


def test_pool_uses_n_connections_and_cwds_once_per_cluster(ftp_world, patch_ftp, tmp_path):
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    _fill_day(ftp_world, datetime.date(2026, 8, 1))
    patch_ftp(ftp_world)

    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path),
               parallel_workers=2)
    result = download_files(cfg, log=lambda *a: None)

    assert len(ftp_world.connections) == 2
    assert all(c.login_calls == [("u", "p")] for c in ftp_world.connections)
    assert all(c.closed for c in ftp_world.connections)
    all_cwd_calls = [d for conn in ftp_world.connections for d in conn.cwd_calls]
    assert sorted(all_cwd_calls) == sorted([f"{REMOTE_DIR}/2026/07", f"{REMOTE_DIR}/2026/08"])
    assert len(result["downloaded"]) == 48
    assert result["missing"] == []


def test_pool_extra_workers_beyond_cluster_count_still_only_cwd_once_per_cluster(ftp_world, patch_ftp, tmp_path):
    """N=3 with only 2 clusters: all 3 workers connect (each unconditionally
    tries), but total cwd calls across every connection still equals the
    cluster count — the idle worker just finds an empty queue."""
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    _fill_day(ftp_world, datetime.date(2026, 8, 1))
    patch_ftp(ftp_world)

    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path),
               parallel_workers=3)
    result = download_files(cfg, log=lambda *a: None)

    assert len(ftp_world.connections) == 3
    all_cwd_calls = [d for conn in ftp_world.connections for d in conn.cwd_calls]
    assert sorted(all_cwd_calls) == sorted([f"{REMOTE_DIR}/2026/07", f"{REMOTE_DIR}/2026/08"])
    assert len(result["downloaded"]) == 48


def test_pool_progress_counter_no_duplicates_or_gaps(ftp_world, patch_ftp, tmp_path):
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    _fill_day(ftp_world, datetime.date(2026, 8, 1))
    patch_ftp(ftp_world)

    seen = []
    lock = threading.Lock()

    def progress(done, total, status, filename):
        with lock:
            seen.append(done)
        assert total == 48

    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path),
               parallel_workers=3)
    download_files(cfg, log=lambda *a: None, progress=progress)

    assert sorted(seen) == list(range(1, 49))   # every "done" value 1..48 shows up exactly once


def test_pool_one_connect_failure_does_not_crash_others(ftp_world, patch_ftp, tmp_path):
    """1 of 2 workers permanently fails to connect (non-retryable): the run
    doesn't raise, and the surviving worker drains the WHOLE shared queue
    (both clusters), so every hour still ends up accounted for."""
    _fill_day(ftp_world, datetime.date(2026, 7, 31))
    _fill_day(ftp_world, datetime.date(2026, 8, 1))
    patch_ftp(ftp_world)
    ftp_world.login_failures = [error_perm("530 forced failure for test")]

    cfg = _cfg(datetime.datetime(2026, 7, 31), datetime.datetime(2026, 8, 1), str(tmp_path),
               parallel_workers=2)
    result = download_files(cfg, log=lambda *a: None)

    assert len(result["downloaded"]) == 48
    assert result["missing"] == []


def test_download_files_raises_when_no_worker_connects(ftp_world, patch_ftp, tmp_path):
    patch_ftp(ftp_world)
    ftp_world.login_failures = [error_perm("530 bad credentials")]
    cfg = _cfg(datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10), str(tmp_path))

    with pytest.raises(error_perm):
        download_files(cfg, log=lambda *a: None)
