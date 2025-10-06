# executor/audit/logger.py
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

DEFAULT_LEVEL = os.environ.get("CORTEX_LOG_LEVEL", "INFO").upper()
_LOG_DIR = Path(".executor") / "logs"
_LOG_FILE = _LOG_DIR / "cortex.log"

_INITIALIZED = False

def initialize_logging(level: str | int = DEFAULT_LEVEL) -> None:
    """
    Configure a root logger with console + rotating file handlers.
    Idempotent: safe to call multiple times.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.INFO))

    # Console
    ch = logging.StreamHandler()
    ch.setLevel(root.level)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))

    # Rotating file
    fh = RotatingFileHandler(_LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(root.level)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    root.addHandler(ch)
    root.addHandler(fh)
    _INITIALIZED = True

def get_logger(name: str) -> logging.Logger:
    if not _INITIALIZED:
        initialize_logging()
    return logging.getLogger(name)
