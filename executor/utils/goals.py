"""
executor/utils/goals.py
-----------------------
Phase 2.17 — Temporal Goals + Deadlines + Priority/Effort + Deletion
"""

from __future__ import annotations
import sqlite3, time, re
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
          priority INTEGER DEFAULT 2,
          effort_estimate TEXT DEFAULT 'medium',
          deadline TEXT,
          progress INTEGER DEFAULT 0,
          progress_note TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          last_active INTEGER NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_goals_session ON goals(session_id,status,last_active)")
        c.commit()

ensure_goals()

def migrate_goals_schema() -> None:
    """Adds missing columns if not yet present."""
    with _conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(goals)").fetchall()]
        add_cols = []
        if "priority" not in cols:
            add_cols.append(("priority", "INTEGER DEFAULT 2"))
        if "effort_estimate" not in cols:
            add_cols.append(("effort_estimate", "TEXT DEFAULT 'medium'"))
        if "deadline" not in cols:
            add_cols.append(("deadline", "TEXT"))
        if "progress" not in cols:
            add_cols.append(("progress", "INTEGER DEFAULT 0"))
        for col, defn in add_cols:
            try:
                c.execute(f"ALTER TABLE goals ADD COLUMN {col} {defn}")
                print(f"[Goals] Added column: {col}")
            except Exception as e:
                print(f"[Goals] Migration skipped {col}: {e}")
        c.commit()

migrate_goals_schema()

# ---------- CRUD ----------
def create_goal(session_id: str, title: str, topic: Optional[str]=None,
                priority: int=2, effort_estimate: str="medium",
                deadline: Optional[str]=None, note: str="") -> int:
    ts = _now()
    with _conn() as c:
        c.execute("""INSERT INTO goals(session_id,title,topic,status,priority,effort_estimate,deadline,
                     progress,progress_note,created_at,updated_at,last_active)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (session_id, title.strip(), (topic or "").strip(), "open",
                   int(priority), (effort_estimate or "medium").strip().lower(),
                   (deadline or ""), 0, note.strip(), ts, ts, ts))
        c.commit()
        gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"[Goals] Created #{gid}: {title}")
    return int(gid)

def update_goal(id_: int, **fields) -> None:
    if not fields: return
    sets, vals = [], []
    for k,v in fields.items():
        sets.append(f"{k}=?"); vals.append(v)
    sets.append("updated_at=?"); vals.append(_now())
    with _conn() as c:
        c.execute(f"UPDATE goals SET {', '.join(sets)} WHERE id=?", (*vals, id_))
        c.commit()

def pause_goal(id_: int) -> None:
    update_goal(id_, status="paused")

def close_goal(id_: int, note: str="") -> None:
    update_goal(id_, status="closed", progress_note=note)
    print(f"[Goals] Closed #{id_}")

def delete_goal(id_: int) -> None:
    """Hard-delete a goal record."""
    with _conn() as c:
        c.execute("DELETE FROM goals WHERE id=?", (id_,))
        c.commit()
    print(f"[Goals] Deleted #{id_}")

def set_deadline(id_: int, deadline: str) -> None:
    update_goal(id_, deadline=deadline)
    print(f"[Goals] Set deadline for #{id_} → {deadline}")

def touch_goal(id_: int, note: str="") -> None:
    with _conn() as c:
        c.execute("UPDATE goals SET last_active=?, updated_at=?, progress_note=COALESCE(?,progress_note) WHERE id=?",
                  (_now(), _now(), note if note else None, id_))
        c.commit()

def list_goals(session_id: str, status: Optional[str]=None, limit: int=50) -> List[Dict]:
    q = ("SELECT id,title,topic,status,priority,effort_estimate,deadline,progress,progress_note,"
         "created_at,updated_at,last_active FROM goals WHERE session_id=?")
    params = [session_id]
    if status:
        q += " AND status=?"; params.append(status)
    q += " ORDER BY (status='open') DESC, updated_at DESC LIMIT ?"; params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [{
        "id":r[0], "title":r[1], "topic":r[2], "status":r[3], "priority":r[4],
        "effort_estimate":r[5], "deadline":r[6], "progress":r[7], "note":r[8],
        "created_at":r[9], "updated_at":r[10], "last_active":r[11]
    } for r in rows]

def get_open_goals(session_id: str) -> List[Dict]:
    return list_goals(session_id, status="open", limit=200)

def get_most_recent_open(session_id: str) -> Optional[Dict]:
    with _conn() as c:
        r = c.execute("""SELECT id,title,topic,status,priority,effort_estimate,deadline,progress,last_active
                         FROM goals WHERE session_id=? AND status='open'
                         ORDER BY last_active DESC LIMIT 1""", (session_id,)).fetchone()
    if not r: return None
    return {"id":r[0], "title":r[1], "topic":r[2], "status":r[3],
            "priority":r[4], "effort_estimate":r[5], "deadline":r[6],
            "progress":r[7], "last_active":r[8]}

def find_goal_by_title(session_id: str, partial: str) -> Optional[Dict]:
    with _conn() as c:
        r = c.execute("""SELECT id,title,topic,status,priority,effort_estimate,deadline,progress,last_active
                         FROM goals WHERE session_id=? AND title LIKE ?
                         ORDER BY status='open' DESC, updated_at DESC LIMIT 1""",
                      (session_id, f"%{partial.strip()}%")).fetchone()
    if not r: return None
    return {"id":r[0], "title":r[1], "topic":r[2], "status":r[3],
            "priority":r[4], "effort_estimate":r[5], "deadline":r[6],
            "progress":r[7], "last_active":r[8]}

def mark_topic_active(session_id: str, topic: str) -> None:
    with _conn() as c:
        c.execute("""UPDATE goals SET last_active=?, updated_at=?
                     WHERE session_id=? AND status='open'
                     AND (topic=? OR title LIKE ?)""",
                  (_now(), _now(), session_id, topic, f"%{topic}%"))
        c.commit()

def list_sessions() -> List[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT session_id FROM goals").fetchall()
    return [r[0] for r in rows]

def stale_open_goals(session_id: str, older_than_s: int) -> List[Dict]:
    now = _now()
    return [g for g in get_open_goals(session_id)
            if now - int(g["last_active"]) >= older_than_s]

def due_soon_goals(session_id: str, within_days: int=3) -> List[Dict]:
    """Find goals due soon based on textual or ISO deadlines."""
    import datetime, dateutil.parser as dp
    res = []
    for g in get_open_goals(session_id):
        d = (g.get("deadline") or "").strip()
        if not d: continue
        try:
            dt = dp.parse(d, fuzzy=True)
            if 0 <= (dt.date() - datetime.date.today()).days <= within_days:
                res.append(g)
        except Exception:
            continue
    return res