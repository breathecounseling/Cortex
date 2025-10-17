"""
executor/utils/session_context.py
---------------------------------
Phase 2.13 — Adds persistent tone / personality tracking.
"""

import sqlite3
from typing import Optional

DB_PATH = "/data/memory.db"

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS session_context (
        session_id TEXT PRIMARY KEY,
        last_topic TEXT,
        last_domain TEXT,
        last_key TEXT,
        intimacy_level INTEGER DEFAULT 0,
        tone TEXT DEFAULT 'neutral'
    )""")
    conn.commit()
    return conn


def set_last_fact(session_id: str, domain: str, key: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO session_context (session_id,last_domain,last_key) VALUES (?,?,?)",
        (session_id, domain, key),
    )
    conn.commit(); conn.close()


def get_last_fact(session_id: str):
    conn = _get_conn()
    cur = conn.execute(
        "SELECT last_domain,last_key FROM session_context WHERE session_id=?",
        (session_id,),
    )
    row = cur.fetchone(); conn.close()
    return row if row else (None, None)


def set_topic(session_id: str, topic: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO session_context (session_id,last_topic) VALUES (?,?)",
        (session_id, topic),
    )
    conn.commit(); conn.close()


def get_topic(session_id: str) -> Optional[str]:
    conn = _get_conn()
    cur = conn.execute("SELECT last_topic FROM session_context WHERE session_id=?", (session_id,))
    row = cur.fetchone(); conn.close()
    return row[0] if row else None


def set_intimacy(session_id: str, level: int) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO session_context (session_id,intimacy_level) VALUES (?,?)",
        (session_id, level),
    )
    conn.commit(); conn.close()


def get_intimacy(session_id: str) -> int:
    conn = _get_conn()
    cur = conn.execute("SELECT intimacy_level FROM session_context WHERE session_id=?", (session_id,))
    row = cur.fetchone(); conn.close()
    return int(row[0]) if row and row[0] is not None else 0


# --- Tone / Personality persistence ---
def set_tone(session_id: str, tone: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO session_context (session_id,tone) VALUES (?,?)",
        (session_id, tone),
    )
    conn.commit(); conn.close()


def get_tone(session_id: str) -> str:
    conn = _get_conn()
    cur = conn.execute("SELECT tone FROM session_context WHERE session_id=?", (session_id,))
    row = cur.fetchone(); conn.close()
    return row[0] if row and row[0] else "neutral"