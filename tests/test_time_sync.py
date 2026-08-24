"""
test_time_sync.py
====================
Ghép build_hourly_table() (pipeline/forecast.py) với build_scalar_history()
(pipeline/obs.py) qua join_forecast_obs() (pipeline/match_score.py) - cả 3 hàm
đều thao tác trên list "(station_code × 24 giờ)/ngày, đủ station_code+hour+
buoi+6 field", ghép nhau theo khoá (station_code, hour), do OBS dẫn dắt
(mọi trạm quan trắc thực sự báo cáo đều có dòng, kể cả trạm chưa ai dự báo).

Dữ liệu: forecast_sample.csv (giả lập, chỉ dự báo cho trạm k31, phủ giờ
0-23) ghép với tests/fixtures/qt_files/full_day_20260810/ (24 file thật,
ngày 2026-08-10, nhiều trạm/giờ).
"""

import pytest

from pipeline.forecast import build_hourly_table, load_records_csv
from pipeline.obs import build_scalar_history
from pipeline.match_score import join_forecast_obs


def _forecast_rows():
    return build_hourly_table(load_records_csv("tests/fixtures/forecast_sample.csv"))


def test_forecast_and_obs_hour_axes_match_for_full_day(full_day_dir):
    forecast_hours = {r["hour"] for r in _forecast_rows()}

    scalar_history = build_scalar_history(full_day_dir)["2026-08-10"]
    obs_hours = {r["hour"] for r in scalar_history}

    assert forecast_hours == obs_hours == set(range(24))


def test_join_forecast_obs_one_row_per_obs_row(full_day_dir):
    """join_forecast_obs() do OBS dẫn dắt - luôn ra đúng 1 dòng/phần tử
    scalar_history, bất kể trạm đó có dự báo hay không."""
    scalar_history = build_scalar_history(full_day_dir)["2026-08-10"]
    rows = join_forecast_obs(_forecast_rows(), scalar_history)

    assert len(rows) == len(scalar_history)
    for row in rows:
        assert row["forecast"]["hour"] == row["hour"] == row["obs"]["hour"]
        assert row["forecast"]["station_code"] == row["station_code"] == row["obs"]["station_code"]


def test_join_forecast_obs_row_shape(full_day_dir):
    """Mỗi dòng ghép có 4 khoá - "forecast" và "obs" đều đủ 9 khoá
    (station_code + hour + buoi + 6 field) - hai bên CÙNG bộ khoá nhưng
    khác không gian giá trị (forecast là bucket đã chọn, obs phần lớn là
    số đo thô của đúng trạm đó)."""
    scalar_history = build_scalar_history(full_day_dir)["2026-08-10"]
    row = join_forecast_obs(_forecast_rows(), scalar_history)[0]

    assert set(row.keys()) == {"station_code", "hour", "forecast", "obs"}
    field_keys = {"station_code", "hour", "buoi", "tong_luong_may", "do_cao_man_may",
                  "hien_tuong", "huong_gio", "toc_do_gio", "tam_nhin"}
    assert set(row["forecast"].keys()) == field_keys
    assert set(row["obs"].keys()) == field_keys


def test_join_forecast_obs_station_without_forecast_gets_empty_forecast_row():
    """Trạm/giờ không có dòng dự báo tương ứng -> ghép với 1 dự báo rỗng
    (6 field None), KHÔNG raise và KHÔNG bị bỏ qua - khác hành vi cũ (raise
    ngay) vì giờ forecast_rows có thể chỉ phủ 1 phần trạm quan trắc được."""
    obs_row = {"station_code": "k99", "hour": 0, "buoi": "dem", "tong_luong_may": 5,
               "do_cao_man_may": None, "hien_tuong": "khong", "huong_gio": None,
               "toc_do_gio": None, "tam_nhin": None}

    rows = join_forecast_obs([], [obs_row])

    assert len(rows) == 1
    assert rows[0]["station_code"] == "k99"
    assert rows[0]["obs"] == obs_row
    assert rows[0]["forecast"] == {"station_code": "k99", "hour": 0, "buoi": "dem",
                                    "tong_luong_may": None, "do_cao_man_may": None,
                                    "hien_tuong": None, "huong_gio": None,
                                    "toc_do_gio": None, "tam_nhin": None}


def test_join_forecast_obs_empty_history_returns_empty_list():
    assert join_forecast_obs(_forecast_rows(), []) == []
