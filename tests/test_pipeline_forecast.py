"""
test_pipeline_forecast.py
====================
Unit tests for pipeline_forecast.py: build_hourly_table's merge/validation
rules and load_records_csv's CSV -> records coercion.
"""

import pytest

from pipeline_forecast import build_hourly_table, load_records_csv


def _rec(start, end, field, bucket):
    return {"start_hour": start, "end_hour": end, "field_name": field, "bucket_selected": bucket}


# =============================================================================
# build_hourly_table — basic shape
# =============================================================================

def test_build_hourly_table_empty_records():
    assert build_hourly_table([]) == []


def test_build_hourly_table_single_record_spans_inclusive_range():
    rows = build_hourly_table([_rec(7, 9, "tong_luong_may", 2)])
    assert [r["hour"] for r in rows] == [7, 8, 9]
    for r in rows:
        assert r["tong_luong_may"] == 2
        assert r["do_cao_man_may"] is None
        assert r["hien_tuong"] is None
        assert r["huong_gio"] is None
        assert r["toc_do_gio"] is None
        assert r["tam_nhin"] is None


def test_build_hourly_table_hour_range_spans_min_to_max_across_records():
    """The hourly table always covers [min start_hour, max end_hour] across
    ALL records, even fields whose own coverage is narrower."""
    rows = build_hourly_table([_rec(5, 5, "tam_nhin", 0), _rec(20, 20, "huong_gio", 3)])
    assert [r["hour"] for r in rows] == list(range(5, 21))
    assert rows[0]["tam_nhin"] == 0
    assert rows[0]["huong_gio"] is None
    assert rows[-1]["huong_gio"] == 3
    assert rows[-1]["tam_nhin"] is None


def test_build_hourly_table_later_starting_record_wins_on_overlap():
    rows = build_hourly_table([
        _rec(7, 12, "tong_luong_may", 2),
        _rec(10, 15, "tong_luong_may", 5),
    ])
    by_hour = {r["hour"]: r["tong_luong_may"] for r in rows}
    assert by_hour[9] == 2
    assert by_hour[10] == 5   # both cover hour 10; later-starting record wins
    assert by_hour[12] == 5
    assert by_hour[15] == 5


# =============================================================================
# build_hourly_table — validation (field_name / bucket_selected)
# =============================================================================

def test_build_hourly_table_rejects_unknown_field_name():
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 1, "khong_ton_tai", 0)])


def test_build_hourly_table_rejects_partial_batch_on_any_bad_record():
    """One invalid record among several valid ones must reject the whole
    batch, not silently drop just the bad one."""
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 1, "tam_nhin", 0), _rec(2, 3, "tam_nhin", 99)])


@pytest.mark.parametrize("field,valid,invalid", [
    ("tong_luong_may", 8, 9),    # 9 windows -> idx 0..8
    ("toc_do_gio", 16, 17),      # 16 windows + 1 catch-all -> idx 0..16
    ("huong_gio", 15, 16),       # 16 directions -> idx 0..15
    ("tam_nhin", 7, 8),          # 7 bounds -> 8 buckets, idx 0..7
    ("do_cao_man_may", 14, 15),  # 13 bounds + "không màn" -> idx 0..14
])
def test_build_hourly_table_bucket_index_boundaries(field, valid, invalid):
    build_hourly_table([_rec(0, 0, field, valid)])  # does not raise
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 0, field, invalid)])


def test_build_hourly_table_rejects_negative_bucket_index():
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 0, "tam_nhin", -1)])


def test_build_hourly_table_rejects_non_int_bucket_for_scalar_fields():
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 0, "tam_nhin", "2")])


def test_build_hourly_table_rejects_bool_bucket_index():
    """bool is technically an int subclass in Python — must be excluded
    explicitly, not accepted as 0/1."""
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 0, "tam_nhin", True)])


def test_build_hourly_table_hien_tuong_accepts_valid_mega_label():
    rows = build_hourly_table([_rec(0, 0, "hien_tuong", "suong_mu")])
    assert rows[0]["hien_tuong"] == "suong_mu"


def test_build_hourly_table_hien_tuong_rejects_unknown_mega_label():
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 0, "hien_tuong", "khong_ton_tai")])


def test_build_hourly_table_hien_tuong_rejects_int_bucket():
    """hien_tuong buckets are mega LABELS, not indices — an int must not be
    accepted even if it happens to look like a valid index elsewhere."""
    with pytest.raises(ValueError):
        build_hourly_table([_rec(0, 0, "hien_tuong", 0)])


# =============================================================================
# load_records_csv
# =============================================================================

def test_load_records_csv_coerces_hours_and_bucket_to_int():
    records = load_records_csv("tests/fixtures/forecast_sample.csv")
    first = records[0]
    assert first == {"start_hour": 0, "end_hour": 6, "field_name": "tong_luong_may", "bucket_selected": 3}
    assert isinstance(first["start_hour"], int)
    assert isinstance(first["bucket_selected"], int)


def test_load_records_csv_keeps_hien_tuong_bucket_as_string():
    records = load_records_csv("tests/fixtures/forecast_sample.csv")
    hien_tuong_records = [r for r in records if r["field_name"] == "hien_tuong"]
    assert hien_tuong_records
    for r in hien_tuong_records:
        assert isinstance(r["bucket_selected"], str)


def test_load_records_csv_feeds_build_hourly_table_cleanly():
    """The fixture CSV, loaded and merged, must cover a full 24-hour day
    (hours 0-23, min/max across every row) without raising."""
    records = load_records_csv("tests/fixtures/forecast_sample.csv")
    rows = build_hourly_table(records)
    assert [r["hour"] for r in rows] == list(range(24))
