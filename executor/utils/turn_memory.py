"""
executor/utils/turn_memory.py
-----------------------------
Phase 2.19 — minimal turn log with get_recent_turns/add_turn helpers
"""

from __future__ import annotations
import sqlite3, time
from pathlib import Path
from typing import List, Dict

DB_PATH = Path("/data/memory.db")

def _conn():
    c = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ensure():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS turns(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT,
          role TEXT,                  -- 'user' | 'assistant'
          content TEXT,
          created_at INTEGER
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, created_at)")
        c.commit()

_ensure()

def add_turn(role: str, text: str, session_id: str = "default") -> None:
    with _conn() as c:
        c.execute("INSERT INTO turns(session_id,role,content,created_at) VALUES(?,?,?,?)",
                  (session_id, role, text, int(time.time())))
        c.commit()

def get_recent_turns(session_id: str = "default", limit: int = 8) -> List[Dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content as text, created_at FROM turns WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, int(limit))
        ).fetchall()
    return [{"role": r["role"], "text": r["text"], "created_at": int(r["created_at"])} for r in rows][::-1]