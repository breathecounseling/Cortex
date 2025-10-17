"""
executor/utils/relationship_graph.py
------------------------------------
Phase 2.13c — Relational knowledge map with fuzzy lookup + explanations

Schema:
  relationships(
    id INTEGER PK,
    src_domain TEXT, src_item TEXT,
    predicate TEXT,                -- 'associated_with' | 'goes_with' | 'implies' | 'contrasts'
    dst_domain TEXT, dst_item TEXT,
    weight REAL, confidence REAL,
    source TEXT, updated_at INTEGER
  )
"""

from __future__ import annotations
import sqlite3, os, re, time
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)

# ---------------- DB helpers ----------------
def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def _now() -> int:
    return int(time.time())

def init_relationships() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
      CREATE TABLE IF NOT EXISTS relationships(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        src_domain TEXT NOT NULL,
        src_item   TEXT NOT NULL,
        predicate  TEXT NOT NULL,
        dst_domain TEXT NOT NULL,
        dst_item   TEXT NOT NULL,
        weight     REAL DEFAULT 1.0,
        confidence REAL DEFAULT 0.6,
        source     TEXT DEFAULT 'inference_engine',
        updated_at INTEGER NOT NULL
      )
    """)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_unique "
              "ON relationships(src_domain,src_item,predicate,dst_domain,dst_item)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rel_src ON relationships(src_domain, src_item)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rel_dst ON relationships(dst_domain, dst_item)")
    conn.commit(); conn.close()

def upsert_relationship(src_domain: str, src_item: str,
                        predicate: str,
                        dst_domain: str, dst_item: str,
                        weight: float = 1.0, confidence: float = 0.6,
                        source: str = "inference_engine") -> None:
    init_relationships()
    conn = _connect(); c = conn.cursor()
    ts = _now()
    c.execute("""DELETE FROM relationships
                 WHERE src_domain=? AND src_item=? AND predicate=? AND dst_domain=? AND dst_item=?""",
              (src_domain, src_item, predicate, dst_domain, dst_item))
    c.execute("""INSERT INTO relationships
                 (src_domain,src_item,predicate,dst_domain,dst_item,weight,confidence,source,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?)""",
              (src_domain, src_item, predicate, dst_domain, dst_item, float(weight), float(confidence), source, ts))
    conn.commit(); conn.close()
    print(f"[Relations] {src_domain}.{src_item} --{predicate}--> {dst_domain}.{dst_item} (w={weight}, c={confidence})")

# ---------------- Lookup helpers ----------------
def normalize_term(term: str) -> str:
    """Normalize item names for fuzzy lookup (e.g., 'cozy layouts' -> 'cozy')."""
    t = (term or "").lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    for suffix in [" layout", " layouts", " design", " designs", " theme", " themes"]:
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    return t.strip()

def related_for_item(item: str,
                     src_domain_hint: Optional[str] = None,
                     limit: int = 10) -> List[Dict[str, Any]]:
    """Fuzzy 'goes_with/associated_with' lookup for a given item."""
    init_relationships()
    conn = _connect(); c = conn.cursor()
    norm = normalize_term(item)
    like_pattern = f"%{norm}%"
    if src_domain_hint:
        c.execute("""
           SELECT src_domain,src_item,predicate,dst_domain,dst_item,weight,confidence,updated_at
           FROM relationships
           WHERE (LOWER(src_item) LIKE LOWER(?) OR LOWER(src_item)=LOWER(?))
             AND src_domain=?
             AND predicate IN ('associated_with','goes_with')
           ORDER BY weight DESC, confidence DESC, updated_at DESC
           LIMIT ?
        """, (like_pattern, norm, src_domain_hint, limit))
    else:
        c.execute("""
           SELECT src_domain,src_item,predicate,dst_domain,dst_item,weight,confidence,updated_at
           FROM relationships
           WHERE (LOWER(src_item) LIKE LOWER(?) OR LOWER(src_item)=LOWER(?))
             AND predicate IN ('associated_with','goes_with')
           ORDER BY weight DESC, confidence DESC, updated_at DESC
           LIMIT ?
        """, (like_pattern, norm, limit))
    rows = c.fetchall(); conn.close()
    return [{"src_domain":r[0], "src_item":r[1], "predicate":r[2],
             "dst_domain":r[3], "dst_item":r[4], "weight":float(r[5]),
             "confidence":float(r[6]), "updated_at":int(r[7])} for r in rows]

# ---------------- Domain traits + explanations ----------------
_DOMAIN_TRAITS: Dict[str, set[str]] = {
    "color": {"vivid", "calm", "warm", "cool", "earthy", "neutral", "natural"},
    "ui": {"minimal", "cozy", "modern", "rounded", "structured", "soft"},
    "food": {"comforting", "fresh", "rich", "light", "hearty"},
    "music": {"energetic", "soothing", "melancholic", "ambient", "uplifting"},
    "activity": {"creative", "reflective", "physical", "social"},
    "mood": {"uplifting", "calm", "grounded", "playful"},
    "weather": {"bright", "gloomy", "refreshing", "humid"},
    "personality": {"introverted", "curious", "grounded", "playful"},
}

def explain_relationship(src_domain: str, dst_domain: str) -> str:
    """Simple natural explanation based on overlapping domain traits."""
    src = _DOMAIN_TRAITS.get((src_domain or "").lower(), set())
    dst = _DOMAIN_TRAITS.get((dst_domain or "").lower(), set())
    common = src.intersection(dst)
    if common:
        joined = ", ".join(sorted(common))
        return f"because both evoke {joined} qualities"
    if src_domain == dst_domain:
        return "because they share a similar style and tone"
    return "because they complement each other in feel and purpose"