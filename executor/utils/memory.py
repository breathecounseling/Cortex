from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "memory.db"


def init_db():
    """Initialize the SQLite memory database if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY, key TEXT, value TEXT)"
    )
    conn.commit()
    conn.close()


def init_db_if_needed():
    """Backward-compatible wrapper for older modules."""
    try:
        init_db()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core fact storage helpers
# ---------------------------------------------------------------------------

def save_fact(key: str, value: str):
    """Save a simple key/value fact to memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def load_fact(key: str) -> Optional[str]:
    """Retrieve a fact from memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM memory WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def list_facts() -> Dict[str, str]:
    """Return all key/value facts stored in memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM memory")
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows}


# ---------------------------------------------------------------------------
# Backward-compatibility helpers for legacy modules
# ---------------------------------------------------------------------------

def remember(*args, **kwargs):
    """
    Flexible memory writer used by multiple legacy modules.
    Accepts arbitrary args and kwargs such as:
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
    Backward-compatible repair recorder for the self-healer and patcher utils.
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
# Conversational context functions for API/chat integration
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
        context = "\n".join(f"{k}: {v}" for k, v in rows)
        return context
    except Exception as e:
        return f"[Memory recall error: {e}]"


def remember_exchange(role: str, message: str, session: str = "default"):
    """
    Store a conversational exchange (role + message) in memory.
    Used by the API/chat pipeline to log conversation history.
    """
    try:
        init_db_if_needed()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        key = f"context:{session}:{role}"
        value = message
        c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Memory error: failed to record exchange: {e}]")