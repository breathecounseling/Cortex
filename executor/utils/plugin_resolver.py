from __future__ import annotations
from typing import Optional
from importlib import import_module

from executor.audit.logger import get_logger

logger = get_logger(__name__)

def resolve(path: str) -> Optional[object]:
    """
    Import a module by dotted path and return it, or None on failure.
    """
    try:
        return import_module(path)
    except Exception as e:
        logger.exception(f"Failed to import specialist: {path}: {e}")
        return None