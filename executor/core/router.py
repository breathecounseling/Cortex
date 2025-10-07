from __future__ import annotations
from typing import Dict, Any

from executor.audit.logger import get_logger

logger = get_logger(__name__)

def route(assistant_message: str | Dict[str, Any]) -> Dict[str, Any]:
    """
    Extremely conservative router:
      - If dict with 'actions' present -> assumes normalized contract
      - Else treat as chat, return contract with a generic 'chat' action
    This preserves tests that expect structured outputs without the Router 'guessing'.
    """
    if isinstance(assistant_message, dict) and assistant_message.get("actions"):
        logger.debug("Router received structured contract")
        return assistant_message

    # Fallback: interpret as generic chat intent
    logger.debug("Router received free text; wrapping as chat action")
    return {
        "assistant_message": str(assistant_message),
        "actions": [{"type": "chat", "payload": {"text": str(assistant_message)}}],
        "tasks": [],
        "facts": [],
    }