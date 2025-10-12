# executor/utils/memory.py
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, List

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "memory.db"


def init_db():
    """Initialize the SQLite memory database if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            value TEXT
        )"""
    )
    conn.commit()
    conn.close()


def init_db_if_needed():
    try:
        init_db()
    except Exception as e:
        print("[InitDBError]", e)


# ---------------------------------------------------------------------------
# Core fact storage helpers
# ---------------------------------------------------------------------------

def save_fact(key: str, value: str):
    """
    Save or update a simple key/value fact to memory.
    If a fact with the same key already exists, overwrite it.
    """
    key = key.strip().lower()
    value = value.strip()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key = ?", (key,))
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
    print(f"[Memory] Saved fact: {key} = {value}")


def delete_fact(key: str):
    """Delete a fact completely."""
    key = key.strip().lower()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    print(f"[Memory] Deleted fact: {key}")


def load_fact(key: str) -> Optional[str]:
    key = key.strip().lower()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM memory WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def list_facts() -> Dict[str, str]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM memory")
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows}


# ---------------------------------------------------------------------------
# Conversational helpers for corrections
# ---------------------------------------------------------------------------

def update_or_delete_from_text(text: str):
    """
    Lightweight NLP rules to detect corrections in plain language.
    Called automatically each turn before save_fact().
    """
    lowered = text.lower().strip()
    # Forget / remove
    if any(p in lowered for p in ("forget that", "remove it", "delete that")):
        # crude: forget last fact
        facts = list_facts()
        if facts:
            last_key = list(facts.keys())[-1]
            delete_fact(last_key)
            return {"action": "deleted", "key": last_key}
        return {"action": "none"}

    # "I changed my mind about my favorite color"
    if "changed my mind" in lowered or "no, that's wrong" in lowered:
        # extract a key hint if possible
        if "color" in lowered:
            delete_fact("favorite color")
            return {"action": "deleted", "key": "favorite color"}
        # add more patterns here as needed
        return {"action": "deleted", "key": None}

    return {"action": "none"}


# ---------------------------------------------------------------------------
# Backward-compatibility helpers (self-healer, repair logs)
# ---------------------------------------------------------------------------

def remember(*args, **kwargs):
    """Flexible legacy writer."""
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key = ":".join(str(a) for a in args if a is not None) or kwargs.get("key", "unknown")
    value = json.dumps(kwargs) if kwargs else ""
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def record_repair(*args, **kwargs):
    """Legacy support for self-healer logs."""
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key = "repair"
    value = json.dumps(kwargs if kwargs else {"args": args})
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Conversational context
# ---------------------------------------------------------------------------

def remember_exchange(role: str, message: str, session: str = "default") -> None:
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
        print(f"[MemoryError] failed to record exchange: {e}")


def recall_context(session: str = "default", limit: int = 6) -> List[Dict[str, str]]:
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, key, value FROM memory WHERE key LIKE ? ORDER BY id DESC LIMIT ?",
        (f"context:{session}:%", int(limit)),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return []

    messages: List[Dict[str, str]] = []
    for _id, key, value in reversed(rows):
        try:
            role = key.split(":", 2)[2]
        except Exception:
            role = "user"
        messages.append({"role": role, "content": value})
    return messages