"""
ini_utils.py
====================
Generic single-key .ini file update, preserving every other line.
"""

import os


def update_ini_key(path: str, section: str, key: str, value: str):
    """
    Update/add a SINGLE key in an .ini file, preserving every other line (including
    comments) — unlike configparser.write(), which rewrites the whole file and
    drops all comments. Missing file/section → created at the end.
    """
    section_header = f"[{section}]"
    lines = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    sec_start = next((i for i, l in enumerate(lines) if l.strip() == section_header), None)
    new_line = f"{key} = {value}\n"

    if sec_start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines:
            lines.append("\n")
        lines.append(section_header + "\n")
        lines.append(new_line)
    else:
        sec_end = len(lines)
        for i in range(sec_start + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                sec_end = i
                break
        key_idx = next((i for i in range(sec_start + 1, sec_end)
                        if lines[i].split("=", 1)[0].strip().lower() == key.lower()), None)
        if key_idx is not None:
            lines[key_idx] = new_line
        else:
            lines.insert(sec_end, new_line)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
