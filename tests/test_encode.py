"""
test_encode.py
====================
encode.py is the reverse of decode.py — the main thing worth testing is that
encode_record() -> decode_record() round-trips back to the values that went
in (within the format's own precision), plus the validation errors each
encoder raises for out-of-range input.
"""

import pytest

from decode import decode_record
from encode import (
    encode_pressure,
    encode_record,
    encode_tail,
    encode_wind,
)


def test_encode_decode_roundtrip_basic():
    raw = encode_record(
        station_code="k31", lat=21.7333, lon=104.8833,
        vv_code="58", wind_N_code="6", wind_dd=0, wind_ff=0,
        temp_c=29.6, dew_c=27.0,
        ww_code="10", w1_code="2", w2_code="2",
        clouds=[{"N": "6", "C": "6", "hshs": "47"}],
        pressure_mmhg=745.3, station_name="Yên Bái",
    )
    decoded = decode_record(raw)

    assert decoded["temperature"] == 29.6
    assert decoded["dewpoint"] == 27.0
    assert decoded["station"] == "Yên Bái"
    assert decoded["location"]["station_code"] == "k31"
    assert decoded["location"]["lat"] == 21.7333
    assert decoded["location"]["lon"] == 104.8833
    assert decoded["pressure"]["pressure_raw"] == 745.3


def test_encode_decode_roundtrip_negative_temperature():
    """Real August data has no negative temps, so this path is otherwise
    untested — exercise it directly through the encode/decode round trip."""
    raw = encode_record(
        station_code="k31", lat=21.7, lon=104.85,
        vv_code="00", wind_N_code="0", wind_dd=0, wind_ff=0,
        temp_c=-5.3, dew_c=-10.0,
    )
    decoded = decode_record(raw)
    assert decoded["temperature"] == -5.3
    assert decoded["dewpoint"] == -10.0


def test_encode_decode_roundtrip_against_real_fixture(qt_00):
    """Re-encode the hand-verified Yên Bái record's decoded values and check
    it decodes back to the same numbers — ties encode.py to the same real
    data decode.py is tested against."""
    from decode import decode_qt_file

    original = decode_qt_file(qt_00)[0]
    raw = encode_record(
        station_code=original["location"]["station_code"],
        lat=original["location"]["lat"], lon=original["location"]["lon"],
        vv_code="58", wind_N_code="6",
        wind_dd=original["wind"]["wind_dd"], wind_ff=original["wind"]["wind_ff"],
        temp_c=original["temperature"], dew_c=original["dewpoint"],
        station_name=original["station"],
    )
    re_decoded = decode_record(raw)
    assert re_decoded["temperature"] == original["temperature"]
    assert re_decoded["dewpoint"] == original["dewpoint"]
    assert re_decoded["location"] == original["location"]
    assert re_decoded["station"] == original["station"]


def test_encode_wind():
    assert encode_wind("6", 120, 11) == "61211"


def test_encode_tail_rejects_bad_station_code():
    with pytest.raises(ValueError):
        encode_tail("31", 21.7, 104.85)   # missing 'k' prefix


def test_encode_pressure_valid_range():
    assert encode_pressure(745.3) == "7453"
    assert encode_pressure(700.0) == "7000"
    assert encode_pressure(799.94) == "7999"  # highest value that still round-trips


def test_encode_pressure_out_of_range():
    with pytest.raises(ValueError):
        encode_pressure(650.0)
    with pytest.raises(ValueError):
        encode_pressure(850.0)
