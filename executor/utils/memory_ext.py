from __future__ import annotations
from typing import Dict, Any
from executor.utils.memory import record_repair


def record_healer_event(event: Dict[str, Any]) -> None:
    """Alias for record_repair, used for richer repair logs."""
    record_repair(**event)