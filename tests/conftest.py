"""
conftest.py
====================
Shared pytest fixtures for the test suite.

FIXTURES_DIR/qt_files holds a small, hand-picked set of REAL raw bulletin
files copied verbatim from a live download (~/solieu26_dl/data) — not
synthetic data — so decode.py/pipeline.py get exercised against the actual
byte-for-byte format the FTP server sends, edge cases included (see the
docstring on each fixture file below for why it was picked).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "qt_files")

# One file per interesting real-world trait:
#   qt_00        — plain ';'-terminated file, used for hand-verified assertions
#   qt_eq_sep    — uses '=' instead of ';' as the record terminator
#   qt_other_day — a different observation date, for multi-date CSV grouping
#   qt_4_clouds  — the one file with the max 4 reported cloud layers
QT_00        = os.path.join(FIXTURES_DIR, "Qt26081000.txt")
QT_EQ_SEP    = os.path.join(FIXTURES_DIR, "Qt26081023.txt")
QT_OTHER_DAY = os.path.join(FIXTURES_DIR, "Qt26081100.txt")
QT_4_CLOUDS  = os.path.join(FIXTURES_DIR, "Qt26081214.txt")


@pytest.fixture
def qt_00():
    return QT_00


@pytest.fixture
def qt_eq_sep():
    return QT_EQ_SEP


@pytest.fixture
def qt_other_day():
    return QT_OTHER_DAY


@pytest.fixture
def qt_4_clouds():
    return QT_4_CLOUDS


@pytest.fixture
def all_qt_files():
    return [QT_00, QT_EQ_SEP, QT_OTHER_DAY, QT_4_CLOUDS]


# A full, uninterrupted day (all 24 hourly files, 2026-08-10, 20 stations
# each) — the 4 single-hour fixtures above can't catch bugs in how
# pipeline.py stitches a continuous run of hours together (missing/duplicate
# hours, wrong sort order, wrong per-hour record counts); this can.
FULL_DAY_DIR = os.path.join(FIXTURES_DIR, "full_day_20260810")


@pytest.fixture
def full_day_qt_files():
    return sorted(
        os.path.join(FULL_DAY_DIR, name) for name in os.listdir(FULL_DAY_DIR)
    )
