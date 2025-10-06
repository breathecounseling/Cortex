from __future__ import annotations
from typing import Literal

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember

logger = get_logger(__name__)

def bootstrap_once() -> None:
    initialize_logging()
    init_db_if_needed()

def process_once() -> Literal["worked", "brainstormed", "idle", "error"]:
    try:
        bootstrap_once()
        remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
        logger.debug("Scheduler heartbeat recorded")
        return "idle"
    except Exception as e:
        logger.exception(f"Scheduler error: {e}")
        return "error"