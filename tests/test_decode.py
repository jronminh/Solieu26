"""
test_decode.py
====================
Unit tests for decode.py's pure functions, plus integration checks against
the real bulletin files under tests/fixtures/qt_files/.
"""

from decode import (
    decode_cloud,
    decode_head,
    decode_history,
    decode_name,
    decode_pressure,
    decode_qt_file,
    decode_record,
    decode_tail,
    decode_wind,
    decode_weather,
    get_qt_data,
    hshs_value,
    is_pressure_token,
    split_record,
    vv_value,
)
from tables import TABLES


# =============================================================================
# is_pressure_token / split_record
# =============================================================================

def test_is_pressure_token():
    assert is_pressure_token("7453")       # 4 digits, starts with '7'
    assert not is_pressure_token("71022")  # 5 digits
    assert not is_pressure_token("8453")   # doesn't start with '7'
    assert not is_pressure_token("745a")   # not all digits


def test_split_record_empty():
    assert split_record("") == {
        "head": None, "wind": None, "indicators": [],
        "pressure": None, "name": [], "tail": None,
    }


def test_split_record_full_yenbai():
    """Hand-verified against the first record of Qt26081000.txt."""
    record = ("k3158 60000 10296 20270 71022 86647 7453 "
              "tYên Bái  k31214410453")
    parts = split_record(record)
    assert parts["head"] == "k3158"
    assert parts["wind"] == "60000"
    assert parts["indicators"] == ["10296", "20270", "71022", "86647"]
    assert parts["pressure"] == "7453"
    assert parts["name"] == ["tYên", "Bái"]
    assert parts["tail"] == "k31214410453"


def test_split_record_no_head_no_wind():
    """A record whose first token isn't 'k...' (e.g. Kiến An in the sample
    data, which only has a name + tail, no head/wind/indicators)."""
    record = "tKiến An  k33204810636"
    parts = split_record(record)
    assert parts["head"] is None
    assert parts["wind"] is None
    assert parts["name"] == ["tKiến", "An"]
    assert parts["tail"] == "k33204810636"


# =============================================================================
# vv_value / hshs_value
# =============================================================================

def test_vv_value_ranges():
    assert vv_value("30", TABLES) == "3.0"       # < 51 -> "d.d" km
    assert vv_value("53", TABLES) is None         # 51-55 undefined
    assert vv_value("58", TABLES) == "8"          # 56-80 -> vv - 50
    assert vv_value("85", TABLES) == "45"         # 81-89 -> vv - 40
    assert vv_value("94", TABLES) == "1"          # special table
    assert vv_value("x", TABLES) is None          # non-numeric
    assert vv_value("5", TABLES) is None          # too short


def test_hshs_value_ranges():
    assert hshs_value("03", TABLES) == 90         # 1-5 -> h*30
    assert hshs_value("20", TABLES) == 600        # 6-50 -> round(h*30/50)*50
    assert hshs_value("00", TABLES) == 30         # special table
    assert hshs_value("90", TABLES) == "<50"       # special, qualitative
    assert hshs_value("ab", TABLES) is None        # non-numeric


# =============================================================================
# Token decoders
# =============================================================================

def test_decode_head():
    assert decode_head("k3158", TABLES) == {"iii": "k31", "VV": "8"}
    assert decode_head(None, TABLES) is None
    assert decode_head("60000", TABLES) is None  # doesn't start with 'k'


def test_decode_wind():
    assert decode_wind("60000", TABLES) == {"wind_N": "8", "wind_dd": 0, "wind_ff": 0}
    assert decode_wind("21211", TABLES) == {"wind_N": "3", "wind_dd": 120, "wind_ff": 11}
    assert decode_wind(None, TABLES) is None
    assert decode_wind("abc", TABLES) is None  # too short


def test_decode_wind_bad_digits_keeps_N():
    assert decode_wind("6abcd", TABLES) == {"wind_N": "8", "wind_dd": None, "wind_ff": None}


def test_decode_weather():
    assert decode_weather("71022", TABLES) == {"ww": "Mù", "W1": "Nhiều mây", "W2": "Nhiều mây"}
    assert decode_weather("710", TABLES) is None  # too short


def test_decode_cloud():
    assert decode_cloud("86647", TABLES) == {"cloud_Ns": "8", "cloud_C": "Sc", "cloud_hshs": 1400}
    assert decode_cloud("864", TABLES) is None


def test_decode_pressure():
    assert decode_pressure("7453") == {"pressure_raw": 745.3, "pressure_hpa": 993.7}
    assert decode_pressure(None) is None
    assert decode_pressure("745") is None  # wrong length


def test_decode_name():
    assert decode_name(["tYên", "Bái"]) == "Yên Bái"
    assert decode_name([]) is None


def test_decode_tail():
    assert decode_tail("k31214410453") == {
        "station_code": "k31", "lat": 21.7333, "lon": 104.8833,
    }
    assert decode_tail(None) is None
    assert decode_tail("short") is None


# =============================================================================
# decode_record — hand-verified against the first record of Qt26081000.txt
# =============================================================================

def test_decode_record_yenbai():
    record = ("k3158 60000 10296 20270 71022 86647 7453 "
              "tYên Bái  k31214410453")
    decoded = decode_record(record)

    assert decoded["head"] == {"iii": "k31", "VV": "8"}
    assert decoded["wind"] == {"wind_N": "8", "wind_dd": 0, "wind_ff": 0}
    assert decoded["temperature"] == 29.6
    assert decoded["dewpoint"] == 27.0
    assert decoded["weather"] == {"ww": "Mù", "W1": "Nhiều mây", "W2": "Nhiều mây"}
    assert decoded["pressure"] == {"pressure_raw": 745.3, "pressure_hpa": 993.7}
    assert decoded["station"] == "Yên Bái"
    assert decoded["location"] == {"station_code": "k31", "lat": 21.7333, "lon": 104.8833}
    assert decoded["raw"] == record


def test_decode_record_name_only_station():
    """Stations like Kiến An in the sample data report only a name + tail
    (no head/wind/indicators/pressure at all)."""
    record = "tKiến An  k33204810636"
    decoded = decode_record(record)
    assert decoded["head"] is None
    assert decoded["wind"] is None
    assert decoded["temperature"] is None
    assert decoded["dewpoint"] is None
    assert decoded["weather"] is None
    assert decoded["pressure"] is None
    assert decoded["station"] == "Kiến An"
    assert decoded["location"] == {"station_code": "k33", "lat": 20.8, "lon": 106.6}


def test_decode_indicators_ignores_unknown_groups():
    """Group codes other than 1/2/7/8 (e.g. '9' supplementary data) must be
    silently ignored, not raise — see the TODO note in decode.py."""
    record = "k3158 60000 90000 7453 tYên Bái  k31214410453"
    decoded = decode_record(record)
    assert decoded["temperature"] is None
    assert decoded["pressure"] == {"pressure_raw": 745.3, "pressure_hpa": 993.7}


# =============================================================================
# File-level: get_qt_data / decode_qt_file / decode_history against real files
# =============================================================================

def test_get_qt_data_semicolon_separator(qt_00):
    records = get_qt_data(qt_00)
    assert len(records) == 20  # 20 stations per hourly file
    assert records[0].startswith("k3158")


def test_get_qt_data_equals_separator(qt_eq_sep):
    """Qt26081023.txt is one of the real files that uses '=' instead of ';'
    as the record terminator — get_qt_data must fall back to it."""
    with open(qt_eq_sep, encoding="utf-8") as f:
        raw = f.read()
    assert ";" not in raw
    assert "=" in raw

    records = get_qt_data(qt_eq_sep)
    assert len(records) == 20


def test_get_qt_data_empty_file(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("", encoding="utf-8")
    assert get_qt_data(str(p)) == []


def test_decode_qt_file_all_records_decode_cleanly(all_qt_files):
    for path in all_qt_files:
        results = decode_qt_file(path)
        assert len(results) == 20
        for r in results:
            assert "error" not in r
            assert r["location"] is not None


def test_decode_qt_file_max_cloud_layers(qt_4_clouds):
    results = decode_qt_file(qt_4_clouds)
    max_layers = max(len(r.get("cloud") or []) for r in results)
    assert max_layers == 4


def test_decode_history_sorts_and_tags_source_file(all_qt_files):
    results = decode_history(all_qt_files)
    # every record keeps a "file" pointer back to its source
    assert all(item["file"] in all_qt_files for item in results)
    # files were processed in sorted() order (Qt26081000 before Qt26081023 etc.)
    seen_order = list(dict.fromkeys(item["file"] for item in results))
    assert seen_order == sorted(all_qt_files)


def test_decode_history_drops_records_without_location():
    """decode_history keeps only records whose tail decoded into a location
    — this is the one filtering step it does. Build a tiny fake file with one
    good and one malformed (no k-tail) record to exercise that branch."""
    import os as _os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = _os.path.join(d, "Qt26081099.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("k3158 60000 7453 tYên Bái  k31214410453;")
            f.write("no tail here at all;")

        results = decode_history([path])
        assert len(results) == 1
        assert results[0]["data"]["station"] == "Yên Bái"
