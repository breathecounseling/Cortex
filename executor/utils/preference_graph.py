"""
executor/utils/preference_graph.py
----------------------------------
Phase 2.12 — preference persistence and recall

Handles user likes/dislikes across domains (food, ui, color, etc.)
Now supports all-domain retrieval for inference engine.
"""

from __future__ import annotations
import sqlite3, time, os
from pathlib import Path
from typing import Optional, Dict, Any, List

DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)

# ---------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------
def _connect():
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def _now() -> int:
    return int(time.time())

def init_preferences() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS preferences(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        item TEXT NOT NULL,
        polarity INTEGER DEFAULT 0,
        strength REAL DEFAULT 0.5,
        source TEXT DEFAULT 'parser',
        updated_at INTEGER NOT NULL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_pref_domain_item ON preferences(domain,item)")
    conn.commit(); conn.close()

# ---------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------
def upsert_preference(domain: str, item: str, polarity: int,
                      strength: float = 0.8, source: str = "parser") -> None:
    """Insert or update a preference for a domain + item."""
    init_preferences()
    conn = _connect(); c = conn.cursor()
    ts = _now()
    c.execute("DELETE FROM preferences WHERE domain=? AND item=?", (domain, item))
    c.execute("""INSERT INTO preferences(domain,item,polarity,strength,source,updated_at)
                 VALUES (?,?,?,?,?,?)""",
              (domain.lower(), item.strip(), int(polarity),
               float(strength), source, ts))
    conn.commit(); conn.close()
    print(f"[Preferences] Upserted: {domain}.{item} polarity={polarity} strength={strength}")

def delete_preference(domain: str, item: str) -> None:
    init_preferences()
    conn = _connect(); c = conn.cursor()
    c.execute("DELETE FROM preferences WHERE domain=? AND item=?", (domain.lower(), item.strip()))
    conn.commit(); conn.close()
    print(f"[Preferences] Deleted: {domain}.{item}")

# ---------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------
def get_preferences(domain: Optional[str] = None,
                    min_strength: float = 0.0) -> List[Dict[str, Any]]:
    """
    Return preferences for a specific domain or all domains.
    If domain is None, returns all.
    """
    init_preferences()
    conn = _connect(); c = conn.cursor()

    if domain:
        c.execute("""
        SELECT domain,item,polarity,strength,updated_at
        FROM preferences
        WHERE domain=? AND strength>=?
        ORDER BY strength DESC, updated_at DESC
        """, (domain.lower(), float(min_strength)))
    else:
        c.execute("""
        SELECT domain,item,polarity,strength,updated_at
        FROM preferences
        WHERE strength>=?
        ORDER BY domain, strength DESC, updated_at DESC
        """, (float(min_strength),))

    rows = c.fetchall(); conn.close()
    return [{"domain": r[0], "item": r[1],
             "polarity": int(r[2]),
             "strength": float(r[3]),
             "updated_at": int(r[4])} for r in rows]

def get_dislikes(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """Convenience query for negative polarity preferences."""
    prefs = get_preferences(domain)
    return [p for p in prefs if p["polarity"] < 0]

def list_all_preferences() -> List[Dict[str, Any]]:
    """Alias for full-table dump (mainly for debugging or inference)."""
    return get_preferences(domain=None)

# ---------------------------------------------------------------------
# User-facing wrapper
# ---------------------------------------------------------------------
def record_preference(domain: str, item: str, polarity: int = 1,
                      strength: float = 0.8, source: str = "parser") -> None:
    """Public entrypoint used by main/chat to record a preference."""
    upsert_preference(domain, item, polarity, strength, source)