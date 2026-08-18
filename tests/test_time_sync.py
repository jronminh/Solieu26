"""
test_time_sync.py
====================
Ghép build_hourly_table() (pipeline/forecast.py) với build_scalar_history()
(pipeline/obs.py) qua join_forecast_obs() (pipeline/scoring.py) - cả 3 hàm
đều thao tác trên list "1 dict/giờ, đủ hour+6 field", ghép nhau thuần theo
khoá "hour" (chưa phân biệt trạm).

Dữ liệu: forecast_sample.csv (giả lập, phủ giờ 0-23) ghép với
tests/fixtures/qt_files/full_day_20260810/ (24 file thật, ngày 2026-08-10).
"""

import datetime

import pytest

from pipeline.forecast import build_hourly_table, load_records_csv
from pipeline.obs import build_scalar_history
from pipeline.scoring import join_forecast_obs


def _forecast_rows():
    return build_hourly_table(load_records_csv("tests/fixtures/forecast_sample.csv"))


def test_forecast_and_obs_hour_axes_match_for_full_day(full_day_dir):
    forecast_hours = {r["hour"] for r in _forecast_rows()}

    scalar_history = build_scalar_history(datetime.date(2026, 8, 10), full_day_dir)
    obs_hours = {r["hour"] for r in scalar_history}

    assert forecast_hours == obs_hours == set(range(24))


def test_join_forecast_obs_hour_always_agrees(full_day_dir):
    scalar_history = build_scalar_history(datetime.date(2026, 8, 10), full_day_dir)
    rows = join_forecast_obs(_forecast_rows(), scalar_history)

    assert len(rows) == 24
    for row in rows:
        assert row["forecast"]["hour"] == row["hour"] == row["obs"]["hour"]


def test_join_forecast_obs_row_shape(full_day_dir):
    """Mỗi dòng ghép chỉ có 3 khoá - KHÔNG mang định danh trạm; "forecast"
    và "obs" đều đủ 7 khoá (hour + 6 field) - hai bên CÙNG khoá field nhưng
    khác không gian giá trị (forecast là bucket đã chọn, obs phần lớn là
    số đo thô)."""
    scalar_history = build_scalar_history(datetime.date(2026, 8, 10), full_day_dir)
    row = join_forecast_obs(_forecast_rows(), scalar_history)[0]

    assert set(row.keys()) == {"hour", "forecast", "obs"}
    field_keys = {"hour", "buoi", "tong_luong_may", "do_cao_man_may", "hien_tuong",
                  "huong_gio", "toc_do_gio", "tam_nhin"}
    assert set(row["forecast"].keys()) == field_keys
    assert set(row["obs"].keys()) == field_keys


def test_join_forecast_obs_raises_on_hour_without_forecast_row():
    """1 dòng obs ứng với giờ không có dòng dự báo -> raise ngay, không
    âm thầm bỏ qua cặp thiếu dữ liệu."""
    with pytest.raises(ValueError):
        join_forecast_obs([], [{"hour": 0, "tong_luong_may": None,
                                 "do_cao_man_may": None, "hien_tuong": None,
                                 "huong_gio": None, "toc_do_gio": None,
                                 "tam_nhin": None}])


def test_join_forecast_obs_empty_history_returns_empty_list():
    assert join_forecast_obs(_forecast_rows(), []) == []
