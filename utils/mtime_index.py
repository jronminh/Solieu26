"""
mtime_index.py
====================
Per-filename record of the server mtime/size seen at download time, so a
later listing can tell a re-uploaded/corrected file (same name, newer
content) from one already up to date. Lives at TEMP_DL_DIR/mtime_index.json,
alongside the downloaded bulletins; see pipeline/fetch.py's download_files()
for how it's consulted.
"""

import json
import os


def load_index(path: str) -> dict:
    """{} if the file is missing, unreadable, or not a JSON object — same
    "absent means no data yet" stance as cli_runner.load_config_file()."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_index(path: str, index: dict):
    """Atomic write (.tmp + os.replace), mirroring utils/ftp_utils.py's
    download pattern: this file is rewritten every listing cycle, so a crash
    mid-write must never leave a half-written index behind."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f)
    os.replace(tmp, path)
