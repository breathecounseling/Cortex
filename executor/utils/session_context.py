"""
executor/utils/session_context.py
---------------------------------
Phase 2.20 — session context + tone + reminder interval + pending confirmations
"""

from __future__ import annotations
import sqlite3, json
from pathlib import Path
from typing import Optional, Tuple

DB_PATH = Path("/data/memory.db")

# ---------- DB helpers ----------
def _conn():
    c = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ensure_tables():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS session_context(
          session_id TEXT PRIMARY KEY,
          last_topic  TEXT,
          last_domain TEXT,
          last_key    TEXT,
          intimacy_level INTEGER DEFAULT 0,
          tone TEXT DEFAULT 'neutral',
          reminder_interval INTEGER DEFAULT 900,  -- 15 minutes default
          pending TEXT                             -- JSON payload for confirmations, e.g. {"action":"clear_goals","ts":...}
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS tone_map(
          domain TEXT,
          tone   TEXT,
          updated_at INTEGER
        )""")
        c.commit()

def _migrate_schema():
    with _conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(session_context)").fetchall()]
        adds = []
        if "tone" not in cols:
            adds.append(("tone", "TEXT DEFAULT 'neutral'"))
        if "reminder_interval" not in cols:
            adds.append(("reminder_interval", "INTEGER DEFAULT 900"))
        if "pending" not in cols:
            adds.append(("pending", "TEXT"))
        for col, defn in adds:
            try:
                c.execute(f"ALTER TABLE session_context ADD COLUMN {col} {defn}")
                print(f"[SessionContext] Added column: {col}")
            except Exception as e:
                print(f"[SessionContext] Migration skip {col}:", e)
        c.commit()

_ensure_tables()
_migrate_schema()

# ---------- Core setters/getters ----------
def set_last_fact(session_id: str, domain: str, key: str) -> None:
    with _conn() as c:
        c.execute("""
          INSERT INTO session_context(session_id,last_domain,last_key)
          VALUES(?,?,?)
          ON CONFLICT(session_id) DO UPDATE SET
            last_domain=excluded.last_domain,
            last_key=excluded.last_key
        """, (session_id, domain, key))
        c.commit()

def get_last_fact(session_id: str) -> Tuple[Optional[str], Optional[str]]:
    with _conn() as c:
        r = c.execute("SELECT last_domain,last_key FROM session_context WHERE session_id=?", (session_id,)).fetchone()
    if not r: return (None, None)
    return (r["last_domain"], r["last_key"])

def set_topic(session_id: str, topic: str) -> None:
    with _conn() as c:
        c.execute("""
          INSERT INTO session_context(session_id,last_topic)
          VALUES(?,?)
          ON CONFLICT(session_id) DO UPDATE SET last_topic=excluded.last_topic
        """, (session_id, topic))
        c.commit()

def get_topic(session_id: Optional[str]) -> Optional[str]:
    if not session_id: return None
    with _conn() as c:
        r = c.execute("SELECT last_topic FROM session_context WHERE session_id=?", (session_id,)).fetchone()
    return r["last_topic"] if r and r["last_topic"] else None

def set_intimacy(session_id: str, level: int) -> None:
    with _conn() as c:
        c.execute("""
          INSERT INTO session_context(session_id,intimacy_level)
          VALUES(?,?)
          ON CONFLICT(session_id) DO UPDATE SET intimacy_level=excluded.intimacy_level
        """, (session_id, level))
        c.commit()

def get_intimacy(session_id: str) -> int:
    with _conn() as c:
        r = c.execute("SELECT intimacy_level FROM session_context WHERE session_id=?", (session_id,)).fetchone()
    return int(r["intimacy_level"]) if r and r["intimacy_level"] is not None else 0

def set_tone(session_id: str, tone: str) -> None:
    with _conn() as c:
        c.execute("""
          INSERT INTO session_context(session_id,tone)
          VALUES(?,?)
          ON CONFLICT(session_id) DO UPDATE SET tone=excluded.tone
        """, (session_id, tone))
        c.commit()

def get_tone(session_id: Optional[str]) -> str:
    if not session_id: return "neutral"
    with _conn() as c:
        r = c.execute("SELECT tone FROM session_context WHERE session_id=?", (session_id,)).fetchone()
    return r["tone"] if r and r["tone"] else "neutral"

# ---------- Reminder interval ----------
def set_reminder_interval(session_id: str, seconds: int) -> None:
    with _conn() as c:
        c.execute("""
          INSERT INTO session_context(session_id,reminder_interval)
          VALUES(?,?)
          ON CONFLICT(session_id) DO UPDATE SET reminder_interval=excluded.reminder_interval
        """, (session_id, int(seconds)))
        c.commit()

def get_reminder_interval(session_id: Optional[str]) -> int:
    if not session_id: return 900
    with _conn() as c:
        r = c.execute("SELECT reminder_interval FROM session_context WHERE session_id=?", (session_id,)).fetchone()
    return int(r["reminder_interval"]) if r and r["reminder_interval"] is not None else 900

# ---------- Pending confirmation state ----------
def set_pending(session_id: str, payload: dict) -> None:
    with _conn() as c:
        c.execute("""
          INSERT INTO session_context(session_id,pending)
          VALUES(?,?)
          ON CONFLICT(session_id) DO UPDATE SET pending=excluded.pending
        """, (session_id, json.dumps(payload)))
        c.commit()

def get_pending(session_id: str) -> Optional[dict]:
    with _conn() as c:
        r = c.execute("SELECT pending FROM session_context WHERE session_id=?", (session_id,)).fetchone()
    if not r or not r["pending"]: return None
    try:
        return json.loads(r["pending"])
    except Exception:
        return None

def clear_pending(session_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE session_context SET pending=NULL WHERE session_id=?", (session_id,))
        c.commit()

# ---------- Domain tone (scaffold) ----------
def set_domain_tone(domain: str, tone: str, updated_at: int) -> None:
    with _conn() as c:
        c.execute("INSERT INTO tone_map(domain,tone,updated_at) VALUES(?,?,?)", (domain, tone, int(updated_at)))
        c.commit()

def get_domain_tone(domain: str) -> Optional[str]:
    with _conn() as c:
        r = c.execute("SELECT tone FROM tone_map WHERE domain=? ORDER BY updated_at DESC LIMIT 1", (domain,)).fetchone()
    return r["tone"] if r else None