"""
executor/utils/goals.py
-----------------------
Phase 2.21 — Temporal Goals + Deadlines + Priority/Effort + Session support
"""

from __future__ import annotations
import sqlite3, time
from pathlib import Path
from typing import List, Dict, Optional

DB_PATH = Path("/data/memory.db")
def _now() -> int: return int(time.time())
def _conn(): return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

# ---------- Schema ----------
def ensure_goals() -> None:
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS goals(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          title TEXT NOT NULL,
          topic TEXT,
          status TEXT DEFAULT 'open',              -- open | paused | closed
          priority INTEGER DEFAULT 2,              -- 3 high | 2 med | 1 low
          effort_estimate TEXT DEFAULT 'medium',   -- small|medium|large
          deadline TEXT,                           -- ISO-ish or human string
          progress INTEGER DEFAULT 0,              -- 0..100
          progress_note TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          last_active INTEGER NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_goals_session ON goals(session_id,status,last_active)")
        c.commit()

ensure_goals()

# ---------- Migration ----------
def migrate_goals_schema() -> None:
    """Safely adds missing columns (priority, effort_estimate, deadline, progress) if they don't exist."""
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
            add_cols.append(("progress", "REAL DEFAULT 0.0"))
        for col, defn in add_cols:
            try:
                c.execute(f"ALTER TABLE goals ADD COLUMN {col} {defn}")
                print(f"[Goals] Added column: {col}")
            except Exception as e:
                print(f"[Goals] Column {col} migration failed:", e)
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

def set_deadline(id_: int, deadline: str) -> None:
    update_goal(id_, deadline=deadline)
    print(f"[Goals] Set deadline for #{id_} → {deadline}")

def touch_goal(id_: int, note: str="") -> None:
    with _conn() as c:
        c.execute("UPDATE goals SET last_active=?, updated_at=?, progress_note=COALESCE(?,progress_note) WHERE id=?",
                  (_now(), _now(), note if note else None, id_))
        c.commit()

def delete_goal(id_: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM goals WHERE id=?", (id_,))
        c.commit()
    print(f"[Goals] Deleted #{id_}")

# ---------- Queries ----------
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

def count_open_goals(session_id: str) -> int:
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) FROM goals WHERE session_id=? AND status='open'", (session_id,)).fetchone()
    return int(r[0] if r else 0)

def clear_all_goals(session_id: str) -> int:
    """Deletes all open goals for a given session."""
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) FROM goals WHERE session_id=? AND status='open'", (session_id,)).fetchone()
        count = int(r[0] if r else 0)
        c.execute("DELETE FROM goals WHERE session_id=? AND status='open'", (session_id,))
        c.commit()
    print(f"[Goals] Cleared {count} open goals for session {session_id}")
    return count

# ---------- Sessions ----------
def list_sessions() -> List[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT session_id FROM goals").fetchall()
    return [r[0] for r in rows]

# ---------- Helpers for scheduler & queries ----------
def _parse_deadline(d: str):
    import datetime
    try:
        import dateutil.parser as dp
        return dp.parse(d, fuzzy=True)
    except Exception:
        # last-ditch ISO attempt
        try:
            return datetime.datetime.fromisoformat(d)
        except Exception:
            return None

def due_within_days(session_id: str, days: int) -> List[Dict]:
    """Goals due within N days (including today)."""
    import datetime
    now = datetime.date.today()
    res = []
    for g in get_open_goals(session_id):
        d = (g.get("deadline") or "").strip()
        if not d: continue
        dt = _parse_deadline(d)
        if not dt: continue
        delta = (dt.date() - now).days
        if 0 <= delta <= days:
            res.append(g)
    return res

def due_soon_goals(session_id: str, within_days: int=3) -> List[Dict]:
    return due_within_days(session_id, within_days)

def overdue_goals(session_id: str) -> List[Dict]:
    """Goals with a deadline earlier than today."""
    import datetime
    now = datetime.date.today()
    res = []
    for g in get_open_goals(session_id):
        d = (g.get("deadline") or "").strip()
        if not d: continue
        dt = _parse_deadline(d)
        if not dt: continue
        if (dt.date() - now).days < 0:
            res.append(g)
    return res