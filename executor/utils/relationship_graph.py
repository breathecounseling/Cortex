"""
executor/utils/relationship_graph.py
------------------------------------
Handles associative relationships between preferences and domains.

2.13b patch:
- Fuzzy lookup for related_for_item()
- Normalization helper
- Adds relation explanation synthesis using shared tags/polarity
"""

from __future__ import annotations
import sqlite3, os, re, time
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)

def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def init_relations() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS relationships(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_domain TEXT,
            src_item TEXT,
            rel_type TEXT,
            tgt_domain TEXT,
            tgt_item TEXT,
            weight REAL,
            confidence REAL,
            created_at INTEGER
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_rel_src ON relationships(src_domain, src_item)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rel_tgt ON relationships(tgt_domain, tgt_item)")
    conn.commit(); conn.close()

def _now() -> int: return int(time.time())

def add_relationship(src_domain: str, src_item: str,
                     rel_type: str, tgt_domain: str, tgt_item: str,
                     weight: float = 1.0, confidence: float = 1.0) -> None:
    init_relations()
    conn = _connect(); c = conn.cursor()
    c.execute("""INSERT INTO relationships
                 (src_domain, src_item, rel_type, tgt_domain, tgt_item, weight, confidence, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
              (src_domain, src_item, rel_type, tgt_domain, tgt_item, weight, confidence, _now()))
    conn.commit(); conn.close()
    print(f"[Relations] {src_domain}.{src_item} --{rel_type}--> {tgt_domain}.{tgt_item} (w={weight}, c={confidence})")

def normalize_term(term: str) -> str:
    """Normalize item names for fuzzy lookup."""
    t = term.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    for suffix in [" layout", " layouts", " design", " designs", " theme", " themes"]:
        if t.endswith(suffix):
            t = t.replace(suffix, "")
    return t.strip()

def related_for_item(item: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return items associated with this one, using fuzzy matching."""
    init_relations()
    conn = _connect(); c = conn.cursor()
    norm = normalize_term(item)
    like_pattern = f"%{norm}%"
    c.execute("""
        SELECT src_domain, src_item, rel_type, tgt_domain, tgt_item, weight, confidence
        FROM relationships
        WHERE LOWER(src_item) LIKE LOWER(?) OR LOWER(src_item) LIKE LOWER(?)
        ORDER BY weight DESC, confidence DESC, created_at DESC
        LIMIT ?
    """, (like_pattern, norm, limit))
    rows = c.fetchall(); conn.close()
    return [
        {"src_domain": r[0], "src_item": r[1],
         "rel_type": r[2], "tgt_domain": r[3],
         "tgt_item": r[4], "weight": r[5], "confidence": r[6]}
        for r in rows
    ]

# --- Explanations ------------------------------------------------------

_DOMAIN_TRAITS = {
    "ui": {"tags": {"warm", "soft", "rounded", "minimal"}},
    "color": {"tags": {"warm", "natural", "earthy", "vibrant"}},
    "food": {"tags": {"rich", "comforting", "savory", "fresh"}},
}

def explain_relationship(src_domain: str, tgt_domain: str) -> str:
    """Provide a simple natural explanation based on domain overlaps."""
    src_tags = _DOMAIN_TRAITS.get(src_domain, {}).get("tags", set())
    tgt_tags = _DOMAIN_TRAITS.get(tgt_domain, {}).get("tags", set())
    common = src_tags.intersection(tgt_tags)
    if common:
        joined = ", ".join(sorted(common))
        return f"because both evoke {joined} qualities"
    # Fallback generic tone
    if src_domain == tgt_domain:
        return "because they share similar style and tone"
    return "because they complement each other in feel and purpose"