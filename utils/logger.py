"""
Purpose: Centralized logging setup for the whole application.
"""
import logging
from datetime import datetime
from pathlib import Path

from utils.time import VN_TZ


class VietnamTimeFormatter(logging.Formatter):
    """Logging formatter that renders timestamps in Vietnam timezone."""

    def formatTime(self, record, datefmt=None):  # type: ignore[override]
        dt = datetime.fromtimestamp(record.created, tz=VN_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


def setup_logging(debug: bool = False, level: str | None = None) -> None:
    """Configure root logger once for consistent logs across modules."""
    if getattr(setup_logging, "_configured", False):
        return

    level_name = (level or ("DEBUG" if debug else "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    formatter = VietnamTimeFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stream handler for console
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # File handler for persistent logs
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "app.log")
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    setup_logging._configured = True