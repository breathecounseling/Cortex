from __future__ import annotations
from typing import Dict, Any

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember, recall

logger = get_logger(__name__)

def can_handle(intent: str) -> bool:
    # Legacy duplicate nomenclature — keep for backward compatibility
    return intent.lower().strip() in {"userpreferences", "user_prefs"}

def describe_capabilities() -> str:
    return "Stores and retrieves user preferences (legacy alias)."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    initialize_logging()
    init_db_if_needed()

    action = payload.get("action", "get")
    key = payload.get("key")
    value = payload.get("value")

    if action == "set" and key is not None:
        remember("preference", key, str(value), source="userpreferences", confidence=1.0)
        logger.info(f"[legacy] Preference set: {key}={value}")
        return {"status": "ok", "message": "Preference saved", "data": {"key": key, "value": value}}

    if action == "get" and key is not None:
        rows = recall(type="preference", key=key, limit=1)
        val = rows[0]["value"] if rows else None
        logger.info(f"[legacy] Preference get: {key} -> {val}")
        return {"status": "ok", "message": "Preference retrieved", "data": {"key": key, "value": val}}

    return {"status": "error", "message": "Invalid preference request"}