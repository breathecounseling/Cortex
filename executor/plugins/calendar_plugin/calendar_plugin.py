from __future__ import annotations
from typing import Dict, Any

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed

logger = get_logger(__name__)

def can_handle(intent: str) -> bool:
    return intent.lower().strip() in {"calendar", "schedule", "calendar_plugin"}

def describe_capabilities() -> str:
    return "Create and list calendar entries"

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    initialize_logging()
    init_db_if_needed()
    logger.info("Calendar handler invoked")
    return {"status": "ok", "message": "Calendar action processed", "data": payload}

# compatibility helper expected by tests
def run():
    return handle({})
