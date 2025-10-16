"""
executor/utils/turn_memory.py
-----------------------------
Short-term working memory (kept) + persistent turn logger (new hook).
"""

from __future__ import annotations
from typing import List, Dict
from executor.utils.turn_log import log_turn

_MAX_TURNS = 20
_memory: List[Dict] = []

def add_turn(role: str, content: str, session_id: str = "default") -> None:
    global _memory
    _memory.append({"role": role, "content": content, "session_id": session_id})
    if len(_memory) > _MAX_TURNS:
        _memory = _memory[-_MAX_TURNS:]
    # NEW: persist to turn_log
    try:
        log_turn(session_id=session_id, role=role, text=content)
    except Exception as e:
        print("[TurnLogError]", e)

def get_recent_turns(session_id: str = "default", limit: int = _MAX_TURNS) -> List[Dict]:
    return [t for t in _memory if t.get("session_id") == session_id][-limit:]

def clear_memory(session_id: str = "default") -> None:
    global _memory
    _memory = [t for t in _memory if t.get("session_id") != session_id]