"""
executor/utils/session_context.py
---------------------------------
Session context management for Echo.
Handles topic, intimacy, and conversational tone (personality state).
Includes auto-migration for missing columns such as `tone`.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("/data/memory.db")

# ---------------------- Database helpers ----------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    """Ensure the session_context table exists."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_context (
                session_id TEXT PRIMARY KEY,
                last_topic TEXT,
                intimacy_level INTEGER DEFAULT 0,
                tone TEXT DEFAULT 'neutral'
            );
            """
        )
        conn.commit()


def ensure_tone_column():
    """
    Auto-migration: if the session_context table is missing the `tone` column,
    add it without dropping existing data.
    """
    with get_conn() as conn:
        cur = conn.execute("PRAGMA table_info(session_context)")
        columns = [row["name"] for row in cur.fetchall()]
        if "tone" not in columns:
            print("[SessionContext] Adding missing `tone` column …")
            conn.execute("ALTER TABLE session_context ADD COLUMN tone TEXT DEFAULT 'neutral';")
            conn.commit()


# Ensure the DB and tone column exist at import time
ensure_tables()
ensure_tone_column()


# ---------------------- Context operations ----------------------

def set_last_fact(session_id: str, domain: str, key: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO session_context (session_id, last_topic)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET last_topic=excluded.last_topic;
            """,
            (session_id, f"{domain}.{key}"),
        )
        conn.commit()


def get_last_fact(session_id: str):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT last_topic FROM session_context WHERE session_id=?", (session_id,)
        )
        row = cur.fetchone()
        if not row or not row["last_topic"]:
            return None, None
        parts = row["last_topic"].split(".", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def set_topic(session_id: str, topic: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO session_context (session_id, last_topic)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET last_topic=excluded.last_topic;
            """,
            (session_id, topic),
        )
        conn.commit()


def get_topic(session_id: str):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT last_topic FROM session_context WHERE session_id=?", (session_id,)
        )
        row = cur.fetchone()
        return row["last_topic"] if row else None


def set_intimacy(session_id: str, level: int):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO session_context (session_id, intimacy_level)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET intimacy_level=excluded.intimacy_level;
            """,
            (session_id, level),
        )
        conn.commit()


def get_intimacy(session_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT intimacy_level FROM session_context WHERE session_id=?",
            (session_id,),
        )
        row = cur.fetchone()
        return int(row["intimacy_level"]) if row else 0


# ---------------------- Tone / personality ----------------------

def set_tone(session_id: str, tone: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO session_context (session_id, tone)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET tone=excluded.tone;
            """,
            (session_id, tone),
        )
        conn.commit()


def get_tone(session_id: str) -> str:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT tone FROM session_context WHERE session_id=?", (session_id,)
        )
        row = cur.fetchone()
        return row["tone"] if row and row["tone"] else "neutral"