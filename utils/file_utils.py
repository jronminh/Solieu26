"""
file_utils.py
====================
OS-level file/folder operations — open a path with its default application.
No GUI/business-logic dependency, so it's safe to import from anywhere.
"""

import os
import subprocess
import sys


def _os_open(path: str):
    """Hand `path` to the OS's default handler — file manager for a folder, the
    associated app for a file. Returns (ok: bool, reason/path)."""
    try:
        if os.name == "nt":
            os.startfile(path)                       # Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])         # macOS
        else:
            subprocess.Popen(["xdg-open", path])     # Linux
        return True, path
    except Exception as e:
        return False, str(e)


def open_folder(path: str):
    """Open a folder with the OS's file manager. Returns (ok: bool, reason/path)."""
    if not path:
        return False, "chưa có thư mục xuất (cần chạy thành công ít nhất một lần)"
    path = os.path.abspath(path)                      # './x' → absolute (Windows dislikes relative paths)
    if not os.path.isdir(path):
        return False, f"thư mục không tồn tại: {path}"
    return _os_open(path)


def open_in_editor(path: str):
    """Open a FILE with its default application (for editing). Returns (ok, reason/path)."""
    if not path:
        return False, "chưa có đường dẫn file"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, f"file không tồn tại: {path}"
    return _os_open(path)
