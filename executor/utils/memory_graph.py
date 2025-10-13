from __future__ import annotations
import sqlite3, time, json, re, os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)
print(f"[GraphDB] Using database at {DB_PATH}")

# ---------------------------------------------------------------------
# DB INIT
# ---------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix())

def init_graph() -> None:
    conn = _connect(); c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS graph_nodes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        nkey TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'global',
        value TEXT NOT NULL,
        meta TEXT DEFAULT '{}',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_dks ON graph_nodes(domain,nkey,scope)")
    conn.commit(); conn.close()

def _now() -> int: return int(time.time())

def _row_to_node(row: Tuple) -> Dict[str, Any]:
    id_, domain, nkey, scope, value, meta, created_at, updated_at = row
    try:
        meta = json.loads(meta or "{}")
    except Exception:
        meta = {}
    return dict(id=id_, domain=domain, key=nkey, scope=scope,
                value=value, meta=meta, created_at=created_at, updated_at=updated_at)

# ---------------------------------------------------------------------
# CORE CRUD
# ---------------------------------------------------------------------
def upsert_node(domain: str, key: str, value: str, scope: str = "global",
                meta: Optional[Dict[str, Any]] = None) -> int:
    """Insert or overwrite node by (domain,key,scope)."""
    init_graph()
    conn = _connect(); c = conn.cursor()
    ts = _now()
    meta_json = json.dumps(meta or {})
    c.execute("DELETE FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?",
              (domain, key, scope))
    c.execute("""INSERT INTO graph_nodes(domain,nkey,scope,value,meta,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?)""",
              (domain, key, scope, value.strip(), meta_json, ts, ts))
    nid = c.lastrowid
    conn.commit(); conn.close()
    print(f"[Graph] Upsert node: ({domain}.{key}.{scope}) = {value}")
    return nid

def get_node(domain: str, key: str, scope: str = "global") -> Optional[Dict[str, Any]]:
    init_graph()
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT id,domain,nkey,scope,value,meta,created_at,updated_at
                 FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?
                 ORDER BY updated_at DESC LIMIT 1""", (domain, key, scope))
    row = c.fetchone(); conn.close()
    return _row_to_node(row) if row else None

def delete_node(domain: str, key: str, scope: str = "global") -> bool:
    init_graph()
    conn = _connect(); c = conn.cursor()
    c.execute("DELETE FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?",
              (domain, key, scope))
    changed = c.rowcount > 0
    conn.commit(); conn.close()
    if changed:
        print(f"[Graph] Deleted node: ({domain}.{key}.{scope})")
    return changed

# ---------------------------------------------------------------------
# LOCATION LOGIC
# ---------------------------------------------------------------------
_LOC_HOME_RX = re.compile(r"\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>[\w\s,]+)", re.I)
_LOC_CURR_RX = re.compile(r"\b(i'?m\s+(in|at|staying\s+in|visiting)|i\s+am\s+(in|at))\s+(?P<city>[\w\s,]+)", re.I)
_LOC_TRIP_RX = re.compile(r"\b(i'?m\s+planning\s+(a\s+)?trip\s+to|i\s+plan\s+to\s+go\s+to|i'?m\s+going\s+to)\s+(?P<city>[\w\s,]+)", re.I)

def extract_and_save_location(text: str) -> Optional[str]:
    """Detect home/current/trip statements and overwrite cleanly."""
    t = (text or "").strip()
    m = _LOC_HOME_RX.search(t)
    if m:
        city = m.group("city").strip().rstrip(".!?")
        upsert_node("location","home",city,scope="home")
        return f"Got it — your home location is {city}."
    m = _LOC_CURR_RX.search(t)
    if m:
        city = m.group("city").strip().rstrip(".!?")
        upsert_node("location","current",city,scope="current")
        return f"Got it — you're currently in {city}."
    m = _LOC_TRIP_RX.search(t)
    if m:
        city = m.group("city").strip().rstrip(".!?")
        upsert_node("location","trip",city,scope="trip")
        return f"Got it — your trip destination is {city}."
    return None

def answer_location_question(text: str) -> Optional[str]:
    """Answer location questions with priority: trip>current>home."""
    q = re.sub(r"[?.!]+$","",(text or "").lower().strip())
    q = re.sub(r"\s+"," ",q)

    if any(p in q for p in ["where am i going","trip destination","where is my trip","what is my trip destination","where will i go","where am i traveling"]):
        t=get_node("location","trip","trip")
        if t and t.get("value"): return f"Your trip destination is {t['value']}."
        return "I don't have a trip destination yet."

    if any(p in q for p in ["where am i","where am i now","where am i visiting","where am i staying","current location"]):
        c=get_node("location","current","current")
        if c and c.get("value"): return f"You're currently in {c['value']}."
        return "I'm not sure where you are right now."

    if any(p in q for p in ["where do i live","home location","where is my home","my home"]):
        h=get_node("location","home","home")
        if h and h.get("value"): return f"You live in {h['value']}."
        return "I'm not sure where you live."
    return None

# ---------------------------------------------------------------------
# FACT / COLOR / FOOD DOMAINS
# ---------------------------------------------------------------------
_FACT_DECL_RX = re.compile(r"\bmy\s+(?P<key>[\w\s]+?)\s+(?:is|was|=|'s)\s+(?P<val>[^.?!]+)", re.I)
_CHANGE_RX = re.compile(r"\b(i\s+changed\s+my\s+mind\s+about|no,\s*it's|actually\s+it's)\s+(?P<key>[\w\s]+)", re.I)

def extract_and_save_fact(text: str) -> Optional[str]:
    """Detect general fact statements like 'my favorite color is blue' and overwrite."""
    t = (text or "").strip()
    m = _FACT_DECL_RX.search(t)
    if m:
        key = m.group("key").strip().lower()
        val = m.group("val").strip().rstrip(".!?")
        # domain routing
        if "color" in key:
            upsert_node("color","favorite",val,scope="global")
            return f"Got it — your favorite color is {val}."
        if "food" in key:
            upsert_node("food","favorite",val,scope="global")
            return f"Got it — your favorite food is {val}."
        if "location" in key or "home" in key:
            upsert_node("location","home",val,scope="home")
            return f"Got it — your home location is {val}."
        upsert_node("misc",key,val,scope="global")
        return f"Got it — I'll remember your {key} is {val}."
    return None

def forget_fact_or_location(text: str) -> Optional[str]:
    """Handle forget/changed-mind semantics by domain."""
    t = (text or "").lower().strip()
    # changed mind
    m = _CHANGE_RX.search(t)
    if m:
        key = m.group("key").strip().lower()
        if "color" in key:
            delete_node("color","favorite","global"); return "Got it — I've forgotten your favorite color."
        if "food" in key:
            delete_node("food","favorite","global"); return "Got it — I've forgotten your favorite food."
        if "home" in key or "location" in key:
            delete_node("location","home","home"); return "Got it — I've forgotten your home location."
        return "Got it — I've cleared that information."

    # explicit forget
    if "forget my favorite color" in t or "forget color" in t:
        delete_node("color","favorite","global"); return "Got it — I've forgotten your favorite color."
    if "forget my favorite food" in t or "forget food" in t:
        delete_node("food","favorite","global"); return "Got it — I've forgotten your favorite food."
    if "forget where i live" in t or "forget home" in t:
        delete_node("location","home","home"); return "Got it — I've forgotten your home location."
    if "forget where i am" in t or "forget current location" in t:
        delete_node("location","current","current"); return "Got it — I've forgotten your current location."
    if "forget my trip" in t or "forget trip" in t:
        delete_node("location","trip","trip"); return "Got it — I've forgotten your trip."
    return None