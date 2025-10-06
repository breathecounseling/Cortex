# executor/utils/memory.py
from __future__ import annotations
import sqlite3
import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime

from executor.audit.logger import get_logger
from .config import get_config, ensure_dirs

log = get_logger(__name__)
_conn_lock = threading.Lock()
_initialized = False

def _connect() -> sqlite3.Connection:
    cfg = get_config()
    db_path = Path(cfg["MEMORY_DB_PATH"])
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _exec_script(conn: sqlite3.Connection, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()

def init_db_if_needed() -> None:
    """
    Ensure .executor/memory/memory.db exists and matches the init schema.
    Idempotent and thread-safe.
    """
    global _initialized
    if _initialized:
        return
    ensure_dirs()
    cfg = get_config()
    db = Path(cfg["MEMORY_DB_PATH"])
    sql = Path(cfg["SCHEMA_INIT_SQL"])
    if not db.exists():
        with _conn_lock:
            with _connect() as conn:
                if sql.exists():
                    _exec_script(conn, sql)
                    log.info(f"Initialized memory DB from schema: {sql}")
                else:
                    log.warning(f"Schema not found at {sql}; memory DB not initialized!")
    _initialized = True

def _append_jsonl(record: Dict[str, Any]) -> None:
    """
    Append a JSON record to the raw memory log for audit/rebuild.
    """
    cfg = get_config()
    path = Path(cfg["MEMORY_LOG_JSONL"])
    line = json.dumps(record, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def remember(
    type: str,
    key: str,
    value: str,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    confidence: float = 1.0,
    source: str = "system",
    expires_at: Optional[str] = None,
    active: int = 1,
) -> int:
    """
    Persist a fact to both SQLite and the JSONL log. Returns new fact id.
    """
    init_db_if_needed()
    rec = {
        "ts": datetime.utcnow().isoformat(timespec="seconds"),
        "event": "remember",
        "type": type,
        "key": key,
        "value": value,
        "user_id": user_id,
        "session_id": session_id,
        "confidence": confidence,
        "source": source,
        "expires_at": expires_at,
        "active": active,
    }
    _append_jsonl(rec)
    with _conn_lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO facts (user_id, session_id, type, key, value, confidence, source, expires_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, session_id, type, key, value, confidence, source, expires_at, active),
        )
        conn.commit()
        return int(cur.lastrowid)

def recall(
    *,
    type: Optional[str] = None,
    key: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 10,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    """
    Query facts with simple filters. Returns latest-first.
    """
    init_db_if_needed()
    where = ["1=1"]
    params: List[Any] = []
    if not include_inactive:
        where.append("active=1")
    if type:
        where.append("type=?"); params.append(type)
    if key:
        where.append("key=?"); params.append(key)
    if user_id:
        where.append("user_id=?"); params.append(user_id)
    if session_id:
        where.append("session_id=?"); params.append(session_id)
    sql = f"SELECT * FROM facts WHERE {' AND '.join(where)} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with _conn_lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def forget(fact_id: int) -> None:
    """
    Soft-delete a fact (active=0). Keeps audit trail in JSONL.
    """
    init_db_if_needed()
    with _conn_lock, _connect() as conn:
        conn.execute("UPDATE facts SET active=0 WHERE id=?", (fact_id,))
        conn.commit()
    _append_jsonl({"ts": datetime.utcnow().isoformat(timespec="seconds"), "event": "forget", "id": fact_id})

def record_repair(file: str, error: str, fix_summary: str, *, user_id: Optional[str] = None, success: bool = False) -> int:
    """
    Persist a self-healer repair record and audit log.
    """
    init_db_if_needed()
    _append_jsonl({
        "ts": datetime.utcnow().isoformat(timespec="seconds"),
        "event": "repair",
        "file": file,
        "error": error,
        "fix_summary": fix_summary,
        "success": bool(success),
        "user_id": user_id,
    })
    with _conn_lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO repairs (user_id, file, error, fix_summary, success) VALUES (?, ?, ?, ?, ?)",
            (user_id, file, error, fix_summary, 1 if success else 0),
        )
        conn.commit()
        return int(cur.lastrowid)

def log_conversation(session: str, role: str, content: str, *, user_id: Optional[str] = None) -> int:
    """
    Optional structured conversation logging (beyond existing JSONL).
    """
    init_db_if_needed()
    with _conn_lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, session, role, content) VALUES (?, ?, ?, ?)",
            (user_id, session, role, content),
        )
        conn.commit()
        return int(cur.lastrowid)

def export_json(tables: Iterable[str] = ("facts","preferences","repairs","conversations")) -> Dict[str, Any]:
    """
    Snapshot tables → JSON for manual sync/backups.
    """
    init_db_if_needed()
    out: Dict[str, Any] = {}
    with _conn_lock, _connect() as conn:
        for t in tables:
            try:
                out[t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
            except sqlite3.Error:
                out[t] = []
    return out

def import_json(snapshot: Dict[str, Any]) -> None:
    """
    Basic importer that inserts rows without de-dup (callers can pre-clean).
    """
    init_db_if_needed()
    with _conn_lock, _connect() as conn:
        for t, rows in snapshot.items():
            if not isinstance(rows, list):
                continue
            for r in rows:
                cols = ", ".join(r.keys())
                qs = ", ".join(["?"] * len(r))
                try:
                    conn.execute(f"INSERT INTO {t} ({cols}) VALUES ({qs})", tuple(r.values()))
                except sqlite3.Error:
                    # skip conflicts silently (simple strategy for now)
                    continue
        conn.commit()
