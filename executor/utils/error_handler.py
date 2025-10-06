from __future__ import annotations
from typing import Callable, Any

from executor.audit.logger import get_logger
from executor.utils.memory import record_repair

logger = get_logger(__name__)

def handle_error(file: str, error: Exception, fix_hint: str | None = None) -> None:
    """
    Centralized error recording for self-healer integration.
    """
    logger.exception(f"Error in {file}: {error}")
    record_repair(file=file, error=str(error), fix_summary=fix_hint or "", success=False)