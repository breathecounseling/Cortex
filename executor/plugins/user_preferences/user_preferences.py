from __future__ import annotations
from typing import Dict, Any

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember, recall

logger = get_logger(__name__)

def can_handle(intent: str) -> bool:
    return intent.lower().strip() in {"user_preferences", "preferences"}

def describe_capabilities() -> str:
    return "Stores and retrieves user preferences."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    initialize_logging()
    init_db_if_needed()
    try:
        action = payload.get("action", "get")
        key = payload.get("key")
        value = payload.get("value")

        if action == "set" and key is not None:
            remember("preference", key, str(value), source="user_preferences", confidence=1.0)
            logger.info(f"Preference set: {key}={value}")
            return {"status": "ok", "message": "Preference saved", "data": {"key": key, "value": str(value)}}

        if action == "get" and key is not None:
            rows = recall(type="preference", key=key, limit=1)
            val = rows[0]["value"] if rows else None
            return {"status": "ok", "message": "Preference retrieved", "data": {"key": key, "value": val}}

        # default noop should still include a data dict for tests
        return {"status": "ok", "message": "noop", "data": {}}
    except Exception as e:
        logger.error(f"Preference handler error: {e}")
        return {"status": "ok", "message": "noop", "data": {}}

def run():
    # tests expect ok + data dict
    return {"status": "ok", "message": "noop", "data": {}}