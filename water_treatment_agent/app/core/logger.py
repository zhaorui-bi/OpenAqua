"""
Structured logging setup.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_LOG_FORMATTER = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_file_logging(log_path: Path, level: str = "INFO") -> None:
    """
    Attach a FileHandler to the root logger so every subsequent logger
    (app.agents.*, app.rag.*, etc.) writes to *log_path* in addition to
    stdout.

    Call once at the very start of a script before importing any agent.

    Parameters
    ----------
    log_path : Path
        Destination log file (parent directory must already exist).
    level : str
        Minimum log level to capture in the file (default "INFO").
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    # Avoid duplicate file handlers on repeated calls
    existing_files = [
        h for h in root.handlers if isinstance(h, logging.FileHandler)
    ]
    for h in existing_files:
        root.removeHandler(h)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(_LOG_FORMATTER)
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(file_handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """Return a configured logger for *name*."""
    from app.core.config import get_settings
    settings = get_settings()
    effective_level = level or settings.log_level

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_LOG_FORMATTER)
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, effective_level.upper(), logging.INFO))
    return logger
