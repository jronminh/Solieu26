"""
test_pipeline_scoring.py
====================
Unit tests for pipeline_scoring.py's score_history: correct dispatch of
each field to scoring/scorer.py's score_<field>() (values reused from
tests/test_scorer.py's hand-verified cases - each score_<field>() now
takes the WHOLE forecast_row/obs dict, not a scalar), and output row
shape/order.

End-to-end smoke test at the bottom runs join_forecast_obs() +
score_history() together on the real full-day fixture (already covered
individually by tests/test_time_sync.py and tests/test_scorer.py).
"""

import datetime

from pipeline_forecast import build_hourly_table, load_records_csv
from pipeline_obs import build_scalar_history
from pipeline_scoring import FIELD_ORDER, join_forecast_obs, score_history

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
    scalar_history = build_scalar_history(datetime.date(2026, 8, 10), full_day_dir)

    scores = score_history(join_forecast_obs(forecast_rows, scalar_history))

    assert len(scores) == 24 * len(FIELD_ORDER)
    for r in scores:
        assert 0 <= r["hour"] <= 23
        assert r["field_name"] in FIELD_ORDER
        assert r["score"] in (True, False, None)
