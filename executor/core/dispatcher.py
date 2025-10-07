from __future__ import annotations
from typing import Any, Dict

from executor.audit.logger import get_logger
from executor.core.registry import Registry

logger = get_logger(__name__)

class Dispatcher:
    """
    Routes a single action dict to its corresponding specialist and executes it.
    """

    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()

    def dispatch(self, action: Dict[str, Any], payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Dispatch an action to the appropriate specialist.
        Tests call with one positional argument (the action dict),
        but payload is accepted for future expansion.
        """
        try:
            plugin = action.get("plugin")
            if not plugin:
                return {"status": "error", "message": "Missing plugin in action."}

            specialist = self.registry.get_specialist(plugin)
            if not specialist:
                return {"status": "error", "message": f"No specialist found for {plugin}"}

            handler = getattr(specialist, "handle", None)
            if not callable(handler):
                return {"status": "error", "message": f"Specialist {plugin} has no handle()"}

            args = action.get("args", {})
            result = handler(args if payload is None else payload)
            if not isinstance(result, dict):
                return {"status": "error", "message": "Handler did not return dict"}
            logger.info(f"Dispatched action for plugin {plugin}")
            return result
        except Exception as e:
            logger.exception(f"Dispatcher error: {e}")
            return {"status": "error", "message": str(e)}
