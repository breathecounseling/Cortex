"""
executor/utils/turn_memory.py
-----------------------------
Short-term working memory (in-process ring buffer)
+ compatibility shim for plugins that expect get_recent_context_text().
"""

from __future__ import annotations
from typing import List, Dict

_MAX_TURNS = 20
_memory: List[Dict] = []

def add_turn(role: str, content: str, session_id: str = "default") -> None:
    """Append a turn to the in-memory ring buffer (most recent first)."""
    global _memory
    _memory.append({"role": role, "content": content, "session_id": session_id})
    if len(_memory) > _MAX_TURNS:
        _memory = _memory[-_MAX_TURNS:]

    # Persist to turn_log if available (2.11+) without hard dependency
    try:
        from executor.utils.turn_log import log_turn  # lazy import
        log_turn(session_id=session_id, role=role, text=content)
    except Exception as e:
        # Safe to ignore in environments without turn_log
        if str(e):
            print("[TurnLogError]", e)

def get_recent_turns(session_id: str = "default", limit: int = _MAX_TURNS) -> List[Dict]:
    """Return recent turns for this session (oldest→newest within the slice)."""
    return [t for t in _memory if t.get("session_id") == session_id][-limit:]

def clear_memory(session_id: str = "default") -> None:
    """Drop in-process turns for a session (does not affect persistent logs)."""
    global _memory
    _memory = [t for t in _memory if t.get("session_id") != session_id]

# ------------------------------------------------------------------
# Compatibility shim for older plugins:
# Some plugins import get_recent_context_text() from turn_memory.
# Provide a stable implementation that renders the recent turns.
# ------------------------------------------------------------------
def get_recent_context_text(limit: int = _MAX_TURNS, session_id: str = "default") -> str:
    """
    Render recent conversation into a single text block:
      User: ...
      Echo: ...
    """
    turns = get_recent_turns(session_id=session_id, limit=limit)
    lines: List[str] = []
    for t in turns:
        who = "User" if t.get("role") == "user" else "Echo"
        lines.append(f"{who}: {t.get('content', '')}")
    return "\n".join(lines)