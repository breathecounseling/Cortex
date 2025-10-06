from __future__ import annotations
from typing import Literal

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember
# expose for tests to monkeypatch
from executor.connectors.openai_client import OpenAIClient  # noqa: F401

logger = get_logger(__name__)

# compatibility constant for tests
_MEM_DIR = ".executor/memory"

def bootstrap_once() -> None:
    initialize_logging()
    init_db_if_needed()

def process_once() -> Literal["worked", "brainstormed", "idle", "error"]:
    bootstrap_once()
    try:
        remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
        return "brainstormed"
    except Exception:
        # ensure embedded schema fallback and retry once
        try:
            init_db_if_needed()
            remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
            return "brainstormed"
        except Exception as inner:
            logger.exception(f"Scheduler error: {inner}")
            return "error"