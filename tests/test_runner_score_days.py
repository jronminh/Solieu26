"""
test_runner_score_days.py
====================
Runner._dates_in_range/_score_days (runner.py): pure logic tests, no
app/thread/FTP needed - _score_days() only touches the filesystem
(output_dir) and pipeline.match_score, never self.app (see _FakeApp in
tests/test_runner_catchup.py for the pattern this mirrors when Runner does
need an app).
"""

import datetime
import os
import shutil

from runner import Runner

FORECAST_CSV = "tests/fixtures/forecast_sample.csv"


def _no_log(level, msg):
    pass


# =============================================================================
# _dates_in_range
# =============================================================================

def test_dates_in_range_single_day_returns_one_date():
    runner = Runner(app=None)
    start = datetime.datetime(2026, 8, 10, 3)
    end = datetime.datetime(2026, 8, 10, 20)
    assert runner._dates_in_range(start, end) == ["2026-08-10"]


def test_dates_in_range_multi_day_inclusive():
    runner = Runner(app=None)
    start = datetime.datetime(2026, 8, 10)
    end = datetime.datetime(2026, 8, 12)
    assert runner._dates_in_range(start, end) == ["2026-08-10", "2026-08-11", "2026-08-12"]


# =============================================================================
# _score_days
# =============================================================================

def test_score_days_skips_dates_without_forecast_csv(tmp_path, full_day_qt_files):
    runner = Runner(app=None)
    exported = runner._score_days(
        full_day_qt_files, datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 10),
        str(tmp_path), log=_no_log)

    assert exported == {}


def test_score_days_only_scores_dates_with_existing_forecast(tmp_path, qt_00, qt_other_day):
    """qt_00 (2026-08-10) + qt_other_day (2026-08-11) đều nằm trong local_files
    (mô phỏng thư mục tải tạm dùng chung), nhưng chỉ có forecast cho 08-10 -
    end-to-end đúng kịch bản lỗi gốc: date_key giờ đến từ khoảng ngày
    (start_date/end_date), không phải history_files.keys(), và
    export_forecast_score() không được lấy nhầm/ghi score cho 08-11."""
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    shutil.copy(qt_00, dl_dir / os.path.basename(qt_00))
    shutil.copy(qt_other_day, dl_dir / os.path.basename(qt_other_day))
    local_files = [str(dl_dir / os.path.basename(qt_00)), str(dl_dir / os.path.basename(qt_other_day))]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    shutil.copy(FORECAST_CSV, out_dir / "forecast_20260810.csv")

    runner = Runner(app=None)
    exported = runner._score_days(
        local_files, datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 11),
        str(out_dir), log=_no_log)

    assert set(exported.keys()) == {"2026-08-10"}
    assert not os.path.exists(out_dir / "score_20260811.csv")


def test_score_days_forecast_without_matching_files_is_skipped(tmp_path, qt_00):
    """Forecast tồn tại cho 1 ngày mà local_files không có file nào của ngày
    đó (vd server không có dữ liệu hôm đó) - bỏ qua an toàn, không lỗi."""
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    shutil.copy(qt_00, dl_dir / os.path.basename(qt_00))
    local_files = [str(dl_dir / os.path.basename(qt_00))]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    shutil.copy(FORECAST_CSV, out_dir / "forecast_20260811.csv")

    runner = Runner(app=None)
    exported = runner._score_days(
        local_files, datetime.datetime(2026, 8, 10), datetime.datetime(2026, 8, 11),
        str(out_dir), log=_no_log)

    assert exported == {}
