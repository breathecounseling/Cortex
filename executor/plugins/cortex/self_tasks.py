from __future__ import annotations
from typing import Dict, Any

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember

logger = get_logger(__name__)

def can_handle(intent: str) -> bool:
    return intent.lower().strip() in {"cortex", "self_tasks"}

def describe_capabilities() -> str:
    return "Core self-optimization tasks (brainstorming, notes)."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    initialize_logging()
    init_db_if_needed()
    remember("system", "self_task", str(payload), source="cortex", confidence=0.8)
    logger.info("Self task recorded")
    return {"status": "ok", "message": "Self task processed"}