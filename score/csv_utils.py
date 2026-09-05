"""
csv_utils.py
====================
Generic CSV writing helper.
"""

import csv


def write_csv(file_path: str, rows: list):
    if not rows:
        return
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
