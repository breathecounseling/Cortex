from __future__ import annotations
from typing import Any, Optional

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed

logger = get_logger(__name__)

try:
    from googleapiclient.discovery import build  # type: ignore
except Exception:  # pragma: no cover
    build = None

def make_sheets_client(credentials: Any) -> Optional[Any]:
    initialize_logging()
    init_db_if_needed()
    if build is None:
        logger.info("google-api-python-client not installed; returning None")
        return None
    try:
        return build("sheets", "v4", credentials=credentials)
    except Exception as e:
        logger.exception(f"Sheets client creation failed: {e}")
        return None