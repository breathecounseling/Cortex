from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path(__file__).parent / "memory.db"


def init_db():
    """Initialize SQLite DB if not exists."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY, key TEXT, value TEXT)"
    )
    conn.commit()
    conn.close()


def save_fact(key: str, value: str):
    """Save a simple key/value fact to memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def list_facts() -> Dict[str, str]:
    """Return all facts stored in memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM memory")
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows}


# ---------------------------------------------------------------------------
# PATCH START: backward compatibility helpers for legacy modules
# ---------------------------------------------------------------------------

def init_db_if_needed():
    """Backward-compatible wrapper to initialize memory DB."""
    try:
        init_db()
    except Exception:
        pass


def remember(*args, **kwargs):
    """
    Backward-compatible flexible memory writer.
    Accepts arbitrary args/kwargs for compatibility with old API calls like:
        remember("system", "task_added", "details", source="docket", confidence=1.0)
    """
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key = ":".join(str(a) for a in args if a is not None) or kwargs.get("key", "unknown")
    value = json.dumps(kwargs) if kwargs else ""
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def record_repair(*args, **kwargs):
    """
    Backward-compatible repair recorder.
    Supports calls like:
        record_repair(file="x", error="...", fix_summary="...", success=True)
    """
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key = "repair"
    value = json.dumps(kwargs if kwargs else {"args": args})
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# PATCH START: add recall_context for API compatibility
# ---------------------------------------------------------------------------

def recall_context(session: str = "default") -> str:
    """
    Retrieve stored context for a given session.
    Used by API/chat to prefill conversational memory.
    """
    try:
        init_db_if_needed()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key, value FROM memory WHERE key LIKE ?", (f"context:{session}%",))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return ""
        # Concatenate all stored values for this session
        context = "\n".join(f"{k}: {v}" for k, v in rows)
        return context
    except Exception as e:
        return f"[Memory recall error: {e}]"

# ---------------------------------------------------------------------------
# PATCH END
# ---------------------------------------------------------------------------


def load_fact(key: str) -> Optional[str]:
    """Retrieve a fact from memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM memory WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None