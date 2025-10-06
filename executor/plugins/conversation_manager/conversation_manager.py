from __future__ import annotations
from pathlib import Path
import json
from typing import Dict, Any, List

from executor.audit.logger import get_logger
from executor.utils.memory import remember, recall, init_db_if_needed

logger = get_logger(__name__)

MEM_DIR = Path(".executor") / "memory"
FACTS_FILE = MEM_DIR / "repl_facts.json"   # retained for compatibility

def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_facts(session: str) -> Dict[str, Any]:
    # Backward compatible: read local file
    data = _read_json(FACTS_FILE)
    return data.get(session, {})

def save_fact(session: str, key: str, value: Any) -> None:
    init_db_if_needed()
    # File for legacy/tools:
    data = _read_json(FACTS_FILE)
    sess = data.setdefault(session, {})
    sess[key] = value
    _write_json(FACTS_FILE, data)
    # DB for durability/query:
    try:
        remember("preference", key, str(value), session_id=session, source="conversation_manager", confidence=0.9)
    except Exception as e:
        logger.warning(f"Failed to persist fact to DB: {e}")

def handle_repl_turn(user_text: str, session: str = "default") -> Dict[str, Any]:
    """
    Very small NL handler that extracts a simple 'favorite color' fact
    (kept only for smoke tests). Real extraction is performed elsewhere.
    """
    text = (user_text or "").lower().strip()
    if "favorite color is" in text:
        value = text.split("favorite color is", 1)[1].strip().strip(".")
        save_fact(session, "favorite_color", value)
        msg = f"Got it — I'll remember your favorite color is {value}."
    else:
        msg = "Thanks! I'll note that."

    return {"status": "ok", "message": msg}