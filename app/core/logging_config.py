"""
Two log files instead of relying on terminal output:
  - logs/app.log          General application logs — same content you'd see in the
                           terminal (INFO/WARNING/ERROR from every module that does
                           `logging.getLogger(__name__)`), timestamped, rotated so it
                           doesn't grow forever.
  - logs/http_access.log  One line per HTTP request — timestamp, client IP, method,
                           path, status code, duration, user-agent. Analogous to
                            the Apache combined log format.

Call setup_logging() once at process startup, before the app starts handling
requests. Every module that does `logger = logging.getLogger(__name__)` — main,
github_service, ai_service, etc. — automatically funnels into the app.log handlers
below via Python's normal logging hierarchy (child loggers propagate to root unless
told not to). Nothing in those files needs to change.

Known limitation: RotatingFileHandler is not safe across multiple OS processes
writing the same file concurrently (fine for `uvicorn --reload`'s single worker, or
gunicorn with --workers 1). If you scale to multiple worker processes later, either
give each worker its own log file (e.g. suffix by PID) or switch to a
QueueHandler + a single listener process, or ship logs to a centralized service
instead of local files.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import get_settings

_settings = get_settings()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / _settings.log_dir

_APP_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure the root logger — call this once, early, in main.py."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_APP_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOGS_DIR / "app.log",
        maxBytes=_settings.log_max_bytes,
        backupCount=_settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(_settings.log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_access_logger() -> logging.Logger:
    """
    Separate logger + handler, deliberately NOT propagating to the root logger —
    access log lines shouldn't also land in app.log; different consumers, different
    rotation needs, and mixing them makes both harder to grep.
    """
    access_logger = logging.getLogger("http.access")
    if access_logger.handlers:
        return access_logger

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

    handler = RotatingFileHandler(
        LOGS_DIR / "http_access.log",
        maxBytes=_settings.log_max_bytes,
        backupCount=_settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)
    return access_logger