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

from pipeline.forecast import build_hourly_table, load_records_csv
from pipeline.obs import build_scalar_history
from pipeline.match_score import FIELD_ORDER, export_forecast_score, join_forecast_obs, score_history
from utils.filename_utils import quantrac_filename_at

# hour 1 -> sub_of_hour() == "dem" (see test_sub_of_hour_covers_every_buổi).
# Values below are the exact True-case pairs hand-verified in
# tests/test_scorer.py, reused here so score_history()'s dispatch is
# checked against an already-trusted forecast/obs pair.
_ALL_TRUE_FORECAST = {
    "hour": 1, "buoi": "dem", "tong_luong_may": 2, "do_cao_man_may": 1, "hien_tuong": "N_0",
    "huong_gio": 0, "toc_do_gio": 2, "tam_nhin": 1,
}
_ALL_TRUE_OBS = {
    "hour": 1, "buoi": "dem", "tong_luong_may": 5, "do_cao_man_may": 50, "hien_tuong": "N_0",
    "huong_gio": 15, "toc_do_gio": 5, "tam_nhin": 0.5,
}
_ALL_NONE_ROW = {
    "hour": 1, "buoi": None, "tong_luong_may": None, "do_cao_man_may": None, "hien_tuong": None,
    "huong_gio": None, "toc_do_gio": None, "tam_nhin": None,
}


def test_score_history_dispatches_each_field_correctly():
    joined = [{"hour": 1, "forecast": _ALL_TRUE_FORECAST, "obs": _ALL_TRUE_OBS}]
    scores = {r["field_name"]: r["score"] for r in score_history(joined)}

    assert scores == {field: True for field in FIELD_ORDER}


def test_score_history_missing_data_scores_none_not_false():
    joined = [{"hour": 1, "forecast": _ALL_NONE_ROW, "obs": _ALL_NONE_ROW}]
    scores = {r["field_name"]: r["score"] for r in score_history(joined)}

    assert scores == {field: None for field in FIELD_ORDER}


def test_score_history_row_shape_and_order():
    joined = [{"hour": 1, "forecast": _ALL_TRUE_FORECAST, "obs": _ALL_TRUE_OBS}]
    rows = score_history(joined)

    assert len(rows) == len(FIELD_ORDER)
    assert [r["field_name"] for r in rows] == list(FIELD_ORDER)
    for r in rows:
        assert set(r.keys()) == {"hour", "field_name", "score"}
        assert r["hour"] == 1


def test_score_history_hien_tuong_reads_buoi_independently_from_each_side():
    """score_history() truyền NGUYÊN forecast_row/obs_row (không tách tay)
    tới score_hien_tuong() - "buoi" mỗi bên đọc từ chính dict của bên đó,
    không bị ép trùng nhau. Dựng forecast_row["buoi"]="chieu" khác hẳn
    obs_row["buoi"]="dem" (mega vẫn khớp "N_0") - phải ra False vì buổi
    lệch quá tolerance, chứng minh dispatch không âm thầm suy lại buổi từ
    "hour" (nếu suy lại từ "hour" dùng chung, 2 buổi sẽ luôn trùng nhau)."""
    forecast_row = dict(_ALL_TRUE_FORECAST, buoi="chieu")
    obs_row = dict(_ALL_TRUE_OBS, buoi="dem")
    joined = [{"hour": 1, "forecast": forecast_row, "obs": obs_row}]

    rows = {r["field_name"]: r["score"] for r in score_history(joined)}
    assert rows["hien_tuong"] is False


def test_score_history_multiple_hours_processed_in_order():
    joined = [
        {"hour": 1, "forecast": _ALL_TRUE_FORECAST, "obs": _ALL_TRUE_OBS},
        {"hour": 2, "forecast": _ALL_NONE_ROW, "obs": _ALL_NONE_ROW},
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
    forecast_rows = build_hourly_table(load_records_csv("tests/fixtures/forecast_sample.csv"))
    scalar_history = build_scalar_history(full_day_dir)["2026-08-10"]

    scores = score_history(join_forecast_obs(forecast_rows, scalar_history))

    assert len(scores) == 24 * len(FIELD_ORDER)
    for r in scores:
        assert 0 <= r["hour"] <= 23
        assert r["field_name"] in FIELD_ORDER
        assert r["score"] in (True, False, None)


# =============================================================================
# export_forecast_score
# =============================================================================

def _read_csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_export_forecast_score_full_day_writes_one_csv_with_24_rows(tmp_path, full_day_qt_files):
    forecast_records = load_records_csv("tests/fixtures/forecast_sample.csv")

    exported = export_forecast_score(full_day_qt_files, forecast_records, str(tmp_path))

    assert list(exported.keys()) == ["2026-08-10"]
    assert exported["2026-08-10"]["records"] == 24
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])
    assert [int(r["hour"]) for r in rows] == list(range(24))
    expected_cols = {"date", "hour", "buoi", "station"} | \
        {f"forecast_{f}" for f in FIELD_ORDER} | \
        {f"obs_{f}" for f in FIELD_ORDER} | \
        {f"score_{f}" for f in FIELD_ORDER}
    assert set(rows[0].keys()) == expected_cols


def test_export_forecast_score_station_populated_on_real_data(tmp_path, full_day_qt_files):
    """Hour 0's representative station is Yên Bái - same fixture record
    test_build_obs_real_fixture_yenbai (tests/test_pipeline_obs.py) hand-verifies."""
    forecast_records = load_records_csv("tests/fixtures/forecast_sample.csv")

    exported = export_forecast_score(full_day_qt_files, forecast_records, str(tmp_path))
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])

    assert rows[0]["station"] == "Yên Bái"
    assert all(r["station"] for r in rows)   # every hour has a file in this fixture


def test_export_forecast_score_missing_obs_hour_scores_none(tmp_path, full_day_dir):
    """Only 2/24 obs files present - the other 22 hours must still produce a
    row (not be dropped), with obs/station blank and every field's score
    blank (CSV empty string == None)."""
    kept_hours = [0, 12]
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    for hour in kept_hours:
        name = quantrac_filename_at(datetime.datetime(2026, 8, 10, hour))
        shutil.copy(os.path.join(full_day_dir, name), dl_dir / name)
    local_files = [str(dl_dir / quantrac_filename_at(datetime.datetime(2026, 8, 10, h)))
                   for h in kept_hours]
    forecast_records = load_records_csv("tests/fixtures/forecast_sample.csv")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    exported = export_forecast_score(local_files, forecast_records, str(out_dir))
    rows = {int(r["hour"]): r for r in _read_csv_rows(exported["2026-08-10"]["csv"])}

    assert len(rows) == 24
    for hour in range(24):
        r = rows[hour]
        if hour in kept_hours:
            assert r["station"]
        else:
            assert r["station"] == ""
            assert r["obs_tong_luong_may"] == ""
            assert all(r[f"score_{f}"] == "" for f in FIELD_ORDER)


def test_export_forecast_score_no_forecast_records_still_24_rows(tmp_path, full_day_qt_files):
    exported = export_forecast_score(full_day_qt_files, [], str(tmp_path))
    rows = _read_csv_rows(exported["2026-08-10"]["csv"])

    assert [int(r["hour"]) for r in rows] == list(range(24))
    for r in rows:
        assert r["forecast_tong_luong_may"] == ""
        assert all(r[f"score_{f}"] == "" for f in FIELD_ORDER)


def test_export_forecast_score_empty_local_files_returns_empty_dict(tmp_path):
    forecast_records = load_records_csv("tests/fixtures/forecast_sample.csv")

    exported = export_forecast_score([], forecast_records, str(tmp_path))

    assert exported == {}
    assert os.listdir(tmp_path) == []


def test_export_forecast_score_multi_date_writes_one_csv_per_date(tmp_path, qt_00, qt_other_day):
    """qt_00 is 2026-08-10 hour 0, qt_other_day is 2026-08-11 hour 0 - two
    distinct dates, 1 CSV each, 24 rows each, no hour collision between them."""
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    shutil.copy(qt_00, dl_dir / os.path.basename(qt_00))
    shutil.copy(qt_other_day, dl_dir / os.path.basename(qt_other_day))
    local_files = [str(dl_dir / os.path.basename(qt_00)), str(dl_dir / os.path.basename(qt_other_day))]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    exported = export_forecast_score(local_files, [], str(out_dir))

    assert set(exported.keys()) == {"2026-08-10", "2026-08-11"}
    for date_str, info in exported.items():
        assert info["records"] == 24
        rows = _read_csv_rows(info["csv"])
        assert [int(r["hour"]) for r in rows] == list(range(24))
        assert all(r["date"] == date_str for r in rows)
