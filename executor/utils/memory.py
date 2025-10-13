from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, List
import re

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

DB_PATH = Path("/data") / "memory.db"
print(f"[MemoryDB] Using database at {DB_PATH}")

def init_db():
    """Initialize the SQLite memory database if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            value TEXT
        )
    """)
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
    """Save or update a simple key/value fact to memory."""
    if not key:
        return
    key = key.strip().lower()
    value = (value or "").strip()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key = ?", (key,))
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
    print(f"[Memory] Saved: {key} = {value}")

def delete_fact(key: str):
    """Delete a fact completely."""
    key = key.strip().lower()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    print(f"[Memory] Deleted: {key}")

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
    """Return all key/value facts stored in memory except ephemeral ones."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM memory")
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows if k not in {"last_fact_query"}}

# ---------------------------------------------------------------------------
# Conversational helpers for corrections
# ---------------------------------------------------------------------------

def update_or_delete_from_text(text: str) -> Dict[str, Any]:
    """
    Detect user requests to delete or correct facts.
    Supports general ('forget that') and targeted ('forget my location') forms.
    """
    lowered = (text or "").lower().strip()

    # Targeted forget/delete: "forget my location", "delete my favorite color"
    m = re.search(r"\b(forget|delete|remove|clear)\s+(my|the)\s+([\w\s]+)", lowered)
    if m:
        key = m.group(3).strip().lower()
        print(f"[MemoryDelete] Targeted delete for: {key}")
        try:
            delete_fact(key)
            return {"action": "deleted", "key": key}
        except Exception as e:
            print(f"[MemoryDeleteError] {e}")
            return {"action": "error", "key": key}

    # Generic forget phrases
    if any(p in lowered for p in ("forget that", "remove it", "delete that", "clear it")):
        facts = list_facts()
        if facts:
            last_key = list(facts.keys())[-1]
            delete_fact(last_key)
            return {"action": "deleted", "key": last_key}
        return {"action": "none"}

    # "I changed my mind" or "that's wrong"
    if "changed my mind" in lowered or "that's wrong" in lowered or "no, it's" in lowered:
        if "color" in lowered:
            delete_fact("favorite color")
            return {"action": "deleted", "key": "favorite color"}
        if "location" in lowered:
            delete_fact("location")
            return {"action": "deleted", "key": "location"}
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

    messages: List[Dict[str, str]] = []
    for _id, key, value in reversed(rows):
        role = "user"
        try:
            role = key.split(":", 2)[2]
        except Exception:
            pass
        messages.append({"role": role, "content": value})
    return messages