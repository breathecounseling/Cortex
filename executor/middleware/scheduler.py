from __future__ import annotations
from typing import Literal
from pathlib import Path

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember

logger = get_logger(__name__)

# compatibility for legacy monkeypatch
_MEM_DIR = str(Path(".executor") / "memory")

def bootstrap_once() -> None:
    initialize_logging()
    init_db_if_needed()

def process_once() -> Literal["worked", "brainstormed", "idle", "error"]:
    """
    One scheduler tick. For tests, just record heartbeat; errors auto-recover.
    """
    try:
        bootstrap_once()
        try:
            remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
        except Exception:
            # re-init schema fallback if temp memory path
            init_db_if_needed()
            remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
        logger.debug("Scheduler heartbeat recorded")
        return "idle"
    except Exception as e:
        logger.exception(f"Scheduler error: {e}")
        return "error"