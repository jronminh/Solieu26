"""
test_csv_pipeline.py
====================
Unit tests for the CSV-export half of csv_pipeline.py (flatten_record,
cloud_layers_needed, write_csv, export_history_by_date) plus the small
filename<->datetime helpers. The FTP download layer (download_files,
run_pipeline) needs a live/mocked server and isn't covered here.
"""

import csv
import os

from bulletin.decode import decode_qt_file
from csv_pipeline import (
    cloud_layers_needed,
    export_history_by_date,
    flatten_record,
    parse_obs_dt,
    quantrac_filename_at,
    write_csv,
)
import datetime


# =============================================================================
# Filename <-> datetime helpers
# =============================================================================

def test_quantrac_filename_at():
    dt = datetime.datetime(2026, 4, 1, 13)
    assert quantrac_filename_at(dt) == "Qt26040113.txt"


def test_quantrac_filename_at_midnight():
    dt = datetime.datetime(2026, 8, 10, 0)
    assert quantrac_filename_at(dt) == "Qt26081000.txt"


def test_parse_obs_dt_valid():
    assert parse_obs_dt("Qt26081000.txt") == datetime.datetime(2026, 8, 10, 0)
    assert parse_obs_dt(r"C:\some\dir\Qt26081412.txt") == datetime.datetime(2026, 8, 14, 12)


def test_parse_obs_dt_invalid():
    assert parse_obs_dt("not_a_bulletin.txt") is None
    assert parse_obs_dt(None) is None
    assert parse_obs_dt("") is None


# =============================================================================
# flatten_record — hand-verified against Qt26081000.txt's first (Yên Bái) record
# =============================================================================

def test_flatten_record_yenbai(qt_00):
    records = decode_qt_file(qt_00)
    flat = flatten_record(records[0], source_file=qt_00, max_cloud_layers=1)

    assert flat["obs_time"] == "2026-08-10 00:00"
    assert flat["date"] == "2026-08-10"
    assert flat["hour"] == "00"
    assert flat["source_file"] == "Qt26081000.txt"

    assert flat["station"] == "Yên Bái"
    assert flat["station_code"] == "k31"
    assert flat["lat"] == 21.7333
    assert flat["lon"] == 104.8833

    assert flat["visibility_km"] == 8.0
    assert flat["total_cloud_N"] == "8"
    assert flat["wind_dd_deg"] == 0
    assert flat["wind_ff"] == 0

    assert flat["temperature_c"] == 29.6
    assert flat["dewpoint_c"] == 27.0

    assert flat["weather_ww"] == "Mù"
    assert flat["weather_W1"] == "Nhiều mây"
    assert flat["weather_W2"] == "Nhiều mây"

    # Yên Bái's record has no 'A' (storm) group -> columns present but blank
    assert flat["storm_dd_deg"] is None
    assert flat["storm_distance"] is None
    assert flat["storm_trend"] is None

    assert flat["pressure_hpa"] == 993.7

    assert flat["cloud_layers"] == 1
    assert flat["cloud_1_Ns"] == "8"
    assert flat["cloud_1_C"] == "Sc"
    assert flat["cloud_1_hshs"] == 1400

    # 'raw' is the last key and holds the original bulletin line
    assert list(flat.keys())[-1] == "raw"
    assert flat["raw"] == records[0]["raw"]


def test_flatten_record_pads_missing_cloud_layers():
    """max_cloud_layers controls how many cloud_N_* column groups get created
    — layers beyond what the record reported come back as None, not missing."""
    records = [{"cloud": [{"cloud_Ns": "8", "cloud_C": "Sc", "cloud_hshs": 1400}]}]
    flat = flatten_record(records[0], max_cloud_layers=3)
    assert flat["cloud_2_Ns"] is None
    assert flat["cloud_3_hshs"] is None


def test_flatten_record_storm_group():
    record = {"storm": {"storm_dd": 140, "storm_L": "10-20km", "storm_Cg": "Phát triển chậm"}}
    flat = flatten_record(record, max_cloud_layers=1)
    assert flat["storm_dd_deg"] == 140
    assert flat["storm_distance"] == "10-20km"
    assert flat["storm_trend"] == "Phát triển chậm"


def test_flatten_record_no_source_file():
    flat = flatten_record({}, source_file=None)
    assert flat["obs_time"] is None
    assert flat["date"] is None
    assert flat["hour"] is None
    assert flat["source_file"] is None


# =============================================================================
# cloud_layers_needed
# =============================================================================

def test_cloud_layers_needed_real_file(qt_4_clouds):
    records = decode_qt_file(qt_4_clouds)
    assert cloud_layers_needed(records) == 4


def test_cloud_layers_needed_defaults_to_1_when_none_reported():
    assert cloud_layers_needed([{"cloud": []}, {"cloud": []}]) == 1
    assert cloud_layers_needed([]) == 1


def test_cloud_layers_needed_caps_at_limit():
    records = [{"cloud": [{}] * 7}]
    assert cloud_layers_needed(records, cap=4) == 4


# =============================================================================
# write_csv
# =============================================================================

def test_write_csv_roundtrip(tmp_path):
    rows = [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]
    out = tmp_path / "out.csv"
    write_csv(str(out), rows)

    with open(out, encoding="utf-8-sig", newline="") as f:
        read_rows = list(csv.DictReader(f))
    assert read_rows == rows


def test_write_csv_no_rows_does_not_create_file(tmp_path):
    out = tmp_path / "out.csv"
    write_csv(str(out), [])
    assert not out.exists()


# =============================================================================
# export_history_by_date — real files spanning two different dates
# =============================================================================

def test_export_history_by_date_splits_per_date(qt_00, qt_other_day, tmp_path):
    exported = export_history_by_date([qt_00, qt_other_day], str(tmp_path))

    assert set(exported.keys()) == {"2026-08-10", "2026-08-11"}
    for date_key, info in exported.items():
        assert info["records"] == 20
        assert os.path.isfile(info["csv"])
        assert info["csv"].endswith(f"history_{date_key.replace('-', '')}.csv")
        with open(info["csv"], encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 20


def test_export_history_by_date_full_day_continuity(full_day_qt_files, tmp_path):
    """A full, uninterrupted day (24 real hourly files, 20 stations each)
    must roll up into one CSV covering every hour 00-23 with no gaps or
    duplicates, and each station present in every hour — the 2-file test
    above only proves two isolated hours split into separate dates; it can't
    catch a bug that only shows up once a whole day's worth of consecutive
    hours accumulate (e.g. an off-by-one dropping/duplicating a boundary
    hour, or a station going missing partway through the day)."""
    exported = export_history_by_date(full_day_qt_files, str(tmp_path))

    assert set(exported.keys()) == {"2026-08-10"}
    info = exported["2026-08-10"]
    assert info["records"] == 24 * 20

    with open(info["csv"], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 24 * 20

    expected_hours = [f"{h:02d}" for h in range(24)]
    hours = [row["hour"] for row in rows]
    assert sorted(set(hours)) == expected_hours  # no missing/extra hour
    hour_counts = {h: hours.count(h) for h in expected_hours}
    assert all(count == 20 for count in hour_counts.values())  # 20 stations, every hour

    station_codes = {row["station_code"] for row in rows}
    assert len(station_codes) == 20
    for code in station_codes:
        assert sum(1 for row in rows if row["station_code"] == code) == 24  # present all day


def test_export_history_by_date_unknown_bucket_for_unparseable_filename(tmp_path):
    """A file that doesn't match QtYYMMDDHH.txt should land under the
    'unknown' date key instead of being silently dropped."""
    src = tmp_path / "weird_name.txt"
    src.write_text("k3158 60000 7453 tYên Bái  k31214410453;", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    exported = export_history_by_date([str(src)], str(out_dir))

    assert "unknown" in exported
    assert exported["unknown"]["records"] == 1
