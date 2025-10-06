from __future__ import annotations
import sqlite3
import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime

from executor.audit.logger import get_logger
from executor.utils.config import get_config, ensure_dirs

log = get_logger(__name__)
_conn_lock = threading.Lock()
_initialized = False

_EMBEDDED_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  session_id TEXT,
  type TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL DEFAULT 1.0,
  source TEXT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME,
  active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_facts_type_key ON facts(type, key);
CREATE INDEX IF NOT EXISTS idx_facts_user_session_time ON facts(user_id, session_id, timestamp DESC);
CREATE TABLE IF NOT EXISTS preferences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  category TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  origin_fact INTEGER REFERENCES facts(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_prefs_user_key ON preferences(user_id, key);
CREATE INDEX IF NOT EXISTS idx_prefs_category ON preferences(category);
CREATE TABLE IF NOT EXISTS repairs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  file TEXT NOT NULL,
  error TEXT NOT NULL,
  fix_summary TEXT,
  success INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_repairs_file_time ON repairs(file, created_at DESC);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  session TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conv_session_time ON conversations(session, timestamp DESC);
CREATE TABLE IF NOT EXISTS embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  vector BLOB NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_embed_fact ON embeddings(fact_id);
"""

def _connect() -> sqlite3.Connection:
    cfg = get_config()
    db_path = Path(cfg["MEMORY_DB_PATH"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _exec_script(conn: sqlite3.Connection, sql_text: str) -> None:
    conn.executescript(sql_text)
    conn.commit()

def _facts_table_exists(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False

def init_db_if_needed() -> None:
    """
    Ensure memory DB exists and schema is initialized.
    If schema file is missing OR DB exists but has no tables, use embedded schema.
    """
    global _initialized
    if _initialized:
        return
    ensure_dirs()
    cfg = get_config()
    db = Path(cfg["MEMORY_DB_PATH"])
    schema_path = Path(cfg["SCHEMA_INIT_SQL"])

    with _conn_lock, _connect() as conn:
        need_bootstrap = False
        if not db.exists():
            need_bootstrap = True
        else:
            # DB file exists — ensure required tables exist
            if not _facts_table_exists(conn):
                need_bootstrap = True

        if need_bootstrap:
            if schema_path.exists():
                _exec_script(conn, schema_path.read_text(encoding="utf-8"))
                log.info(f"Initialized memory DB from schema: {schema_path}")
            else:
                _exec_script(conn, _EMBEDDED_SCHEMA)
                log.info("Initialized memory DB from embedded schema")
    _initialized = True

def _append_jsonl(record: Dict[str, Any]) -> None:
    cfg = get_config()
    path = Path(cfg["MEMORY_LOG_JSONL"])
    line = json.dumps(record, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True
    )
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
    init_db_if_needed()
    with _conn_lock, _connect() as conn:
        conn.execute("UPDATE facts SET active=0 WHERE id=?", (fact_id,))
        conn.commit()
    _append_jsonl({"ts": datetime.utcnow().isoformat(timespec="seconds"), "event": "forget", "id": fact_id})

def record_repair(file: str, error: str, fix_summary: str, *, user_id: Optional[str] = None, success: bool = False) -> int:
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