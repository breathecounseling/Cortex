"""
executor/utils/preference_graph.py
----------------------------------
Weighted, graded preference store (+1 like / -1 dislike; 0..1 strength; optional clusters).
"""

from __future__ import annotations
import sqlite3
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from executor.utils.time_utils import now_ts
from executor.utils.memory_graph import DB_PATH

def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def _init() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS preferences(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        item TEXT NOT NULL,
        polarity INTEGER NOT NULL,   -- +1 like, -1 dislike
        strength REAL NOT NULL DEFAULT 0.7,
        cluster TEXT,
        source TEXT,
        updated_at INTEGER NOT NULL
    )""")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pref_unique ON preferences(domain, item)")
    conn.commit(); conn.close()

def record_preference(domain: str, item: str, polarity: int,
                      strength: float = 0.7,
                      cluster: Optional[str] = None,
                      source: str = "reasoner") -> None:
    _init()
    domain = (domain or "").strip().lower()
    item = (item or "").strip().lower()
    ts = now_ts()
    conn = _connect(); c = conn.cursor()
    # Upsert: prefer latest polarity/strength/source
    c.execute("""INSERT INTO preferences(domain,item,polarity,strength,cluster,source,updated_at)
                 VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT(domain,item)
                 DO UPDATE SET polarity=excluded.polarity,
                               strength=excluded.strength,
                               cluster=excluded.cluster,
                               source=excluded.source,
                               updated_at=excluded.updated_at""",
              (domain, item, int(polarity), float(strength), cluster, source, ts))
    conn.commit(); conn.close()

def get_preferences(domain: str, min_strength: float = 0.4) -> List[Dict]:
    _init()
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT domain,item,polarity,strength,cluster,source,updated_at
                 FROM preferences
                 WHERE domain=? AND strength>=?
                 ORDER BY strength DESC, updated_at DESC""", (domain.lower(), float(min_strength)))
    rows = c.fetchall(); conn.close()
    return [{"domain": r[0], "item": r[1], "polarity": int(r[2]), "strength": float(r[3]),
             "cluster": r[4], "source": r[5], "updated_at": int(r[6])} for r in rows]

def get_dislikes(domain: str) -> List[Dict]:
    _init()
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT domain,item,polarity,strength,cluster,source,updated_at
                 FROM preferences
                 WHERE domain=? AND polarity<0
                 ORDER BY updated_at DESC""", (domain.lower(),))
    rows = c.fetchall(); conn.close()
    return [{"domain": r[0], "item": r[1], "polarity": int(r[2]), "strength": float(r[3]),
             "cluster": r[4], "source": r[5], "updated_at": int(r[6])} for r in rows]

def infer_palette_from_prefs() -> Dict:
    """
    Derive a simple palette from color-related prefs. Placeholder:
    return neutral earth tones if any related cluster; swap with a learned palette later.
    """
    prefs = get_preferences("color", min_strength=0.0)
    has_earth = any(("earth" in p["item"] or "olive" in p["item"] or "burgundy" in p["item"]) for p in prefs)
    if has_earth:
        return {"palette": "earth_tones", "colors": ["#5B6A5B", "#8B5E5A", "#C2A383", "#283845"]}
    return {"palette": "default", "colors": ["#0EA5E9", "#22C55E", "#F97316", "#A78BFA"]}