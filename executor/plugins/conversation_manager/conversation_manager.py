from __future__ import annotations
from pathlib import Path
import json
from typing import Dict, Any, List

from executor.audit.logger import get_logger

logger = get_logger(__name__)

# compatibility: tests monkeypatch this value
_MEM_DIR = str(Path(".executor") / "memory")

def _mem_path(name: str) -> Path:
    p = Path(_MEM_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p / name

def _read_json(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_json(p: Path, data: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_facts(session: str) -> Dict[str, Any]:
    data = _read_json(_mem_path("repl_facts.json"))
    return data.get(session, {})

def save_fact(session: str, key: str, value: Any) -> None:
    data = _read_json(_mem_path("repl_facts.json"))
    sess = data.setdefault(session, {})
    sess[key] = value
    _write_json(_mem_path("repl_facts.json"), data)

def handle_repl_turn(user_text: str, session: str = "default") -> Dict[str, Any]:
    text = (user_text or "").lower()
    if "favorite color is" in text:
        value = text.split("favorite color is", 1)[1].strip().strip(".")
        save_fact(session, "favorite_color", value)
        msg = f"Got it—I’ll remember that your favorite color is {value}."
    else:
        msg = "Ok."

    history: List[Dict[str, str]] = [
        {"role": "user", "content": user_text}
    ]
    return {"status": "ok", "messages": history, "message": msg}
