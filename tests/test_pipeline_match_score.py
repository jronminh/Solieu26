"""
test_pipeline_match_score.py
====================
Unit tests for pipeline/match_score.py's score_history: correct dispatch of
each field to scoring/scorer.py's score_<field>() (values reused from
tests/test_scorer.py's hand-verified cases - each score_<field>() now
takes the WHOLE forecast_row/obs dict, not a scalar), and output row
shape/order.

End-to-end smoke test at the bottom runs join_forecast_obs() +
score_history() together on the real full-day fixture (already covered
individually by tests/test_time_sync.py and tests/test_scorer.py).
"""

import csv
import datetime
import os
import shutil

from pipeline.forecast import build_hourly_table, export_forecast_table, load_records_csv
from pipeline.obs import build_scalar_history
from pipeline.match_score import FIELD_ORDER, export_forecast_score, join_forecast_obs, score_history
from utils.filename_utils import quantrac_filename_at

FORECAST_CSV = "tests/fixtures/forecast_sample.csv"

# hour 1 -> sub_of_hour() == "dem" (see test_sub_of_hour_covers_every_buổi).
# Values below are the exact True-case pairs hand-verified in
# tests/test_scorer.py, reused here so score_history()'s dispatch is
# checked against an already-trusted forecast/obs pair.
_ALL_TRUE_FORECAST = {
    "station_code": "k31", "hour": 1, "buoi": "dem", "tong_luong_may": 2, "do_cao_man_may": 1,
    "hien_tuong": "khong", "huong_gio": 0, "toc_do_gio": 2, "tam_nhin": 1,
}
_ALL_TRUE_OBS = {
    "station_code": "k31", "hour": 1, "buoi": "dem", "tong_luong_may": 5, "do_cao_man_may": 50,
    "hien_tuong": "khong", "huong_gio": 15, "toc_do_gio": 5, "tam_nhin": 0.5,
}
_ALL_NONE_ROW = {
    "station_code": "k31", "hour": 1, "buoi": None, "tong_luong_may": None, "do_cao_man_may": None,
    "hien_tuong": None, "huong_gio": None, "toc_do_gio": None, "tam_nhin": None,
}


def test_score_history_dispatches_each_field_correctly():
    joined = [{"station_code": "k31", "hour": 1, "forecast": _ALL_TRUE_FORECAST, "obs": _ALL_TRUE_OBS}]
    scores = {r["field_name"]: r["score"] for r in score_history(joined)}

    assert scores == {field: True for field in FIELD_ORDER}


def test_score_history_missing_data_scores_none_not_false():
    joined = [{"station_code": "k31", "hour": 1, "forecast": _ALL_NONE_ROW, "obs": _ALL_NONE_ROW}]
    scores = {r["field_name"]: r["score"] for r in score_history(joined)}

    assert scores == {field: None for field in FIELD_ORDER}


def test_score_history_row_shape_and_order():
    joined = [{"station_code": "k31", "hour": 1, "forecast": _ALL_TRUE_FORECAST, "obs": _ALL_TRUE_OBS}]
    rows = score_history(joined)

    assert len(rows) == len(FIELD_ORDER)
    assert [r["field_name"] for r in rows] == list(FIELD_ORDER)
    for r in rows:
        assert set(r.keys()) == {"station_code", "hour", "field_name", "score"}
        assert r["hour"] == 1
        assert r["station_code"] == "k31"


def test_score_history_hien_tuong_reads_buoi_independently_from_each_side():
    """score_history() truyền NGUYÊN forecast_row/obs_row (không tách tay)
    tới score_hien_tuong() - "buoi" mỗi bên đọc từ chính dict của bên đó,
    không bị ép trùng nhau. Dựng forecast_row["buoi"]="chieu" khác hẳn
    obs_row["buoi"]="dem" (mega vẫn khớp "khong") - phải ra False vì buổi
    lệch quá tolerance, chứng minh dispatch không âm thầm suy lại buổi từ
    "hour" (nếu suy lại từ "hour" dùng chung, 2 buổi sẽ luôn trùng nhau)."""
    forecast_row = dict(_ALL_TRUE_FORECAST, buoi="chieu")
    obs_row = dict(_ALL_TRUE_OBS, buoi="dem")
    joined = [{"station_code": "k31", "hour": 1, "forecast": forecast_row, "obs": obs_row}]

    rows = {r["field_name"]: r["score"] for r in score_history(joined)}
    assert rows["hien_tuong"] is False


def test_score_history_multiple_hours_processed_in_order():
    joined = [
        {"station_code": "k31", "hour": 1, "forecast": _ALL_TRUE_FORECAST, "obs": _ALL_TRUE_OBS},
        {"station_code": "k31", "hour": 2, "forecast": _ALL_NONE_ROW, "obs": _ALL_NONE_ROW},
    ]
    rows = score_history(joined)

    assert len(rows) == 2 * len(FIELD_ORDER)
    assert [r["hour"] for r in rows] == [1] * 6 + [2] * 6


def test_score_history_empty_joined_rows_returns_empty_list():
    assert score_history([]) == []


# =============================================================================
# smoke test - join_forecast_obs() + score_history() on real full-day data
# =============================================================================

def test_join_and_score_full_day_smoke(full_day_dir):
    """forecast_sample.csv chỉ dự báo cho k31 - join_forecast_obs() do OBS
    dẫn dắt nên vẫn ra 1 dòng/trạm quan trắc (kể cả trạm không có dự báo,
    ghép với dự báo rỗng -> điểm toàn bỏ cặp)."""
    forecast_rows = build_hourly_table(load_records_csv("tests/fixtures/forecast_sample.csv"))
    scalar_history = build_scalar_history(full_day_dir)["2026-08-10"]
    num_stations = len({r["station_code"] for r in scalar_history})

    joined = join_forecast_obs(forecast_rows, scalar_history)
    scores = score_history(joined)

    assert len(joined) == len(scalar_history) == num_stations * 24
    assert len(scores) == num_stations * 24 * len(FIELD_ORDER)
    for r in scores:
        assert 0 <= r["hour"] <= 23
        assert r["field_name"] in FIELD_ORDER
        assert r["score"] in (True, False, None)

    other_station = next(r["station_code"] for r in scalar_history if r["station_code"] != "k31")
    other_scores = [r["score"] for r in scores if r["station_code"] == other_station]
    assert all(s is None for s in other_scores)   # không dự báo -> bỏ cặp toàn bộ


# =============================================================================
# export_forecast_score
# =============================================================================

def _read_csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_export_forecast_score_full_day_writes_one_csv_with_rows_per_station(tmp_path, full_day_qt_files, full_day_dir):
    num_stations = len({r["station_code"] for r in build_scalar_history(full_day_dir)["2026-08-10"]})

    exported = export_forecast_score(full_day_qt_files, FORECAST_CSV, str(tmp_path))

    assert list(exported.keys()) == ["2026-08-10"]
    assert exported["2026-08-10"]["records"] == num_stations * 24
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])
    by_station = {}
    for r in rows:
        by_station.setdefault(r["station_code"], []).append(r)
    assert len(by_station) == num_stations
    for station_code, srows in by_station.items():
        assert [int(r["hour"]) for r in srows] == list(range(24))
    expected_cols = {"date", "station_code", "hour", "buoi"} | \
        {f"forecast_{f}" for f in FIELD_ORDER} | \
        {f"obs_{f}" for f in FIELD_ORDER} | \
        {f"score_{f}" for f in FIELD_ORDER}
    assert set(rows[0].keys()) == expected_cols


def test_export_forecast_score_writes_score_prefixed_csv_filename(tmp_path, full_day_qt_files):
    """Output filename uses the score_ prefix, not forecast_ - the latter is
    reserved for pipeline/forecast.py::export_forecast_table()'s raw-records
    archive, to avoid the two exports colliding on the same file name."""
    exported = export_forecast_score(full_day_qt_files, FORECAST_CSV, str(tmp_path))

    assert os.path.basename(exported["2026-08-10"]["csv"]) == "score_20260810.csv"


def test_export_forecast_score_station_code_populated_on_real_data(tmp_path, full_day_qt_files):
    """Yên Bái (k31), giờ 0 - same fixture record
    test_build_obs_real_fixture_yenbai (tests/test_pipeline_obs.py) hand-verifies."""
    exported = export_forecast_score(full_day_qt_files, FORECAST_CSV, str(tmp_path))
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])

    yenbai_row = next(r for r in rows if r["station_code"] == "k31" and r["hour"] == "0")
    assert yenbai_row["station_code"] == "k31"
    assert all(r["station_code"] for r in rows)   # mọi dòng đều biết trạm, kể cả trạm không có dự báo


def test_export_forecast_score_missing_obs_hour_scores_none(tmp_path, full_day_dir):
    """Only 2/24 obs files present - the other 22 hours must still produce a
    row per station (not be dropped), with obs blank and every field's
    score blank (CSV empty string == None) - station_code stays populated
    (đã biết trạm nào từ 2 file có mặt, chỉ thiếu dữ liệu giờ đó)."""
    kept_hours = [0, 12]
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    for hour in kept_hours:
        name = quantrac_filename_at(datetime.datetime(2026, 8, 10, hour))
        shutil.copy(os.path.join(full_day_dir, name), dl_dir / name)
    local_files = [str(dl_dir / quantrac_filename_at(datetime.datetime(2026, 8, 10, h)))
                   for h in kept_hours]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    exported = export_forecast_score(local_files, FORECAST_CSV, str(out_dir))
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])
    by_station = {}
    for r in rows:
        by_station.setdefault(r["station_code"], []).append(r)

    assert by_station
    for station_code, srows in by_station.items():
        by_hour = {int(r["hour"]): r for r in srows}
        assert list(by_hour) == list(range(24))
        for hour in range(24):
            r = by_hour[hour]
            assert r["station_code"] == station_code
            if hour not in kept_hours:
                assert r["obs_tong_luong_may"] == ""
                assert all(r[f"score_{f}"] == "" for f in FIELD_ORDER)


def test_export_forecast_score_no_forecast_csv_path_still_has_rows(tmp_path, full_day_qt_files, full_day_dir):
    num_stations = len({r["station_code"] for r in build_scalar_history(full_day_dir)["2026-08-10"]})

    exported = export_forecast_score(full_day_qt_files, None, str(tmp_path))
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])

    assert len(rows) == num_stations * 24
    for r in rows:
        assert r["forecast_tong_luong_may"] == ""
        assert all(r[f"score_{f}"] == "" for f in FIELD_ORDER)


def test_export_forecast_score_empty_local_files_returns_empty_dict(tmp_path):
    exported = export_forecast_score([], FORECAST_CSV, str(tmp_path))

    assert exported == {}
    assert os.listdir(tmp_path) == []


def test_export_forecast_score_multi_date_writes_one_csv_per_date(tmp_path, qt_00, qt_other_day):
    """qt_00 is 2026-08-10 hour 0, qt_other_day is 2026-08-11 hour 0 - two
    distinct dates, 1 CSV each, no hour/date collision between them."""
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    shutil.copy(qt_00, dl_dir / os.path.basename(qt_00))
    shutil.copy(qt_other_day, dl_dir / os.path.basename(qt_other_day))
    local_files = [str(dl_dir / os.path.basename(qt_00)), str(dl_dir / os.path.basename(qt_other_day))]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    history_by_date = build_scalar_history(str(dl_dir))
    exported = export_forecast_score(local_files, None, str(out_dir))

    assert set(exported.keys()) == {"2026-08-10", "2026-08-11"}
    for date_str, info in exported.items():
        num_stations = len({r["station_code"] for r in history_by_date[date_str]})
        assert info["records"] == num_stations * 24
        rows = _read_csv_rows(info["csv"])
        assert all(r["date"] == date_str for r in rows)


def test_export_forecast_score_scoped_to_explicit_files_does_not_touch_other_dates_csv(
        tmp_path, qt_00, qt_other_day):
    """Thư mục chứa file của 2 ngày (mô phỏng thư mục tải tạm dùng chung
    giữa các lượt chạy, xem TEMP_DL_DIR ở utils/config_utils.py) - chỉ
    truyền path của 1 ngày phải chỉ ghi CSV của đúng ngày đó, KHÔNG được lấy
    nhầm/ghi đè CSV của ngày kia dù nó nằm chung thư mục (bug đã sửa: trước
    đây export_forecast_score() chỉ dùng local_files[0] để suy ra thư mục
    rồi quét cả thư mục, kéo theo mọi ngày khác có mặt ở đó)."""
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    shutil.copy(qt_00, dl_dir / os.path.basename(qt_00))
    shutil.copy(qt_other_day, dl_dir / os.path.basename(qt_other_day))

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    exported = export_forecast_score(
        [str(dl_dir / os.path.basename(qt_00))], FORECAST_CSV, str(out_dir))

    assert set(exported.keys()) == {"2026-08-10"}
    assert not os.path.exists(out_dir / "score_20260811.csv")


def test_export_forecast_score_reads_archived_forecast_table(tmp_path, full_day_qt_files):
    """forecast_csv_path also accepts a file written by
    pipeline/forecast.py::export_forecast_table() (the archive of a
    forecaster's raw bucket selections) - same shape as a hand-authored
    records CSV, so it must produce the exact same score CSV."""
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    archived = export_forecast_table(
        load_records_csv(FORECAST_CSV), "2026-08-10", str(archive_dir))

    direct_dir = tmp_path / "direct"
    direct_dir.mkdir()
    archive_dir_out = tmp_path / "from_archive"
    archive_dir_out.mkdir()
    direct = export_forecast_score(full_day_qt_files, FORECAST_CSV, str(direct_dir))
    from_archive = export_forecast_score(full_day_qt_files, archived["csv"], str(archive_dir_out))

    assert _read_csv_rows(direct["2026-08-10"]["csv"]) == _read_csv_rows(from_archive["2026-08-10"]["csv"])
