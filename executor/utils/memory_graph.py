# executor/utils/memory_graph.py
from __future__ import annotations
import sqlite3, time, json, re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = Path("/data") / "memory.db"  # reuse same file for simplicity
print(f"[GraphDB] Using database at {DB_PATH}")

# -----------------------------
# DB init & helpers
# -----------------------------
def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix())

def init_graph() -> None:
    """Create graph tables if they don't exist. Lives alongside the 'memory' table."""
    conn = _connect()
    c = conn.cursor()
    # Nodes: (id, domain, key, scope, value, meta, created_at, updated_at)
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
    c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_dks ON graph_nodes(domain, nkey, scope)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_updated ON graph_nodes(updated_at)")

    # Edges: (id, src_id, dst_id, etype, meta, created_at)
    c.execute("""
    CREATE TABLE IF NOT EXISTS graph_edges(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        src_id INTEGER NOT NULL,
        dst_id INTEGER NOT NULL,
        etype TEXT NOT NULL,
        meta TEXT DEFAULT '{}',
        created_at INTEGER NOT NULL,
        FOREIGN KEY(src_id) REFERENCES graph_nodes(id) ON DELETE CASCADE,
        FOREIGN KEY(dst_id) REFERENCES graph_nodes(id) ON DELETE CASCADE
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(src_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges(dst_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(etype)")

    conn.commit()
    conn.close()

def _now() -> int:
    return int(time.time())

def _row_to_node(row: Tuple) -> Dict[str, Any]:
    id_, domain, nkey, scope, value, meta, created_at, updated_at = row
    meta_obj = {}
    try:
        meta_obj = json.loads(meta or "{}")
    except Exception:
        meta_obj = {}
    return {
        "id": id_,
        "domain": domain,
        "key": nkey,
        "scope": scope,
        "value": value,
        "meta": meta_obj,
        "created_at": created_at,
        "updated_at": updated_at,
    }

# -----------------------------
# Core graph API
# -----------------------------
def upsert_node(domain: str, key: str, value: str, scope: str = "global", meta: Optional[Dict[str, Any]] = None) -> int:
    """
    Create or update a node by (domain, key, scope). Returns node id.
    """
    init_graph()
    conn = _connect()
    c = conn.cursor()
    ts = _now()
    meta_json = json.dumps(meta or {})
    # Try update first
    c.execute("SELECT id FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?", (domain, key, scope))
    row = c.fetchone()
    if row:
        nid = row[0]
        c.execute("UPDATE graph_nodes SET value=?, meta=?, updated_at=? WHERE id=?", (value, meta_json, ts, nid))
        conn.commit()
        conn.close()
        print(f"[Graph] Updated node: ({domain}.{key}.{scope}) = {value}")
        return nid
    # Insert
    c.execute(
        "INSERT INTO graph_nodes(domain, nkey, scope, value, meta, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (domain, key, scope, value, meta_json, ts, ts)
    )
    nid = c.lastrowid
    conn.commit()
    conn.close()
    print(f"[Graph] Inserted node: ({domain}.{key}.{scope}) = {value}")
    return nid

def get_node(domain: str, key: str, scope: str = "global") -> Optional[Dict[str, Any]]:
    init_graph()
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, domain, nkey, scope, value, meta, created_at, updated_at FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?", (domain, key, scope))
    row = c.fetchone()
    conn.close()
    return _row_to_node(row) if row else None

def delete_node(domain: str, key: str, scope: str = "global") -> bool:
    init_graph()
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM graph_nodes WHERE domain=? AND nkey=? AND scope=?", (domain, key, scope))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    if changed:
        print(f"[Graph] Deleted node: ({domain}.{key}.{scope})")
    return changed

def link_nodes(src_id: int, dst_id: int, etype: str, meta: Optional[Dict[str, Any]] = None) -> int:
    init_graph()
    conn = _connect()
    c = conn.cursor()
    ts = _now()
    c.execute(
        "INSERT INTO graph_edges(src_id, dst_id, etype, meta, created_at) VALUES(?,?,?,?,?)",
        (src_id, dst_id, etype, json.dumps(meta or {}), ts)
    )
    eid = c.lastrowid
    conn.commit()
    conn.close()
    print(f"[Graph] Linked {src_id} -[{etype}]-> {dst_id}")
    return eid

def neighbors(node_id: int, etype: Optional[str] = None) -> List[Dict[str, Any]]:
    init_graph()
    conn = _connect()
    c = conn.cursor()
    if etype:
        c.execute("""
        SELECT g.id, g.domain, g.nkey, g.scope, g.value, g.meta, g.created_at, g.updated_at
        FROM graph_edges e
        JOIN graph_nodes g ON g.id = e.dst_id
        WHERE e.src_id=? AND e.etype=?
        """, (node_id, etype))
    else:
        c.execute("""
        SELECT g.id, g.domain, g.nkey, g.scope, g.value, g.meta, g.created_at, g.updated_at
        FROM graph_edges e
        JOIN graph_nodes g ON g.id = e.dst_id
        WHERE e.src_id=?
        """, (node_id,))
    rows = c.fetchall()
    conn.close()
    return [_row_to_node(r) for r in rows]

# -----------------------------
# Domain convenience (Location)
# -----------------------------
# Supported scopes for location: home, current, trip
_LOC_HOME_RX = re.compile(r"\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>.+)$", re.I)
_LOC_CURR_RX = re.compile(r"\b(i'?m\s+(in|at|staying\s+in|visiting)|i\s+am\s+(in|at))\s+(?P<city>.+)$", re.I)
_LOC_TRIP_RX = re.compile(r"\b(i'?m\s+planning\s+(a\s+)?trip\s+to|i\s+plan\s+to\s+go\s+to|i'?m\s+going\s+to)\s+(?P<city>.+)$", re.I)

def set_location_home(city: str) -> None:
    upsert_node("location", "home", city.strip(), scope="home")

def set_location_current(city: str) -> None:
    upsert_node("location", "current", city.strip(), scope="current")

def set_location_trip(city: str) -> None:
    upsert_node("location", "trip", city.strip(), scope="trip")

def clear_location_home() -> None:
    delete_node("location", "home", scope="home")

def clear_location_current() -> None:
    delete_node("location", "current", scope="current")

def clear_location_trip() -> None:
    delete_node("location", "trip", scope="trip")

def extract_and_save_location(text: str) -> Optional[str]:
    """
    Parse a freeform sentence into location {home|current|trip}, save node, return a confirmation string.
    """
    t = (text or "").strip()
    m = _LOC_HOME_RX.search(t)
    if m:
        city = m.group("city").strip().rstrip(".!?")
        set_location_home(city)
        return f"Got it — your home location is {city}."
    m = _LOC_CURR_RX.search(t)
    if m:
        city = m.group("city").strip().rstrip(".!?")
        set_location_current(city)
        return f"Got it — you're currently in {city}."
    m = _LOC_TRIP_RX.search(t)
    if m:
        city = m.group("city").strip().rstrip(".!?")
        set_location_trip(city)
        return f"Got it — your trip destination is {city}."
    return None

def answer_location_question(text: str) -> Optional[str]:
    """
    Route location-like questions to the right scope.
    Priority: trip > current > home.
    """
    q = re.sub(r"[?.!]+$", "", (text or "").lower().strip())  # normalize
    q = re.sub(r"\s+", " ", q)

    # --- TRIP questions first ---
    if any(p in q for p in [
        "where am i going",
        "trip destination",
        "where is my trip",
        "what's there",
        "what should i do there",
        "what is my trip destination",
        "where will i go"
    ]):
        t = get_node("location", "trip", scope="trip")
        if t and t.get("value"):
            return f"Your trip destination is {t['value']}."
        # fallback to current/home
        c = get_node("location", "current", scope="current")
        if c and c.get("value"):
            return f"You're currently in {c['value']}."
        h = get_node("location", "home", scope="home")
        if h and h.get("value"):
            return f"You live in {h['value']}."
        return "I don't have a trip destination yet."

    # --- CURRENT questions ---
    if any(p in q for p in [
        "where am i",
        "where am i now",
        "where am i visiting",
        "where am i staying",
        "current location",
    ]):
        c = get_node("location", "current", scope="current")
        if c and c.get("value"):
            return f"You're currently in {c['value']}."
        t = get_node("location", "trip", scope="trip")
        if t and t.get("value"):
            return f"You're preparing to go to {t['value']}."
        h = get_node("location", "home", scope="home")
        if h and h.get("value"):
            return f"You live in {h['value']}."
        return "I'm not sure where you are right now."

    # --- HOME questions ---
    if any(p in q for p in [
        "where do i live",
        "home location",
        "where is my home",
        "my home",
    ]):
        h = get_node("location", "home", scope="home")
        if h and h.get("value"):
            return f"You live in {h['value']}."
        return "I'm not sure where you live."

    # --- fallback: generic "where" ---
    if q.startswith("where"):
        c = get_node("location", "current", scope="current")
        if c and c.get("value"):
            return f"You're currently in {c['value']}."
        h = get_node("location", "home", scope="home")
        if h and h.get("value"):
            return f"You live in {h['value']}."
    return None

# -----------------------------
# Domain generic upsert/query
# -----------------------------
def upsert_fact(domain: str, key: str, value: str, scope: str = "global", meta: Optional[Dict[str, Any]] = None) -> None:
    upsert_node(domain, key, value, scope=scope, meta=meta or {})

def get_fact(domain: str, key: str, scope: str = "global") -> Optional[str]:
    n = get_node(domain, key, scope=scope)
    return n["value"] if n else None

def delete_fact_node(domain: str, key: str, scope: str = "global") -> bool:
    return delete_node(domain, key, scope=scope)

# -----------------------------
# Migration (optional, non-destructive)
# -----------------------------
def migrate_from_flat_memory(flat: Dict[str, str]) -> int:
    """
    Best-effort migration from flat memory facts (favorite color, location, current location, trip destination) to graph nodes.
    Returns count of migrated items.
    """
    count = 0
    try:
        for k, v in (flat or {}).items():
            kl = k.lower()
            if kl == "favorite color":
                upsert_node("color", "favorite", v, scope="global"); count += 1
            elif kl in ("location", "home location"):
                upsert_node("location", "home", v, scope="home"); count += 1
            elif kl == "current location":
                upsert_node("location", "current", v, scope="current"); count += 1
            elif kl == "trip destination":
                upsert_node("location", "trip", v, scope="trip"); count += 1
            elif kl == "favorite food":
                upsert_node("food", "favorite", v, scope="global"); count += 1
            # You can extend mapping here for more domains
    except Exception as e:
        print("[GraphMigrationError]", e)
    print(f"[GraphMigration] Migrated {count} items from flat memory.")
    return count