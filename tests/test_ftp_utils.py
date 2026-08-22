"""
test_ftp_utils.py
====================
Baseline tests for utils/ftp_utils.py (download_one, fetch_and_bucket)
against today's behavior, using tests/fake_ftp.py instead of a live server.
Phase 2/4 (SIZE-check, poll-size-hai-lần) extend download_one's retry
branches; these tests pin down the branches that already exist so later
phases can be checked against them for regressions.
"""

import os

import pytest

from tests.fake_ftp import FakeFTP, FakeFTPWorld
from utils.ftp_utils import download_one, fetch_and_bucket

REMOTE_DIR = "/Quantrac/2026/08"


def _ftp_in(world, path=REMOTE_DIR):
    ftp = FakeFTP(world=world)
    ftp.cwd(path)
    return ftp


# =============================================================================
# download_one
# =============================================================================

def test_download_one_success_writes_file_and_no_leftover_part(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"hello world")
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, stability_check=False)

    assert status == 0
    assert os.path.isfile(local_path)
    with open(local_path, "rb") as f:
        assert f.read() == b"hello world"
    assert not os.path.exists(local_path + ".part")


def test_download_one_skips_existing_local_file(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"server version")
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")
    with open(local_path, "wb") as f:
        f.write(b"local version")

    status = download_one(ftp, "Qt26081000.txt", local_path)

    assert status == 1
    with open(local_path, "rb") as f:
        assert f.read() == b"local version"   # untouched, not overwritten


def test_download_one_missing_on_server_no_leftover(ftp_world, tmp_path):
    ftp = _ftp_in(ftp_world)   # no file registered
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path)

    assert status == 2
    assert not os.path.isfile(local_path)
    assert not os.path.exists(local_path + ".part")


def test_download_one_retries_temp_error_then_succeeds(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"ok", retr_fail_count=1)
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, retry_temp=1, retry_wait=0,
                           stability_check=False)

    assert status == 0
    with open(local_path, "rb") as f:
        assert f.read() == b"ok"


def test_download_one_gives_up_after_retries_exhausted(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"ok", retr_fail_count=99)
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, retry_temp=1, retry_wait=0,
                           stability_check=False)

    assert status == 2
    assert not os.path.isfile(local_path)
    assert not os.path.exists(local_path + ".part")


# =============================================================================
# download_one: SIZE-check on finalize (Phase 2)
# =============================================================================

def test_download_one_size_mismatch_gives_up_after_retries(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"hello", size_sequence=[999])
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, retry_temp=1, retry_wait=0,
                           stability_check=False)

    assert status == 2
    assert not os.path.isfile(local_path)
    assert not os.path.exists(local_path + ".part")


def test_download_one_size_mismatch_then_matches_on_retry(ftp_world, tmp_path):
    content = b"hello"
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", content, size_sequence=[999, len(content)])
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, retry_temp=1, retry_wait=0,
                           stability_check=False)

    assert status == 0
    with open(local_path, "rb") as f:
        assert f.read() == content
    assert not os.path.exists(local_path + ".part")


def test_download_one_size_unsupported_still_accepts_file(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"hello", size_fail=True)
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")
    logs = []

    status = download_one(ftp, "Qt26081000.txt", local_path,
                           log=lambda lvl, msg: logs.append((lvl, msg)))

    assert status == 0
    with open(local_path, "rb") as f:
        assert f.read() == b"hello"
    assert logs and logs[0][0] == "WARN"


def test_download_one_size_unsupported_without_log_callback(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"hello", size_fail=True)
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path)   # log=None default

    assert status == 0


# =============================================================================
# download_one: poll-size-hai-lần (Phase 4) — stability_wait=0 below keeps
# these tests instant while still exercising the real 2-call comparison.
# =============================================================================

def test_download_one_stable_size_downloads_on_first_attempt(ftp_world, tmp_path):
    content = b"hello"
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", content)   # size_sequence=None -> always stable
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, stability_check=True, stability_wait=0)

    assert status == 0
    with open(local_path, "rb") as f:
        assert f.read() == content


def test_download_one_unstable_size_retries_then_succeeds(ftp_world, tmp_path):
    content = b"hello"
    # attempt 1's poll: 10 vs 20 (unstable) -> retry; attempt 2's poll: 5 vs 5 (stable) -> download;
    # then _size_ok's post-download SIZE call sees 5 again, matching len(content).
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", content, size_sequence=[10, 20, 5, 5, 5])
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, retry_temp=1, retry_wait=0,
                           stability_check=True, stability_wait=0)

    assert status == 0
    with open(local_path, "rb") as f:
        assert f.read() == content


def test_download_one_unstable_size_gives_up_after_retries(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"hello", size_sequence=[1, 2, 3, 4])
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, retry_temp=1, retry_wait=0,
                           stability_check=True, stability_wait=0)

    assert status == 2
    assert not os.path.isfile(local_path)
    assert not os.path.exists(local_path + ".part")


def test_download_one_stability_check_disabled_skips_extra_size_calls(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"hello")
    ftp = _ftp_in(ftp_world)
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, stability_check=False)

    assert status == 0
    # only _size_ok's single post-download SIZE call; none from the (skipped) stability poll
    assert ftp_world.dirs[REMOTE_DIR]["Qt26081000.txt"]._size_calls == 1


def test_download_one_missing_on_server_no_stability_delay(ftp_world, tmp_path):
    """A genuinely absent file shouldn't wait stability_wait at all: the first
    SIZE call already raises, which _is_stable treats as inconclusive."""
    ftp = _ftp_in(ftp_world)   # no file registered
    local_path = str(tmp_path / "Qt26081000.txt")

    status = download_one(ftp, "Qt26081000.txt", local_path, stability_check=True, stability_wait=0)

    assert status == 2


# =============================================================================
# fetch_and_bucket: classification + log level
# =============================================================================

def test_fetch_and_bucket_downloaded(ftp_world, tmp_path):
    ftp_world.add_file(REMOTE_DIR, "Qt26081000.txt", b"data")
    ftp = _ftp_in(ftp_world)
    buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
    logs = []

    status = fetch_and_bucket(ftp, "Qt26081000.txt", str(tmp_path), 0, 0,
                               lambda lvl, msg: logs.append((lvl, msg)), buckets,
                               stability_check=False)

    assert status == 0
    assert buckets["downloaded"] == ["Qt26081000.txt"]
    assert buckets["files"] == [str(tmp_path / "Qt26081000.txt")]
    assert logs and logs[0][0] == "OK"


def test_fetch_and_bucket_skipped(ftp_world, tmp_path):
    ftp = _ftp_in(ftp_world)
    local_path = tmp_path / "Qt26081000.txt"
    local_path.write_bytes(b"already here")
    buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
    logs = []

    status = fetch_and_bucket(ftp, "Qt26081000.txt", str(tmp_path), 0, 0,
                               lambda lvl, msg: logs.append((lvl, msg)), buckets)

    assert status == 1
    assert buckets["skipped"] == ["Qt26081000.txt"]
    assert logs and logs[0][0] == "SKIP"


def test_fetch_and_bucket_missing(ftp_world, tmp_path):
    ftp = _ftp_in(ftp_world)
    buckets = {"files": [], "downloaded": [], "skipped": [], "missing": []}
    logs = []

    status = fetch_and_bucket(ftp, "Qt26081000.txt", str(tmp_path), 0, 0,
                               lambda lvl, msg: logs.append((lvl, msg)), buckets)

    assert status == 2
    assert buckets["missing"] == ["Qt26081000.txt"]
    assert logs and logs[0][0] == "MISS"
