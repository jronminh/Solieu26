"""
filename.py
====================
Bulletin filename <-> datetime, both directions: 'QtYYMMDDHH.txt' names an
hourly bulletin file, no century, hour zero-padded.
"""

import datetime
import os


def quantrac_filename_at(dt: datetime.datetime) -> str:
    """Qt<YY><MM><DD><HH>.txt — e.g. datetime(2026,4,1,13) → 'Qt26040113.txt'."""
    return f"Qt{dt.strftime('%y%m%d')}{dt.hour:02}.txt"


def parse_obs_dt(filename: str):
    """
    Extract the observation datetime from a 'QtYYMMDDHH.txt' filename.
    Returns a datetime, or None if the name doesn't match the pattern.
    Used to generate a real time column for the CSV (instead of burying it in source_file).
    """
    if not filename:
        return None
    base = os.path.basename(filename)
    try:
        return datetime.datetime.strptime(base[2:10], "%y%m%d%H")
    except (ValueError, IndexError):
        return None
