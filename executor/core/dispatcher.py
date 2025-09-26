"""
Dispatcher for Executor actions.

- Given an action {plugin, goal, status, args}
- Looks up the specialist in the Registry
- Calls specialist.handle(intent)
- Returns structured result {status, message, artifacts?, facts?}
"""

from typing import Dict, Any
from executor.core.registry import SpecialistRegistry


class Dispatcher:
    def __init__(self, registry: SpecialistRegistry | None = None):
        self.registry = registry or SpecialistRegistry()

    def dispatch(self, action: Dict[str, Any]) -> Dict[str, Any]:
        plugin = action.get("plugin")
        specialist = self.registry.get_specialist(plugin)
        if not specialist:
            return {
                "status": "error",
                "message": f"No specialist found for plugin={plugin}",
            }

        if hasattr(specialist, "can_handle") and not specialist.can_handle(action):
            return {
                "status": "skipped",
                "message": f"Specialist for {plugin} declined to handle {action.get('goal')}",
            }

        try:
            result = specialist.handle(action)
            if not isinstance(result, dict):
                raise ValueError("specialist.handle must return dict")
            return result
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {e}"}
