# executor/utils/session_context.py
from __future__ import annotations
import sqlite3, time
from pathlib import Path
from typing import Optional, Tuple

DB_PATH = Path("/data") / "memory.db"  # share the same DB volume

def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def init_session_context() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS session_context(
        session_id TEXT PRIMARY KEY,
        last_domain TEXT,
        last_key TEXT,
        updated_at INTEGER
    )""")
    conn.commit(); conn.close()

def set_last_fact(session_id: str, domain: str, key: str) -> None:
    init_session_context()
    ts = int(time.time())
    conn = _connect(); c = conn.cursor()
    c.execute("REPLACE INTO session_context(session_id,last_domain,last_key,updated_at) VALUES(?,?,?,?)",
              (session_id, domain, key, ts))
    conn.commit(); conn.close()

def get_last_fact(session_id: str) -> Tuple[Optional[str], Optional[str]]:
    init_session_context()
    conn = _connect(); c = conn.cursor()
    c.execute("SELECT last_domain,last_key FROM session_context WHERE session_id=? LIMIT 1", (session_id,))
    row = c.fetchone(); conn.close()
    return (row[0], row[1]) if row else (None, None)