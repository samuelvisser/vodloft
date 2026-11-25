"""The optional log file: everything VODLoft logs, at the application log level, in ``logs/vodloft.log`` next to
config.yml. Unlike the Logs page, it survives restarts and updates."""
from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import AppSettings
from config.settings.base import get_config_path

from backend.logging_buffer import is_logs_endpoint_access

LOG_FILE_NAME = "vodloft.log"
# Uvicorn's own loggers do not pass their records on to the root logger, so they get the handler directly.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_handler: _LogFileHandler | None = None


class _LogFileHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        # The Logs page polls every few seconds; those requests would bury everything else.
        if is_logs_endpoint_access(record):
            return
        # "uvicorn.error" passes its records to "uvicorn"; write a record once even if it reaches the handler twice.
        if getattr(record, "_vodloft_log_filed", False):
            return
        record._vodloft_log_filed = True
        super().emit(record)


def log_file_path() -> Path:
    return get_config_path().parent / "logs" / LOG_FILE_NAME


def configure_log_file(settings: AppSettings) -> None:
    """Start, stop or change the log file to match the settings."""
    global _handler
    options = settings.log_file
    path = log_file_path()
    level = getattr(logging, settings.log_level, logging.INFO)
    with _lock:
        current = _handler
        if current and options.enabled and Path(current.baseFilename) == path.resolve() \
                and current.maxBytes == options.max_megabytes * 1024 * 1024 \
                and current.backupCount == options.kept_files:
            current.setLevel(level)
            return
        if current:
            _detach(current)
            _handler = None
        if not options.enabled:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = _LogFileHandler(
                path,
                maxBytes=options.max_megabytes * 1024 * 1024,
                backupCount=options.kept_files,
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not open the log file %s: %s", path, exc)
            return
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(_FORMAT))
        for name in ("", *_UVICORN_LOGGERS):
            logging.getLogger(name).addHandler(handler)
        _handler = handler


def _detach(handler: logging.Handler) -> None:
    for name in ("", *_UVICORN_LOGGERS):
        logging.getLogger(name).removeHandler(handler)
    handler.close()
