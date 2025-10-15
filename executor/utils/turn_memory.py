"""
executor/utils/turn_memory.py
---------------------------------
Turn Memory — short-term conversational buffer for Echo.

Purpose:
    • Log every user + assistant exchange with timestamps.
    • Retrieve the last N turns to provide context for reasoning.
    • (Optional) summarize or prune older entries to keep memory efficient.
"""

from __future__ import annotations
import json, time, os
from pathlib import Path
from typing import List, Dict, Optional

# Location for persisted turn log
TURN_FILE = Path("/data/turn_memory.json")
MAX_TURNS = 20  # number of recent turns to keep in rolling memory


def _load_turns() -> List[Dict[str, str]]:
    """Internal: Load all stored turns from disk."""
    if not TURN_FILE.exists():
        return []
    try:
        return json.loads(TURN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_turns(turns: List[Dict[str, str]]) -> None:
    """Internal: Write turns back to disk."""
    try:
        TURN_FILE.write_text(json.dumps(turns[-MAX_TURNS:], indent=2), encoding="utf-8")
    except Exception as e:
        print("[TurnMemorySaveError]", e)


def add_turn(role: str, content: str, session_id: Optional[str] = "default") -> None:
    """
    Append a new message to the rolling memory.
    role: 'user' or 'assistant'
    content: text message
    session_id: optional identifier for multi-session support
    """
    turns = _load_turns()
    turns.append({
        "role": role,
        "content": content.strip(),
        "session_id": session_id,
        "ts": int(time.time())
    })
    _save_turns(turns)


def get_recent_turns(limit: int = MAX_TURNS, session_id: Optional[str] = "default") -> List[Dict[str, str]]:
    """
    Retrieve the last N turns, optionally filtered by session.
    Returns newest → oldest (chronological).
    """
    turns = _load_turns()
    filtered = [t for t in turns if t.get("session_id") == session_id]
    return filtered[-limit:]


def get_recent_context_text(limit: int = MAX_TURNS, session_id: Optional[str] = "default") -> str:
    """
    Return the recent conversation as a plain text block for injection
    into GPT-5 prompts.
    """
    turns = get_recent_turns(limit=limit, session_id=session_id)
    lines = []
    for t in turns:
        who = "User" if t["role"] == "user" else "Echo"
        lines.append(f"{who}: {t['content']}")
    return "\n".join(lines)


def clear_turn_memory(session_id: Optional[str] = "default") -> None:
    """Clear stored turns for a specific session."""
    if not TURN_FILE.exists():
        return
    try:
        turns = _load_turns()
        turns = [t for t in turns if t.get("session_id") != session_id]
        _save_turns(turns)
    except Exception as e:
        print("[TurnMemoryClearError]", e)