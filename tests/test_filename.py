"""
test_filename.py
====================
Unit tests for bulletin/filename.py: the QtYYMMDDHH.txt filename<->datetime
helpers, both directions.
"""

import datetime

from bulletin.filename import parse_obs_dt, quantrac_filename_at


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
