# executor/utils/memory.py
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, List

DB_PATH = Path("/data") / "memory.db"
print(f"[MemoryDB] Using database at {DB_PATH}")

EPHEMERAL_KEYS = {"last_fact_query"}

def init_db():
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

# Facts
def save_fact(key: str, value: str):
    if not key:
        return
    key = key.strip().lower()
    value = (value or "").strip()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key=?", (key,))
    c.execute("INSERT INTO memory (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()
    print(f"[Memory] Saved: {key} = {value}")

def delete_fact(key: str):
    key = key.strip().lower()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key=?", (key,))
    conn.commit()
    conn.close()
    print(f"[Memory] Deleted: {key}")

def load_fact(key: str) -> Optional[str]:
    key = key.strip().lower()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM memory WHERE key=?", (key,))
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
    return {k: v for k, v in rows if not k.startswith("context:")}

# Delete/correction helpers
def update_or_delete_from_text(text: str) -> Dict[str, Any]:
    """
    Detect "forget/delete/remove/clear my/the X" and generic forget-phrases.
    If a turn includes both forget and a new declaration, main.py will re-save afterwards.
    """
    lowered = (text or "").lower().strip()

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

    if any(p in lowered for p in ("forget that", "remove it", "delete that", "clear it")):
        facts = list_facts()
        facts = {k:v for k,v in facts.items() if k not in EPHEMERAL_KEYS}
        if facts:
            last_key = list(facts.keys())[-1]
            delete_fact(last_key)
            return {"action": "deleted", "key": last_key}
        return {"action": "none"}

    # Optional: explicit corrections shortcuts (kept minimal; semantic handler usually covers this)
    if "changed my mind" in lowered or "that's wrong" in lowered:
        # We don't guess the key here; main.py's semantic layer should set it.
        return {"action": "none"}

    return {"action": "none"}

# Context
def remember_exchange(role: str, message: str, session: str = "default") -> None:
    try:
        init_db_if_needed()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO memory (key, value) VALUES (?,?)", (f"context:{session}:{role}", message))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[MemoryError] failed to record exchange: {e}")

def recall_context(session: str = "default", limit: int = 8) -> List[Dict[str, str]]:
    init_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, key, value FROM memory WHERE key LIKE ? ORDER BY id DESC LIMIT ?",
              (f"context:{session}:%", int(limit)))
    rows = c.fetchall()
    conn.close()
    messages: List[Dict[str, str]] = []
    for _id, key, value in reversed(rows):
        try:
            role = key.split(":", 2)[2]
        except Exception:
            role = "user"
        messages.append({"role": role, "content": value})
    return messages