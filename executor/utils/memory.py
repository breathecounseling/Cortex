# executor/utils/memory.py
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, List

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

DB_PATH = Path("/data") / "memory.db"
print(f"[MemoryDB] Using database at {DB_PATH}")

def init_db():
    """Initialize the SQLite database for both facts and chat context."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Core fact table
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            value TEXT
        )
    """)

    # Chat context table (new)
    c.execute("""
        CREATE TABLE IF NOT EXISTS context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT,
            role TEXT,
            message TEXT
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
    """Save or update a simple key/value fact to memory, with verification."""
    key = key.strip().lower()
    value = value.strip()
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level="DEFERRED", timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM memory WHERE key = ?", (key,))
        c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        print(f"[Memory] ✅ Saved fact: {key} = {value}")

        verify = load_fact(key)
        if verify != value:
            print(f"[MemoryWarning] Fact '{key}' failed persistence check (got {verify})")
        else:
            print(f"[MemoryCheck] Verified persistence for '{key}'")
    except Exception as e:
        print(f"[MemoryError] save_fact failed: {e}")

def delete_fact(key: str):
    """Delete a fact completely."""
    key = key.strip().lower()
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level="DEFERRED", timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM memory WHERE key = ?", (key,))
        conn.commit()
        conn.close()
        print(f"[Memory] Deleted fact: {key}")
    except Exception as e:
        print(f"[MemoryError] delete_fact failed: {e}")

def load_fact(key: str) -> Optional[str]:
    """Retrieve one fact."""
    key = key.strip().lower()
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM memory WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[MemoryError] load_fact failed: {e}")
        return None

def list_facts() -> Dict[str, str]:
    """Return all key/value facts stored in memory."""
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level="DEFERRED", timeout=10)
        c = conn.cursor()
        c.execute("SELECT key, value FROM memory")
        rows = c.fetchall()
        conn.close()
        facts = {k: v for k, v in rows if not k.startswith("context:")}
        print(f"[MemoryDump] Current facts:\n{json.dumps(facts, indent=2)}")
        return facts
    except Exception as e:
        print(f"[MemoryError] list_facts failed: {e}")
        return {}

# ---------------------------------------------------------------------------
# Conversational helpers for corrections / deletions
# ---------------------------------------------------------------------------

def update_or_delete_from_text(text: str):
    """
    Detect user requests to delete or correct facts.
    Supports both general ("forget that") and targeted ("forget my location") forms.
    """
    lowered = text.lower().strip()

    # Targeted forget/delete
    if re.search(r"\b(forget|delete|remove|clear)\s+(my|the)\s+([\w\s]+)", lowered):
        match = re.search(r"\b(forget|delete|remove|clear)\s+(my|the)\s+([\w\s]+)", lowered)
        if match:
            key = match.group(3).strip().lower()
            print(f"[MemoryDelete] Targeted delete request for: {key}")
            try:
                delete_fact(key)
                return {"action": "deleted", "key": key}
            except Exception as e:
                print(f"[MemoryDeleteError] {e}")
                return {"action": "error", "key": key}

    # Generic forget
    if any(p in lowered for p in ("forget that", "remove it", "delete that", "clear it")):
        facts = list_facts()
        if facts:
            last_key = list(facts.keys())[-1]
            delete_fact(last_key)
            return {"action": "deleted", "key": last_key}
        return {"action": "none"}

    # "I changed my mind" / corrections
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
# Backward compatibility (self-healer / repair logs)
# ---------------------------------------------------------------------------

def remember(*args, **kwargs):
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key = ":".join(str(a) for a in args if a is not None) or kwargs.get("key", "unknown")
    value = json.dumps(kwargs) if kwargs else ""
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def record_repair(*args, **kwargs):
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key = "repair"
    value = json.dumps(kwargs if kwargs else {"args": args})
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Conversational context (now in its own table)
# ---------------------------------------------------------------------------

def remember_exchange(role: str, message: str, session: str = "default") -> None:
    """Record conversational turns in the context table."""
    try:
        init_db_if_needed()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO context (session, role, message) VALUES (?, ?, ?)",
            (session, role, message),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ContextError] failed to record exchange: {e}")

def recall_context(session: str = "default", limit: int = 6) -> List[Dict[str, str]]:
    """Retrieve the last N conversational exchanges."""
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, message FROM context WHERE session=? ORDER BY id DESC LIMIT ?",
        (session, int(limit)),
    )
    rows = c.fetchall()
    conn.close()
    if not rows:
        return []
    messages: List[Dict[str, str]] = []
    for role, msg in reversed(rows):
        messages.append({"role": role, "content": msg})
    return messages