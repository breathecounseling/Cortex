from __future__ import annotations
from typing import Dict, Any

from executor.audit.logger import get_logger
from .registry import Registry

logger = get_logger(__name__)

class Dispatcher:
    """
    Simple dispatcher that calls specialist.handle(payload) if can_handle matches.
    """
    def __init__(self, registry: Registry | None = None):
        self.registry = registry or Registry()

    def dispatch(self, capability: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        specialist = self.registry.get_specialist_for(capability)
        if not specialist:
            msg = f"No specialist found for capability '{capability}'"
            logger.warning(msg)
            return {"status": "error", "message": msg}

        if hasattr(specialist, "can_handle") and not specialist.can_handle(capability):
            logger.debug(f"Specialist refuses capability '{capability}'")
            return {"status": "skip", "message": "Specialist declined"}

        if not hasattr(specialist, "handle"):
            msg = f"Specialist missing 'handle' for capability '{capability}'"
            logger.error(msg)
            return {"status": "error", "message": msg}

        return specialist.handle(payload or {})