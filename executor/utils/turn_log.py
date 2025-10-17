"""
executor/utils/turn_log.py
--------------------------
Persistent, indexed conversation log with simple keyword + semantic search.
"""

from __future__ import annotations
import sqlite3, re
from typing import List, Dict, Optional
from pathlib import Path

from executor.utils.time_utils import now_ts
# Reuse memory.db alongside graph
from executor.utils.memory_graph import DB_PATH

def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def _init() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS turn_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,           -- 'user' | 'assistant'
        text TEXT,
        topic TEXT,
        ts INTEGER,
        embedding BLOB NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_turnlog_sid_ts ON turn_log(session_id, ts)")
    conn.commit(); conn.close()

def log_turn(session_id: str, role: str, text: str, topic: Optional[str] = None) -> None:
    _init()
    conn = _connect(); c = conn.cursor()
    c.execute("INSERT INTO turn_log(session_id, role, text, topic, ts, embedding) VALUES (?,?,?,?,?,NULL)",
              (session_id, role, text or "", topic or "", now_ts()))
    conn.commit(); conn.close()

def search_turns_keyword(q: str, session_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    _init()
    q = (q or "").strip()
    conn = _connect(); c = conn.cursor()
    if session_id:
        c.execute("""SELECT session_id, role, text, topic, ts FROM turn_log
                     WHERE session_id=? AND text LIKE ?
                     ORDER BY ts DESC LIMIT ?""", (session_id, f"%{q}%", limit))
    else:
        c.execute("""SELECT session_id, role, text, topic, ts FROM turn_log
                     WHERE text LIKE ?
                     ORDER BY ts DESC LIMIT ?""", (f"%{q}%", limit))
    rows = c.fetchall(); conn.close()
    return [{"session_id": r[0], "role": r[1], "text": r[2], "topic": r[3], "ts": int(r[4])} for r in rows]

# Semantic search stub: use keyword for now; swap to vector search later.
def search_turns_semantic(q: str, session_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    # TODO: integrate embeddings + ANN index; for now fallback to keyword
    return search_turns_keyword(q, session_id=session_id, limit=limit)