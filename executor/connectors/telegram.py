from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed

try:
    from telegram import Bot  # type: ignore
except Exception:  # pragma: no cover (optional dep)
    Bot = None  # graceful fallback

logger = get_logger(__name__)
OFFSET_FILE = Path(".executor") / "memory" / "telegram_offset.txt"

def _read_offset() -> Optional[int]:
    if not OFFSET_FILE.exists():
        return None
    try:
        text = OFFSET_FILE.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except Exception as e:
        logger.warning(f"Failed reading Telegram offset: {e}")
        return None

def _write_offset(update_id: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        OFFSET_FILE.write_text(str(update_id), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed writing Telegram offset: {e}")

def poll_updates(token: str) -> List[dict]:
    """
    Poll updates from Telegram safely. Returns a list of update dicts.
    """
    initialize_logging()
    init_db_if_needed()

    if Bot is None:
        logger.info("python-telegram-bot not installed; skipping poll")
        return []

    bot = Bot(token=token)
    offset = _read_offset()
    try:
        updates = bot.get_updates(offset=offset or 0, timeout=30)
        out = []
        max_id = offset or 0
        for u in updates:
            d = {"update_id": u.update_id, "message": getattr(u, "message", None)}
            out.append(d)
            if u.update_id > max_id:
                max_id = u.update_id
        if max_id:
            _write_offset(max_id + 1)
        return out
    except Exception as e:
        logger.exception(f"Telegram polling failed: {e}")
        return []