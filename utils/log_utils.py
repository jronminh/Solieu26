"""
log_utils.py
====================
File logging setup: one rotating file under USER_BASE_DIR/logs, DEBUG level,
with module/function/line and full tracebacks. Separate from the in-app log
tab (main.py's App._log, RAM-only, capped at MAX_LOG_LINES) - this is the
channel for post-mortem debugging when that buffer isn't enough or the app
has already closed.
"""

import logging
import logging.handlers
import os

from utils import config_utils as config

LOG_DIR = os.path.join(config.USER_BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "solieu26.log")

# Maps the GUI's ad-hoc level strings (common.LOG_COLORS) onto stdlib levels,
# for bridging App._log() into the file logger.
UI_LEVEL_MAP = {
    "INFO": logging.INFO,
    "OK":   logging.INFO,
    "SKIP": logging.INFO,
    "ACT":  logging.INFO,
    "MISS": logging.WARNING,
    "WARN": logging.WARNING,
    "ERR":  logging.ERROR,
}

_configured = False


def setup_file_logging():
    """Attach the rotating file handler to the 'solieu26' logger tree. Safe to
    call more than once (e.g. from tests importing main) - only the first call
    does anything."""
    global _configured
    if _configured:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s:%(funcName)s:%(lineno)d  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger = logging.getLogger("solieu26")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Child of the 'solieu26' logger tree, e.g. get_logger('fetch') -> 'solieu26.fetch'."""
    return logging.getLogger(f"solieu26.{name}")
