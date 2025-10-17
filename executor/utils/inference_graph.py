"""
executor/utils/inference_graph.py
---------------------------------
Persistence layer for inferred preferences.
"""

import sqlite3, time, os
from pathlib import Path
from typing import Optional, Dict, Any, List

DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)

def _connect(): return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
def _now(): return int(time.time())

def init_inference():
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS inferred_preferences(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        item TEXT NOT NULL,
        polarity INTEGER DEFAULT 0,
        confidence REAL DEFAULT 0.5,
        source TEXT DEFAULT 'inference_engine',
        updated_at INTEGER NOT NULL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_infer_domain_item "
              "ON inferred_preferences(domain,item)")
    conn.commit(); conn.close()

def upsert_inferred_preference(domain: str, item: str,
                               polarity: int, confidence: float):
    init_inference()
    conn = _connect(); c = conn.cursor()
    ts = _now()
    c.execute("DELETE FROM inferred_preferences WHERE domain=? AND item=?",
              (domain, item))
    c.execute("""INSERT INTO inferred_preferences
                 (domain,item,polarity,confidence,updated_at)
                 VALUES (?,?,?,?,?)""",
              (domain, item, polarity, confidence, ts))
    conn.commit(); conn.close()

def list_inferred_preferences(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    init_inference()
    conn = _connect(); c = conn.cursor()
    if domain:
        c.execute("SELECT domain,item,polarity,confidence,updated_at "
                  "FROM inferred_preferences WHERE domain=?", (domain,))
    else:
        c.execute("SELECT domain,item,polarity,confidence,updated_at "
                  "FROM inferred_preferences")
    rows = c.fetchall(); conn.close()
    return [{"domain":r[0],"item":r[1],
             "polarity":r[2],"confidence":r[3],
             "updated_at":r[4]} for r in rows]