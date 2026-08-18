"""
test_bulletin_generator.py
====================
bulletin_generator.py's table backbone stores {start, end, field, value} rows
and merges them into one encode_record() call per hour any row's range
touches. This tests only that pure merge/encode logic (_covered_hours,
_merge_at_hour, _encode_state, _row_value_str, the FIELD_DEFS registry) —
no Tkinter widgets are built or shown, so no display is required.

Two of these cases (inclusive end-hour, per-hour breakpoints instead of
per-row-start) are regression tests for bugs a user caught by hand: a
"07-09" row originally produced only one code (at 07h) instead of one per
covered hour, and the end hour was originally exclusive so "09" wasn't
covered at all.
"""

import pytest

from bulletin.bulletin_generator import (
    CLOUD_FIELD_KEYS,
    FIELD_DEFS,
    _covered_hours,
    _encode_state,
    _field_key_from_label,
    _merge_at_hour,
    _row_value_str,
)
from bulletin.decode import decode_record
from bulletin.code_tables import TABLES


def _row(start, end, field, value, _id=1):
    return {"_id": _id, "start": start, "end": end, "field": field, "value": value}


def test_covered_hours_single_row_is_inclusive_both_ends():
    """Regression: a '07-09' row must cover 07, 08 AND 09 (3 hours), not
    just 07 (the original per-row-start bug) or 07-08 (the original
    exclusive-end bug)."""
    rows = [_row(7, 9, "wind_ff", 5.0)]
    assert _covered_hours(rows) == [7, 8, 9]


def test_covered_hours_unions_across_rows():
    rows = [_row(7, 9, "wind_ff", 5.0, 1), _row(20, 22, "temp", 15.0, 2)]
    assert _covered_hours(rows) == [7, 8, 9, 20, 21, 22]


def test_covered_hours_single_hour_row():
    """start == end is a valid single-hour row."""
    assert _covered_hours([_row(5, 5, "pressure", 754.0)]) == [5]


def test_merge_at_hour_later_starting_row_wins_on_overlap():
    rows = [_row(7, 9, "wind_ff", 5.0, 1), _row(9, 11, "wind_ff", 7.0, 2)]
    assert _merge_at_hour(rows, 8) == {"wind_ff": 5.0}
    assert _merge_at_hour(rows, 9) == {"wind_ff": 7.0}   # both cover hour 9; row 2 started later
    assert _merge_at_hour(rows, 10) == {"wind_ff": 7.0}
    assert _merge_at_hour(rows, 12) == {}                # outside every row's range


def test_merge_at_hour_combines_different_fields():
    rows = [_row(7, 12, "wind_ff", 5.0, 1), _row(9, 12, "temp", 28.5, 2)]
    assert _merge_at_hour(rows, 8) == {"wind_ff": 5.0}
    assert _merge_at_hour(rows, 9) == {"wind_ff": 5.0, "temp": 28.5}


def test_encode_state_defaults_mandatory_fields_when_uncovered():
    """vv/N_total/wind_dd/wind_ff are mandatory tokens in every record — an
    uncovered hour must still encode (using the documented 0/"0" defaults),
    not raise."""
    raw = _encode_state({}, "k31", 21.7, 104.85, "Yên Bái")
    decoded = decode_record(raw)
    assert decoded["wind"] == {"wind_dd": 0, "wind_ff": 0}
    assert decoded["total_cloud"] == {"total_cloud_N": 0}
    assert decoded["head"]["VV"] == 0.0


def test_encode_state_omits_uncovered_optional_fields():
    state = {"wind_ff": 5.0}
    raw = _encode_state(state, "k31", 21.7, 104.85, "Yên Bái")
    decoded = decode_record(raw)
    assert decoded["temperature"] is None
    assert decoded["dewpoint"] is None
    assert decoded["pressure"] is None
    assert decoded["weather"] is None
    assert "cloud" not in decoded  # key is only added when an '8' token is present


def test_encode_state_includes_covered_fields():
    state = {"wind_ff": 5.0, "wind_dd": 120.0, "N_total": "6", "vv": "58",
             "temp": 29.6, "dew": 27.0, "pressure": 745.3,
             "cloud1": {"N": "6", "C": "6", "hshs": "47"}}
    raw = _encode_state(state, "k31", 21.7, 104.85, "Yên Bái")
    decoded = decode_record(raw)
    assert decoded["temperature"] == 29.6
    assert decoded["dewpoint"] == 27.0
    assert decoded["pressure"]["pressure_raw"] == 745.3
    assert len(decoded["cloud"]) == 1
    assert decoded["wind"]["wind_ff"] == 5
    assert decoded["wind"]["wind_dd"] == 120


def test_encode_state_orders_cloud_layers_by_slot():
    # distinct N_oktas codes per slot, inserted out of order, to prove
    # _encode_state emits them cloud1..cloud4 regardless of dict order
    codes = {"cloud2": "2", "cloud4": "4", "cloud1": "1", "cloud3": "3"}
    state = {k: {"N": code, "C": "0", "hshs": "00"} for k, code in codes.items()}
    raw = _encode_state(state, "k31", 21.7, 104.85, "Yên Bái")
    decoded = decode_record(raw)
    assert len(decoded["cloud"]) == 4
    got_Ns = [layer["amount"] for layer in decoded["cloud"]]
    expected_Ns = [int(TABLES["N_oktas"][codes[f"cloud{i}"]]) for i in (1, 2, 3, 4)]
    assert got_Ns == expected_Ns


def test_full_scenario_matches_reported_example():
    """The scenario a user reported by hand: wind 5 m/s from 07-09, then
    7 m/s from 09-11 — must yield 5 hourly codes (07..11), each with the
    right wind speed, and the shared boundary hour (09) uses the
    later-starting row's value."""
    rows = [_row(7, 9, "wind_ff", 5.0, 1), _row(9, 11, "wind_ff", 7.0, 2)]
    hours = _covered_hours(rows)
    assert hours == [7, 8, 9, 10, 11]

    expected = {7: 5, 8: 5, 9: 7, 10: 7, 11: 7}
    for h in hours:
        state = _merge_at_hour(rows, h)
        raw = _encode_state(state, "k31", 21.7, 104.85, "Yên Bái")
        assert decode_record(raw)["wind"]["wind_ff"] == expected[h]


@pytest.mark.parametrize("key", list(FIELD_DEFS.keys()))
def test_field_key_from_label_roundtrips_every_field(key):
    assert _field_key_from_label(FIELD_DEFS[key]["label"]) == key


def test_field_key_from_label_unknown_returns_none():
    assert _field_key_from_label("không tồn tại") is None


def test_row_value_str_scalar_fields():
    assert _row_value_str(_row(0, 0, "wind_ff", 5.0)) == "5"
    assert _row_value_str(_row(0, 0, "wind_dd", 120.0)) == "120°"
    assert _row_value_str(_row(0, 0, "temp", 28.5)) == "28.5°C"
    assert _row_value_str(_row(0, 0, "pressure", 754.0)) == "754.0 mmHg"


def test_row_value_str_cloud_field_shows_height_when_valid():
    v = {"N": "6", "C": "6", "hshs": "47"}
    s = _row_value_str(_row(0, 0, "cloud1", v))
    assert TABLES["cloud_type"]["6"] in s
    assert "h≈" in s  # height preview present (hshs "47" decodes to a real height)


def test_cloud_field_keys_are_all_in_field_defs():
    assert set(CLOUD_FIELD_KEYS) <= set(FIELD_DEFS.keys())
