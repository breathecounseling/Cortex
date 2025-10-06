from __future__ import annotations
from pathlib import Path
from typing import Optional

from executor.audit.logger import get_logger
from executor.utils.memory import record_repair

logger = get_logger(__name__)

def write_patch(target: Path, new_content: str, *, summary: str = "") -> None:
    """
    Overwrite a file with new content (utf-8) and record a repair summary.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    if summary:
        record_repair(file=str(target), error="patched", fix_summary=summary, success=True)
    logger.info(f"Patched file: {target}")