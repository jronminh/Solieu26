"""
test_runner_catchup.py
====================
Mốc catch-up sau downtime (runner.py): pure logic tests for
_pending_catchup_range/_contiguous_advance/_advance_catchup_mark, plus one
integration test (FakeFTP + a real worker thread) confirming the mark is
persisted correctly after a fetch cycle with a gap in the middle.

Runner reaches into an App instance for widgets/collaborators it never
actually needs for this logic, so _FakeApp below stubs just enough of that
surface (see each method's docstring in runner.py for what it touches).
"""

import datetime
from unittest.mock import MagicMock

import pytest

from utils import config_utils as config
from utils.filename_utils import quantrac_filename_at
from runner import Runner

REMOTE_DIR = "/Quantrac"


@pytest.fixture(autouse=True)
def _reset_catchup_mark():
    original = config.CONFIG.get("catchup_mark")
    yield
    if original is None:
        config.CONFIG.pop("catchup_mark", None)
    else:
        config.CONFIG["catchup_mark"] = original


class _FakeApp:
    """Minimal stand-in for main.App: only what Runner touches during
    _start_worker -> _work -> _poll -> _on_fetch_done/_on_export_*."""

    def __init__(self, cfg_path):
        self.cfg_path = cfg_path
        self.logs = []
        self.status = MagicMock()
        self.auto_query = MagicMock()
        self.history_viewer = MagicMock()
        self.root = MagicMock()
        self.root.after = lambda ms, fn: None

    def _log(self, level, msg):
        self.logs.append((level, msg))

    def _divider(self):
        pass

    def _reset_download_queue(self, start, end):
        pass

    def _set_download_progress(self, *args, **kwargs):
        pass

    def refresh_range_panel_state(self):
        pass

    def _refresh_info_panel(self):
        pass


def _fill_range(world, start: datetime.datetime, end: datetime.datetime, skip=()):
    """Register a file for every hour in [start, end] except those in `skip`
    (a set of datetimes) — for carving a gap in the middle of a range."""
    from pipeline.fetch import expected_hours
    for ts in expected_hours(start, end):
        if ts in skip:
            continue
        path = f"{REMOTE_DIR}/{ts:%Y}/{ts:%m}"
        world.add_file(path, quantrac_filename_at(ts), b"data")


# =============================================================================
# _pending_catchup_range: pure logic, no app/thread needed
# =============================================================================

def test_pending_catchup_range_no_mark_returns_none():
    config.CONFIG["catchup_mark"] = ""
    runner = Runner(app=None)
    assert runner._pending_catchup_range(datetime.datetime(2026, 8, 10, 12)) is None


def test_pending_catchup_range_invalid_mark_returns_none():
    config.CONFIG["catchup_mark"] = "not-a-date"
    runner = Runner(app=None)
    assert runner._pending_catchup_range(datetime.datetime(2026, 8, 10, 12)) is None


def test_pending_catchup_range_gap_under_hour_returns_none():
    config.CONFIG["catchup_mark"] = "2026-08-10 11:30:00"
    runner = Runner(app=None)
    now = datetime.datetime(2026, 8, 10, 12, 0)   # mark+1h is 12:30, later than now
    assert runner._pending_catchup_range(now) is None


def test_pending_catchup_range_returns_gap_from_mark_plus_1h():
    config.CONFIG["catchup_mark"] = "2026-08-10 10:00:00"
    runner = Runner(app=None)
    now = datetime.datetime(2026, 8, 10, 15, 0)
    start, end = runner._pending_catchup_range(now)
    assert start == datetime.datetime(2026, 8, 10, 11, 0)
    assert end == now


# =============================================================================
# _contiguous_advance: pure logic
# =============================================================================

def test_contiguous_advance_no_missing_reaches_end():
    # expected_hours() widens a same-day range to the full 00-23, regardless
    # of start/end's hour parts (existing behavior, not something this phase
    # changes) — end at hour 23 keeps the expectation unambiguous.
    runner = Runner(app=None)
    start = datetime.datetime(2026, 8, 10, 0)
    end = datetime.datetime(2026, 8, 10, 23)
    mark = runner._contiguous_advance(start, end, missing_filenames=[])
    assert mark == end


def test_contiguous_advance_stops_before_first_missing():
    runner = Runner(app=None)
    start = datetime.datetime(2026, 8, 10, 0)
    end = datetime.datetime(2026, 8, 10, 5)
    missing = [quantrac_filename_at(datetime.datetime(2026, 8, 10, 3))]
    mark = runner._contiguous_advance(start, end, missing)
    assert mark == datetime.datetime(2026, 8, 10, 2)   # hour right before the gap


def test_contiguous_advance_first_hour_missing_returns_before_start():
    runner = Runner(app=None)
    start = datetime.datetime(2026, 8, 10, 0)
    end = datetime.datetime(2026, 8, 10, 5)
    missing = [quantrac_filename_at(start)]
    mark = runner._contiguous_advance(start, end, missing)
    assert mark < start


# =============================================================================
# _advance_catchup_mark: writes config.ini + CONFIG, never regresses
# =============================================================================

def test_advance_catchup_mark_writes_new_mark(tmp_path):
    ini_path = str(tmp_path / "config.ini")
    app = _FakeApp(cfg_path=ini_path)
    runner = Runner(app=app)
    config.CONFIG["catchup_mark"] = ""

    start = datetime.datetime(2026, 8, 10, 0)
    end = datetime.datetime(2026, 8, 10, 23)
    runner._advance_catchup_mark(start, end, missing_filenames=[])

    assert config.CONFIG["catchup_mark"] == "2026-08-10 23:00:00"
    with open(ini_path, encoding="utf-8") as f:
        assert "catchup_mark = 2026-08-10 23:00:00" in f.read()


def test_advance_catchup_mark_does_not_regress(tmp_path):
    ini_path = str(tmp_path / "config.ini")
    app = _FakeApp(cfg_path=ini_path)
    runner = Runner(app=app)
    config.CONFIG["catchup_mark"] = "2026-08-11 10:00:00"

    # A cycle for an earlier day (e.g. a redundant re-run) confirms only up to
    # 2026-08-10 23:00 — well before the mark already on record.
    start = datetime.datetime(2026, 8, 10, 0)
    end = datetime.datetime(2026, 8, 10, 23)
    runner._advance_catchup_mark(start, end, missing_filenames=[])

    assert config.CONFIG["catchup_mark"] == "2026-08-11 10:00:00"   # unchanged


# =============================================================================
# _run_catchup_then_normal: control flow (no thread needed when no gap pending)
# =============================================================================

def test_run_catchup_then_normal_falls_back_to_on_run_when_no_gap():
    config.CONFIG["catchup_mark"] = ""
    app = _FakeApp(cfg_path="unused")
    runner = Runner(app=app)
    called = []
    runner._on_run = lambda: called.append(True)

    runner._run_catchup_then_normal()

    assert called == [True]
    assert runner._on_run_done is None


# =============================================================================
# Integration: a fetch cycle with a gap in the middle advances the mark to
# right before the gap, not past it.
# =============================================================================

def test_fetch_cycle_advances_mark_stopping_before_gap(ftp_world, patch_ftp, tmp_path):
    patch_ftp(ftp_world)

    start = datetime.datetime(2026, 8, 10, 0)
    end = datetime.datetime(2026, 8, 10, 5)
    gap_hour = datetime.datetime(2026, 8, 10, 3)
    _fill_range(ftp_world, start, end, skip={gap_hour})

    ini_path = str(tmp_path / "config.ini")
    app = _FakeApp(cfg_path=ini_path)
    runner = Runner(app=app)
    config.CONFIG["catchup_mark"] = ""

    cfg = {
        "ftp_host": "host", "ftp_user": "u", "ftp_pass": "p",
        "ftp_timeout": 5, "retry_temp": 0, "retry_wait": 0,
        "stability_check": False,   # keep the test instant; poll-size-hai-lần tested separately
        "remote_dir": REMOTE_DIR, "local_dir": str(tmp_path / "dl"),
        "output_dir": str(tmp_path / "out"),
        "start_date": start, "end_date": end,
    }
    assert runner._start_worker(cfg) is True
    runner.worker.join(timeout=5)
    assert not runner.worker.is_alive()
    runner._poll()   # drain every event the worker thread queued while running

    assert config.CONFIG["catchup_mark"] == "2026-08-10 02:00:00"   # right before the gap at 03:00
