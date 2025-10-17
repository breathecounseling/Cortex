"""
executor/utils/memory_graph.py
------------------------------
Phase 2.11.1 — domain detection expanded for UI/food terms; full stable CRUD.
"""

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
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

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

def _now() -> int: 
    return int(time.time())

def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj)
    except Exception:
        return "{}"

def _row_to_node(row: Tuple) -> Dict[str, Any]:
    id_, domain, nkey, scope, value, meta, created_at, updated_at = row
    try:
        meta = json.loads(meta or "{}")
    except Exception:
        meta = {}
    return {
        "id": int(id_),
        "domain": domain,
        "key": nkey,
        "scope": scope,
        "value": value,
        "meta": meta,
        "created_at": int(created_at),
        "updated_at": int(updated_at),
    }

# ---------------------------------------------------------------------
# KEY NORMALIZATION
# ---------------------------------------------------------------------
def canonicalize_key(key: str) -> str:
    if not key:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", key).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned

# ---------------------------------------------------------------------
# CORE CRUD
# ---------------------------------------------------------------------
def upsert_node(domain: str, key: str, value: str, scope: str = "global",
                meta: Optional[Dict[str, Any]] = None) -> int:
    init_graph()
    conn = _connect(); c = conn.cursor()
    ts = _now()
    meta_json = _safe_json(meta or {})
    c.execute("DELETE FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?",
              (domain, key, scope))
    c.execute("""INSERT INTO graph_nodes(domain,nkey,scope,value,meta,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?)""",
              (domain, key, scope, value.strip(), meta_json, ts, ts))
    nid = c.lastrowid
    conn.commit(); conn.close()
    print(f"[Graph] Upsert node: ({domain}.{key}.{scope}) = {value}")
    return int(nid)

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
# HELPERS
# ---------------------------------------------------------------------
_DOMAIN_SCOPES = {
    "location": ["home", "current", "trip", "global"],
    "color": ["global"],
    "food": ["global"],
    "ui": ["global"],
}

def get_all_scopes_for_domain(domain: str) -> List[str]:
    return _DOMAIN_SCOPES.get(domain, ["global"])

# ---------------------------------------------------------------------
# AUTO-EXTENSIBLE DOMAIN DETECTION (expanded for UI/food)
# ---------------------------------------------------------------------
def detect_domain_from_key(key: str) -> str:
    """
    Infer or create a domain name dynamically from a fact key.
    Expanded rules so UI/layout/chart terms map to 'ui';
    single-ingredient nouns map to 'food'.
    """
    k = (key or "").lower().strip()

    # --- Food keywords (single items & cuisines) ---
    if any(word in k for word in [
        "food","cuisine","dish","meal",
        "seafood","broccoli","pasta","sushi",
        "pizza","oyster","oysters","gumbo","liver","anchovy","anchovies",
        "ramen","curry","taco","tacos","noodle","noodles"
    ]):
        return "food"

    # --- Color & palette ---
    if "color" in k or ("earth" in k and "tone" in k):
        return "color"

    # --- Location ---
    if "location" in k or "home" in k or "trip" in k or "city" in k:
        return "location"

    # --- Media/Project ---
    if "movie" in k or "film" in k:
        return "movie"
    if "song" in k or "music" in k:
        return "music"
    if "project" in k:
        return "project"

    # --- UI / visual language ---
    if any(token in k for token in [
        "ui","layout","palette","theme","rounded","corner",
        "donut","chart","charts","dashboard","typography","density","font"
    ]):
        return "ui"

    # fallback heuristic
    words = k.split()
    dom = "misc"
    if words:
        first = words[0]
        if first not in ("favorite", "my", "the", "a", "an"):
            dom = re.sub(r"[^a-z0-9_]+", "_", first)
    print(f"[Graph] Auto-created domain: {dom}")
    return dom or "misc"

# ---------------------------------------------------------------------
# NEGATION & TOPIC HELPERS
# ---------------------------------------------------------------------
def contains_negation(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"\b(not|no|never|nevermind)\b", text.lower()))

def extract_topic_intro(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b(.+)", text.strip())
    if m:
        return m.group(2).strip(" .!?")
    return None

# ---------------------------------------------------------------------
# LOCATION LOGIC
# ---------------------------------------------------------------------
_LOC_HOME_RX = re.compile(r"\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>[\w\s,]+)", re.I)
_LOC_CURR_RX = re.compile(r"\b(i'?m\s+(in|at|staying\s+in|visiting)|i\s+am\s+(in|at))\s+(?P<city>[\w\s,]+)", re.I)
_LOC_TRIP_RX = re.compile(r"\b(i'?m\s+planning\s+(a\s+)?trip\s+to|i\s+plan\s+to\s+go\s+to|i'?m\s+going\s+to)\s+(?P<city>[\w\s,]+)", re.I)

def extract_and_save_location(text: str) -> Optional[str]:
    t = (text or "").strip()
    for rx, (key, scope, msg) in [
        (_LOC_HOME_RX, ("home", "home", "your home location")),
        (_LOC_CURR_RX, ("current", "current", "you're currently in")),
        (_LOC_TRIP_RX, ("trip", "trip", "your trip destination")),
    ]:
        m = rx.search(t)
        if m:
            city = m.group("city").strip().rstrip(".!?")
            upsert_node("location", key, city, scope=scope)
            return f"Got it — {msg} is {city}."
    return None

def answer_location_question(text: str) -> Optional[str]:
    q = re.sub(r"[?.!]+$", "", (text or "").lower().strip())
    q = re.sub(r"\s+", " ", q)
    if any(p in q for p in ["where am i going", "trip destination", "where is my trip",
                            "what is my trip destination", "where will i go", "where am i traveling"]):
        t = get_node("location", "trip", "trip")
        if t: return f"Your trip destination is {t['value']}."
        return "I don't have a trip destination yet."
    if any(p in q for p in ["where am i", "where am i now", "where am i visiting",
                            "where am i staying", "current location"]):
        c = get_node("location", "current", "current")
        if c: return f"You're currently in {c['value']}."
        return "I'm not sure where you are right now."
    if any(p in q for p in ["where do i live", "home location", "where is my home", "my home"]):
        h = get_node("location", "home", "home")
        if h: return f"You live in {h['value']}."
        return "I'm not sure where you live."
    return None

# ---------------------------------------------------------------------
# FACTS
# ---------------------------------------------------------------------
_FACT_DECL_RX = re.compile(r"\bmy\s+(?P<key>[\w\s]+?)\s+(?:is|was|=|'s)\s+(?P<val>[^.?!]+)", re.I)
_CHANGE_RX = re.compile(r"\b(i\s+changed\s+my\s+mind\s+about|no,\s*it's|actually\s+it's)\s+(?P<key>[\w\s]+)", re.I)

def extract_and_save_fact(text: str) -> Optional[str]:
    m = _FACT_DECL_RX.search(text or "")
    if not m:
        return None
    key = m.group("key").strip().lower()
    val = m.group("val").strip().rstrip(".!?")
    dom = detect_domain_from_key(key)
    upsert_node(dom, key, val, scope="global")
    return f"Got it — your {key} is {val}."

def forget_fact_or_location(text: str) -> Optional[str]:
    t = (text or "").lower().strip()
    m = _CHANGE_RX.search(t)
    if m:
        key = m.group("key").strip().lower()
        dom = detect_domain_from_key(key)
        delete_node(dom, key, "global")
        return f"Got it — I've forgotten your {key}."
    if "forget my" in t or "forget the" in t:
        key = re.sub(r"forget\s+(my|the)\s+", "", t).strip()
        dom = detect_domain_from_key(key)
        delete_node(dom, key, "global")
        return f"Got it — I've forgotten your {key}."
    return None