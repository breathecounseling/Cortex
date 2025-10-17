"""
executor/utils/goals.py
-----------------------
Phase 2.13 — Temporal Goal Manager

Schema:
  goals(
    id INTEGER PK,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    topic TEXT,
    status TEXT DEFAULT 'open',   -- open | paused | closed
    progress_note TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_active INTEGER NOT NULL
  )
"""

from __future__ import annotations
import sqlite3, time
from pathlib import Path
from typing import List, Dict, Optional

DB_PATH = Path("/data/memory.db")

def _now() -> int: return int(time.time())
def _conn(): return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def ensure_goals() -> None:
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS goals(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          title TEXT NOT NULL,
          topic TEXT,
          status TEXT DEFAULT 'open',
          progress_note TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          last_active INTEGER NOT NULL
        )""")
        c.commit()

ensure_goals()

def create_goal(session_id: str, title: str, topic: Optional[str]=None, note: str="") -> int:
    ts = _now()
    with _conn() as c:
        c.execute("""INSERT INTO goals(session_id,title,topic,status,progress_note,created_at,updated_at,last_active)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (session_id, title.strip(), (topic or "").strip(), "open", note.strip(), ts, ts, ts))
        c.commit()
        gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"[Goals] Created #{gid}: {title}")
    return int(gid)

def touch_goal(goal_id: int, note: str="") -> None:
    ts = _now()
    with _conn() as c:
        c.execute("UPDATE goals SET last_active=?, updated_at=?, progress_note=COALESCE(?,progress_note) WHERE id=?",
                  (ts, ts, note if note else None, goal_id))
        c.commit()

def close_goal(goal_id: int, note: str="") -> None:
    ts = _now()
    with _conn() as c:
        c.execute("UPDATE goals SET status='closed', updated_at=?, progress_note=COALESCE(?,progress_note) WHERE id=?",
                  (ts, note if note else None, goal_id))
        c.commit()
    print(f"[Goals] Closed #{goal_id}")

def list_goals(session_id: str, status: Optional[str]=None, limit: int=20) -> List[Dict]:
    q = "SELECT id,title,topic,status,progress_note,created_at,updated_at,last_active FROM goals WHERE session_id=?"
    params = [session_id]
    if status:
        q += " AND status=?"; params.append(status)
    q += " ORDER BY (status='open') DESC, updated_at DESC LIMIT ?"; params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [{"id":r[0], "title":r[1], "topic":r[2], "status":r[3], "note":r[4],
             "created_at":r[5], "updated_at":r[6], "last_active":r[7]} for r in rows]

def get_most_recent_open(session_id: str) -> Optional[Dict]:
    with _conn() as c:
        r = c.execute("""SELECT id,title,topic,status,progress_note,last_active
                         FROM goals WHERE session_id=? AND status='open'
                         ORDER BY last_active DESC LIMIT 1""", (session_id,)).fetchone()
    if not r: return None
    return {"id":r[0], "title":r[1], "topic":r[2], "status":r[3], "note":r[4], "last_active":r[5]}

def mark_topic_active(session_id: str, topic: str) -> None:
    """When conversation returns to a topic, update its last_active if matching open goal exists."""
    with _conn() as c:
        c.execute("""UPDATE goals SET last_active=?, updated_at=? 
                     WHERE session_id=? AND status='open' AND (topic=? OR title LIKE ?)""",
                  (_now(), _now(), session_id, topic, f"%{topic}%"))
        c.commit()