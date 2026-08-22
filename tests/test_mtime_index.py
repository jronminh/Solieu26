"""
test_mtime_index.py
====================
utils/mtime_index.py: load/save round-trip, corrupt/missing file handling,
atomic write (no orphan .tmp left behind).
"""

import os

from utils.mtime_index import load_index, save_index


def test_load_missing_file_returns_empty_dict(tmp_path):
    path = str(tmp_path / "mtime_index.json")
    assert load_index(path) == {}


def test_save_then_load_round_trip(tmp_path):
    path = str(tmp_path / "mtime_index.json")
    index = {"Qt26081000.txt": {"mtime": "20260810000000", "size": 123}}
    save_index(path, index)
    assert load_index(path) == index


def test_load_corrupt_json_returns_empty_dict(tmp_path):
    path = str(tmp_path / "mtime_index.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert load_index(path) == {}


def test_load_non_dict_json_returns_empty_dict(tmp_path):
    path = str(tmp_path / "mtime_index.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")
    assert load_index(path) == {}


def test_save_writes_atomically_no_leftover_tmp(tmp_path):
    path = str(tmp_path / "mtime_index.json")
    save_index(path, {"a": 1})
    assert os.path.isfile(path)
    assert not os.path.exists(path + ".tmp")


def test_save_overwrites_existing_index(tmp_path):
    path = str(tmp_path / "mtime_index.json")
    save_index(path, {"a": 1})
    save_index(path, {"b": 2})
    assert load_index(path) == {"b": 2}
