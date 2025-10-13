from __future__ import annotations
import json, re, sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, List

DB_PATH = Path("/data") / "memory.db"
print(f"[MemoryDB] Using database at {DB_PATH}")

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------
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
    try: init_db()
    except Exception as e: print("[InitDBError]", e)

# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
def save_fact(key: str, value: str):
    key, value = key.strip().lower(), value.strip()
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM memory WHERE key=?", (key,))
        c.execute("INSERT INTO memory (key,value) VALUES (?,?)", (key,value))
        conn.commit()
        conn.close()
        print(f"[Memory] Saved: {key}={value}")
    except Exception as e:
        print("[MemoryError save_fact]", e)

def delete_fact(key: str):
    key = key.strip().lower()
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM memory WHERE key=?", (key,))
        conn.commit(); conn.close()
        print(f"[Memory] Deleted: {key}")
    except Exception as e:
        print("[MemoryError delete_fact]", e)

def load_fact(key: str) -> Optional[str]:
    key = key.strip().lower()
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM memory WHERE key=?", (key,))
        row = c.fetchone(); conn.close()
        print(f"[MemoryLoad] {key} -> {row[0] if row else None}")
        return row[0] if row else None
    except Exception as e:
        print("[MemoryError load_fact]", e)
        return None

def list_facts() -> Dict[str,str]:
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key,value FROM memory")
        rows = c.fetchall(); conn.close()
        facts = {k:v for k,v in rows if not k.startswith("context:")}
        print(f"[MemoryDump] {json.dumps(facts,indent=2)}")
        return facts
    except Exception as e:
        print("[MemoryError list_facts]", e)
        return {}

# ---------------------------------------------------------------------------
# Forget / update
# ---------------------------------------------------------------------------
def update_or_delete_from_text(text: str):
    lowered = text.lower().strip()
    m = re.search(r"\b(forget|delete|remove|clear)\s+(my|the)\s+([\w\s]+)", lowered)
    if m:
        key = m.group(3).strip().lower()
        delete_fact(key)
        return {"action":"deleted","key":key}

    if any(p in lowered for p in ("forget that","remove it","delete that","clear it")):
        facts = list_facts()
        if facts:
            k = list(facts.keys())[-1]
            delete_fact(k)
            return {"action":"deleted","key":k}
    return {"action":"none"}

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def remember_exchange(role:str,message:str,session:str="default"):
    try:
        init_db()
        conn=sqlite3.connect(DB_PATH)
        c=conn.cursor()
        c.execute("INSERT INTO context(session,role,message) VALUES(?,?,?)",
                  (session,role,message))
        conn.commit(); conn.close()
    except Exception as e:
        print("[ContextError remember_exchange]",e)

def recall_context(session:str="default",limit:int=6)->List[Dict[str,str]]:
    init_db()
    conn=sqlite3.connect(DB_PATH)
    c=conn.cursor()
    c.execute("SELECT role,message FROM context WHERE session=? ORDER BY id DESC LIMIT ?",
              (session,int(limit)))
    rows=c.fetchall(); conn.close()
    return [{"role":r,"content":m} for r,m in reversed(rows)]