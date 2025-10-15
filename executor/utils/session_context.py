"""
executor/utils/session_context.py
---------------------------------
Persistent session context helpers for Echo:
- last fact (domain, key)
- last topic (topic string)
"""

from __future__ import annotations
import sqlite3, time
from pathlib import Path
from typing import Optional, Tuple

DB_PATH = Path("/data") / "memory.db"

def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def _init() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS session_context(
        session_id TEXT PRIMARY KEY,
        last_domain TEXT,
        last_key TEXT,
        last_topic TEXT,
        updated_at INTEGER
    )""")
    conn.commit(); conn.close()

def set_last_fact(session_id: str, domain: str, key: str) -> None:
    _init()
    conn = _connect(); c = conn.cursor()
    ts = int(time.time())
    c.execute("""INSERT INTO session_context(session_id,last_domain,last_key,last_topic,updated_at)
                 VALUES(?,?,?,?,?)
                 ON CONFLICT(session_id)
                 DO UPDATE SET last_domain=excluded.last_domain,
                               last_key=excluded.last_key,
                               updated_at=excluded.updated_at""",
              (session_id, domain, key, None, ts))
    conn.commit(); conn.close()

def get_last_fact(session_id: str) -> Tuple[Optional[str], Optional[str]]:
    _init()
    conn = _connect(); c = conn.cursor()
    c.execute("SELECT last_domain,last_key FROM session_context WHERE session_id=? LIMIT 1", (session_id,))
    row = c.fetchone(); conn.close()
    return (row[0], row[1]) if row else (None, None)

def set_topic(session_id: str, topic: str) -> None:
    _init()
    conn = _connect(); c = conn.cursor()
    ts = int(time.time())
    c.execute("""INSERT INTO session_context(session_id,last_domain,last_key,last_topic,updated_at)
                 VALUES(?,?,?,?,?)
                 ON CONFLICT(session_id)
                 DO UPDATE SET last_topic=excluded.last_topic,
                               updated_at=excluded.updated_at""",
              (session_id, None, None, topic.strip(), ts))
    conn.commit(); conn.close()

def get_topic(session_id: str) -> Optional[str]:
    _init()
    conn = _connect(); c = conn.cursor()
    c.execute("SELECT last_topic FROM session_context WHERE session_id=? LIMIT 1", (session_id,))
    row = c.fetchone(); conn.close()
    return row[0] if row and row[0] else None