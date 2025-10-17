"""
executor/utils/relationship_graph.py
------------------------------------
Phase 2.13 — Relational knowledge map

Stores pairwise associations like:
  (src_domain, src_item) --predicate--> (dst_domain, dst_item)

Examples:
  ('ui','cozy') --implies--> ('color','warm tones')
  ('food','seafood') --associated_with--> ('ui','coastal')

This is intentionally simple and append-only with an upsert that keeps a single
row per (src, predicate, dst).
"""

from __future__ import annotations
import sqlite3, time, os
from pathlib import Path
from typing import List, Dict, Optional, Tuple

DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)

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
        predicate  TEXT NOT NULL,   -- 'implies' | 'associated_with' | 'goes_with' | 'contrasts'
        dst_domain TEXT NOT NULL,
        dst_item   TEXT NOT NULL,
        weight     REAL DEFAULT 1.0,   -- simple ranking weight (0..1)
        confidence REAL DEFAULT 0.6,   -- model confidence (0..1)
        source     TEXT DEFAULT 'inference_engine',
        updated_at INTEGER NOT NULL
    )
    """)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_unique "
              "ON relationships(src_domain,src_item,predicate,dst_domain,dst_item)")
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

def list_relations(src_domain: Optional[str] = None,
                   src_item: Optional[str] = None,
                   predicate: Optional[str] = None) -> List[Dict]:
    init_relationships()
    conn = _connect(); c = conn.cursor()
    sql = "SELECT src_domain,src_item,predicate,dst_domain,dst_item,weight,confidence,updated_at FROM relationships WHERE 1=1"
    params: List = []
    if src_domain:
        sql += " AND src_domain=?"; params.append(src_domain)
    if src_item:
        sql += " AND src_item=?"; params.append(src_item)
    if predicate:
        sql += " AND predicate=?"; params.append(predicate)
    sql += " ORDER BY weight DESC, confidence DESC, updated_at DESC"
    c.execute(sql, tuple(params))
    rows = c.fetchall(); conn.close()
    return [{"src_domain":r[0], "src_item":r[1], "predicate":r[2],
             "dst_domain":r[3], "dst_item":r[4], "weight":float(r[5]),
             "confidence":float(r[6]), "updated_at":int(r[7])} for r in rows]

def related_for_item(item: str,
                     src_domain_hint: Optional[str] = None,
                     limit: int = 10) -> List[Dict]:
    """
    Find 'goes_with' or 'associated_with' for a given item (case-insensitive).
    """
    init_relationships()
    conn = _connect(); c = conn.cursor()
    if src_domain_hint:
        c.execute("""SELECT src_domain,src_item,predicate,dst_domain,dst_item,weight,confidence,updated_at
                     FROM relationships
                     WHERE LOWER(src_item)=LOWER(?) AND src_domain=?
                       AND predicate IN ('associated_with','goes_with')
                     ORDER BY weight DESC, confidence DESC, updated_at DESC
                     LIMIT ?""", (item, src_domain_hint, limit))
    else:
        c.execute("""SELECT src_domain,src_item,predicate,dst_domain,dst_item,weight,confidence,updated_at
                     FROM relationships
                     WHERE LOWER(src_item)=LOWER(?)
                       AND predicate IN ('associated_with','goes_with')
                     ORDER BY weight DESC, confidence DESC, updated_at DESC
                     LIMIT ?""", (item, limit))
    rows = c.fetchall(); conn.close()
    return [{"src_domain":r[0], "src_item":r[1], "predicate":r[2],
             "dst_domain":r[3], "dst_item":r[4], "weight":float(r[5]),
             "confidence":float(r[6]), "updated_at":int(r[7])} for r in rows]