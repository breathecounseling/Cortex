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

def init_db() -> None:
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

def init_db_if_needed() -> None:
    try:
        init_db()
    except Exception as e:
        print("[InitDBError]", e)


# ---------------------------------------------------------------------------
# Fact storage and lookup
# ---------------------------------------------------------------------------

def save_fact(key: str, value: str) -> None:
    key, value = key.strip().lower(), value.strip()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM memory WHERE key = ?", (key,))
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
    print(f"[Memory] Saved: {key} = {value}")

def delete_fact(key: str) -> None:
    key = key.strip().lower()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM memory WHERE key = ?", (key,))
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
    init_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT key, value FROM memory").fetchall()
    conn.close()
    return {k: v for k, v in rows}


# ---------------------------------------------------------------------------
# Domain detection and focus management
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "location": ["live", "city", "state", "country", "visit", "travel", "trip"],
    "color": ["color", "shade", "hue"],
    "food": ["food", "dish", "meal", "eat", "snack"],
    "name": ["name", "called"],
}

def detect_domain(text: str) -> str:
    lowered = text.lower()
    for domain, words in DOMAIN_KEYWORDS.items():
        if any(w in lowered for w in words):
            return domain
    return "general"

def clear_last_focus_if_needed(text: str) -> None:
    """Automatically clear 'last_fact_query' if new input belongs to another domain."""
    domain = detect_domain(text)
    last_query = load_fact("last_fact_query")
    if not last_query:
        return
    if not any(word in last_query for word in DOMAIN_KEYWORDS.get(domain, [])):
        delete_fact("last_fact_query")
        print(f"[SemanticFocus] Cleared last focus ({last_query}) after domain switch → {domain}")


# ---------------------------------------------------------------------------
# Fact query logic
# ---------------------------------------------------------------------------

def handle_fact_query(text: str) -> Optional[str]:
    """
    Detect 'what is my X' / 'where do I X' patterns and return known fact if present.
    Saves last_fact_query for follow-up corrections.
    """
    lowered = text.lower().strip()
    domain = detect_domain(lowered)
    key_match = re.search(r"\b(?:my|the|our)\s+([\w\s]+)$", lowered) or re.search(r"\b(?:my|the|our)\s+([\w\s]+)\b", lowered)
    if not key_match:
        return None
    key = key_match.group(1).strip().lower()

    # Match against known facts
    facts = list_facts()
    for k, v in facts.items():
        if key in k or k in key:
            print(f"[FactQuery.Match] {k} → {v}")
            save_fact("last_fact_query", k)
            return v

    # If not found, store pending key for next declaration
    save_fact("last_fact_query", key)
    print(f"[FactQuery.Semantic] pending key={key}")
    return None


# ---------------------------------------------------------------------------
# Forget / correction
# ---------------------------------------------------------------------------

def update_or_delete_from_text(text: str) -> Dict[str, Any]:
    lowered = text.lower().strip()

    match = re.search(r"\b(forget|delete|remove|clear)\s+(my|the)\s+([\w\s]+)", lowered)
    if match:
        key = match.group(3).strip().lower()
        delete_fact(key)
        return {"action": "deleted", "key": key}

    if any(p in lowered for p in ("forget that", "remove it", "delete that", "clear it")):
        facts = list_facts()
        if facts:
            last_key = list(facts.keys())[-1]
            delete_fact(last_key)
            return {"action": "deleted", "key": last_key}
        return {"action": "none"}

    if "changed my mind" in lowered or "that's wrong" in lowered or "no, it's" in lowered:
        for k in list_facts().keys():
            if any(w in k for w in ["color", "location", "food"]):
                delete_fact(k)
                return {"action": "deleted", "key": k}
        return {"action": "deleted", "key": None}

    return {"action": "none"}


# ---------------------------------------------------------------------------
# Context memory
# ---------------------------------------------------------------------------

def remember_exchange(role: str, message: str, session: str = "default") -> None:
    try:
        init_db_if_needed()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (f"context:{session}:{role}", message))
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