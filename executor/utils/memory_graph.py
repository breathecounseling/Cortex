# executor/utils/memory_graph.py
from __future__ import annotations
import sqlite3, time, json, re, os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from executor.utils.sanitizer import sanitize_value

# ---------------------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------------------
DB_PATH = Path("/data") / "memory.db"
os.makedirs(DB_PATH.parent, exist_ok=True)
print(f"[GraphDB] Using database at {DB_PATH}")

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    try:
        # Better concurrency for readers+writes
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn

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
# KEY CANONICALIZATION
# ---------------------------------------------------------------------
def canonicalize_key(k: str | None) -> str | None:
    if not k:
        return k
    k = k.strip().lower()
    k = re.sub(r"[\s_]+", " ", k)
    return k.strip()

# ---------------------------------------------------------------------
# DB LOCK-RESILIENT COMMIT
# ---------------------------------------------------------------------
def _safe_commit(conn: sqlite3.Connection, retries: int = 4, delay: float = 0.12) -> None:
    for _ in range(retries):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(delay)
                continue
            raise
    raise sqlite3.OperationalError("database is locked (after retries)")

# ---------------------------------------------------------------------
# CORE CRUD
# ---------------------------------------------------------------------
def upsert_node(domain: str, key: str, value: str, scope: str = "global",
                meta: Optional[Dict[str, Any]] = None) -> int:
    """Insert or overwrite node by (domain,key,scope)."""
    init_graph()
    key = canonicalize_key(key) or key
    conn = _connect(); c = conn.cursor()
    ts = _now()
    meta_json = _safe_json(meta or {})
    c.execute("DELETE FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?",
              (domain, key, scope))
    c.execute("""INSERT INTO graph_nodes(domain,nkey,scope,value,meta,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?)""",
              (domain, key, scope, (value or "").strip(), meta_json, ts, ts))
    nid = c.lastrowid
    _safe_commit(conn); conn.close()
    print(f"[Graph] Upsert node: ({domain}.{key}.{scope}) = {value}")
    return int(nid)

def get_node(domain: str, key: str, scope: str = "global") -> Optional[Dict[str, Any]]:
    init_graph()
    key = canonicalize_key(key) or key
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT id,domain,nkey,scope,value,meta,created_at,updated_at
                 FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?
                 ORDER BY updated_at DESC LIMIT 1""", (domain, key, scope))
    row = c.fetchone(); conn.close()
    return _row_to_node(row) if row else None

def delete_node(domain: str, key: str, scope: str = "global") -> bool:
    init_graph()
    key = canonicalize_key(key) or key
    conn = _connect(); c = conn.cursor()
    c.execute("DELETE FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?",
              (domain, key, scope))
    changed = c.rowcount > 0
    _safe_commit(conn); conn.close()
    if changed:
        print(f"[Graph] Deleted node: ({domain}.{key}.{scope})")
    return changed

# ---------------------------------------------------------------------
# 2.9 REGEX ENHANCEMENTS (syntax helpers)
# ---------------------------------------------------------------------
_CLAUSE_SPLIT_RX = re.compile(r"\b(?:but|and|then|while)\b", re.I)
def split_clauses(text: str) -> List[str]:
    return [t.strip() for t in _CLAUSE_SPLIT_RX.split(text or "") if t.strip()]

# Non-greedy + look-ahead so we stop BEFORE “but/and/then/I’m/I am” or end
_LOC_HOME_RX = re.compile(
    r"\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>[A-Za-z\s]+?)(?=\s+(?:but|and|then|i'?m\b|i\s+am\b)|[.?!]|$)",
    re.I
)
_LOC_CURR_RX = re.compile(
    r"\b(i'?m\s+(?:in|at|staying\s+in|visiting)|i\s+am\s+(?:in|at))\s+(?P<city>[A-Za-z\s]+?)(?=\s+(?:but|and|then|i'?m\b|i\s+am\b)|[.?!]|$)",
    re.I
)
# Adverb-first variant: "I'm currently in Paris"
_LOC_CURR_RX_ALT = re.compile(
    r"\b(i'?m|i\s+am)\s+currently\s+(?:in|at|staying\s+in|visiting)\s+(?P<city>[A-Za-z\s]+?)(?=\s+(?:but|and|then|i'?m\b|i\s+am\b)|[.?!]|$)",
    re.I
)
_LOC_TRIP_RX = re.compile(
    r"\b(i'?m\s+(?:planning\s+(?:a\s+)?trip\s+to|going\s+to|heading\s+to)|trip\s+to)\s+(?P<city>[A-Za-z\s]+?)(?=\s+(?:but|and|then|i'?m\b|i\s+am\b)|[.?!]|$)",
    re.I
)

_NEGATION_RX = re.compile(r"\b(no|not|never)\b", re.I)
_TOPIC_INTRO_RX = re.compile(
    r"\b(?:let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\s+(?P<topic>[\w\s]+)",
    re.I
)

def contains_negation(text: str) -> bool:
    return bool(_NEGATION_RX.search(text or ""))

def extract_topic_intro(text: str) -> Optional[str]:
    m = _TOPIC_INTRO_RX.search(text or "")
    return m.group("topic").strip() if m else None

# ---------------------------------------------------------------------
# 2.8.x PATCHES — SCOPE-AWARE FORGET + IMPLICIT CHANGE
# ---------------------------------------------------------------------
_DOMAIN_SCOPES = {
    "location": ["home", "current", "trip", "global"],
    "color": ["global"],
    "food": ["global"],
}

def get_all_scopes_for_domain(domain: str) -> List[str]:
    return _DOMAIN_SCOPES.get(domain, ["global"])

def infer_location_key_and_scope(text: str) -> (Optional[str], Optional[str]):
    t = (text or "").lower()
    if "home" in t or "live" in t:
        return ("home", "home")
    if "current" in t or re.search(r"\bi['’]?m in\b|\bcurrently in\b", t):
        return ("current", "current")
    if "trip" in t or "going to" in t or "destination" in t:
        return ("trip", "trip")
    return (None, None)

def detect_implicit_change(text: str) -> Optional[Dict[str, str]]:
    t = (text or "").lower().strip()

    m = re.search(r"\b(?:moved|relocated)\s+to\s+(?P<city>[\w\s,]+)", t)
    if m:
        city = sanitize_value(m.group("city"))
        return {"domain": "location", "key": "home", "scope": "home", "value": city}

    if re.search(r"\bnew home\b", t):
        return {"domain": "location", "key": "home", "scope": "home"}

    m = re.search(r"\bi['’]?m\s+in\s+(?P<city>[\w\s,]+)", t)
    if m:
        city = sanitize_value(m.group("city"))
        return {"domain": "location", "key": "current", "scope": "current", "value": city}

    m = re.search(r"\b(?:going|heading|trip)\s+to\s+(?P<city>[\w\s,]+)", t)
    if m:
        city = sanitize_value(m.group("city"))
        return {"domain": "location", "key": "trip", "scope": "trip", "value": city}
    return None

# ---------------------------------------------------------------------
# AUTO-EXTENSIBLE DOMAIN DETECTION
# ---------------------------------------------------------------------
def detect_domain_from_key(key: str) -> str:
    k = (key or "").lower().strip()
    if not k: return "misc"
    if "food" in k or "drink" in k or "meal" in k: return "food"
    if "color" in k or "paint" in k or "shade" in k: return "color"
    if "location" in k or "home" in k or "trip" in k or "city" in k: return "location"
    dom = re.sub(r"[^a-z0-9_]+", "_", k.split()[0]) if k else "misc"
    print(f"[Graph] Auto-created domain: {dom}")
    return dom or "misc"

# ---------------------------------------------------------------------
# LOCATION LOGIC (clause-aware)
# ---------------------------------------------------------------------
def extract_and_save_location(text: str) -> Optional[str]:
    if not text: return None

    change = detect_implicit_change(text)
    if change and change.get("value"):
        upsert_node(change["domain"], change["key"], change["value"], scope=change["scope"])
        return f"Got it — your {change['key']} location is {change['value']}."

    for clause in split_clauses(text):
        t = clause.strip()
        for rx, (key, scope, msg) in [
            (_LOC_HOME_RX, ("home", "home", "your home location")),
            (_LOC_CURR_RX, ("current", "current", "you're currently in")),
            (_LOC_CURR_RX_ALT, ("current", "current", "you're currently in")),
            (_LOC_TRIP_RX, ("trip", "trip", "your trip destination")),
        ]:
            m = rx.search(t)
            if m:
                city = sanitize_value(m.group("city"))
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
    if any(p in q for p in ["where do i live", "home location",
                            "where is my home", "my home"]):
        h = get_node("location", "home", "home")
        if h: return f"You live in {h['value']}."
        return "I'm not sure where you live."
    return None

# ---------------------------------------------------------------------
# FACT / COLOR / FOOD / MISC
# ---------------------------------------------------------------------
_FACT_DECL_RX = re.compile(r"\bmy\s+(?P<key>[\w\s]+?)\s+(?:is|was|=|'s)\s+(?P<val>[^.?!]+)", re.I)
_CHANGE_RX = re.compile(
    r"(?:i\s+changed\s+my\s+mind[,.]?(?:\s*(?:about|on)?\s+(?P<key>[\w\s]+))?"
    r"|no[,.\s]*it'?s|actually[,.\s]*it'?s)"
    r"\s+(?P<val>[^.?!]+)",
    re.I,
)

def extract_and_save_fact(text: str) -> Optional[str]:
    if not text: return None

    m_change = _CHANGE_RX.search(text)
    if m_change:
        key = canonicalize_key((m_change.groupdict().get("key") or "").strip().lower())
        val = sanitize_value((m_change.groupdict().get("val") or "").strip().rstrip(".!?"))
        if key:
            dom = detect_domain_from_key(key)
        else:
            dom, key = _load_recent()
        scopes = get_all_scopes_for_domain(dom)
        for scope in scopes:
            delete_node(dom, key, scope)
        upsert_node(dom, key, val, scope=scopes[0])
        return f"Got it — your {key} is {val}."

    m = _FACT_DECL_RX.search(text)
    if not m:
        return None
    key = canonicalize_key(m.group("key").strip().lower())
    val = sanitize_value(m.group("val").strip().rstrip(".!?"))
    dom = detect_domain_from_key(key)
    upsert_node(dom, key, val, scope="global")
    return f"Got it — your {key} is {val}."

# ---------------------------------------------------------------------
# RECENT-UPSERT FALLBACK (legacy only)
# ---------------------------------------------------------------------
_CACHE_FILE = Path("/tmp/_cortex_recent_domain.json")

def _cache_recent(domain: str, key: str) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps({"domain": domain, "key": key}))
    except Exception:
        pass

def _load_recent() -> Tuple[str, str]:
    try:
        data = json.loads(_CACHE_FILE.read_text())
        dom = data.get("domain", "color")
        key = canonicalize_key(data.get("key", "favorite color")) or "favorite color"
        return dom, key
    except Exception:
        return ("color", "favorite color")

# ---------------------------------------------------------------------
# FORGET / CORRECTION
# ---------------------------------------------------------------------
def forget_fact_or_location(text: str) -> Optional[str]:
    t = (text or "").lower().strip()
    m = _CHANGE_RX.search(t)
    if m:
        key = canonicalize_key((m.groupdict().get("key") or "").strip().lower())
        val = (m.groupdict().get("val") or "").strip()
        dom = detect_domain_from_key(key or _load_recent()[0])
        scopes = get_all_scopes_for_domain(dom)
        for scope in scopes:
            delete_node(dom, key or _load_recent()[1], scope)
        if val:
            upsert_node(dom, key or _load_recent()[1], sanitize_value(val), scope=scopes[0])
            return f"Got it — your {key or _load_recent()[1]} is {val}."
        return f"Got it — I've updated your {key or 'fact'}."

    if "forget" in t:
        if any(w in t for w in ["trip", "home", "current", "city", "place", "location"]):
            dom = "location"
            key, scope = infer_location_key_and_scope(t)
            if key:
                delete_node(dom, key, scope)
                return f"Got it — I've forgotten your {key} location."
            for scope in get_all_scopes_for_domain(dom):
                delete_node(dom, "*", scope)
            return "Got it — I've cleared your saved locations."

        key = canonicalize_key(re.sub(r"forget\s+(my|the)\s+", "", t).strip())
        dom = detect_domain_from_key(key)
        for scope in get_all_scopes_for_domain(dom):
            delete_node(dom, key, scope)
        return f"Got it — I've forgotten your {key}."
    return None