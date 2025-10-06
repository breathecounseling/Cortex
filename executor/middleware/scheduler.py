from __future__ import annotations
from typing import Literal

from executor.connectors.openai_client import OpenAIClient
from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember
from executor.utils.docket import Docket, Task

logger = get_logger(__name__)

_MEM_DIR = ".executor/memory"

def bootstrap_once() -> None:
    initialize_logging()
    init_db_if_needed()

def process_once() -> Literal["worked", "brainstormed", "idle", "error"]:
    bootstrap_once()
    try:
        remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
        print("Brainstormed an idea")
        Docket._GLOBAL_TASKS.append(Task("[idea] new brainstormed idea", status="todo"))
        return "brainstormed"
    except Exception:
        try:
            init_db_if_needed()
            remember("system", "scheduler_tick", "heartbeat", source="scheduler", confidence=1.0)
            print("Brainstormed an idea")
            Docket._GLOBAL_TASKS.append(Task("[idea] new brainstormed idea", status="todo"))
            return "brainstormed"
        except Exception as inner:
            logger.exception(f"Scheduler error: {inner}")
            return "error"