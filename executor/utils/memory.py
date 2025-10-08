# executor/utils/memory.py
from __future__ import annotations
import os, sqlite3, time
from typing import List, Dict, Any

# Use Fly volume if available, otherwise fallback to local path
DB_PATH = (
    "/data/memory.db"
    if os.path.exists("/data")
    else os.path.join(os.path.dirname(__file__), "..", "memory.db")
)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def _connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db_if_needed() -> None:
    """Initialize the memory database if not yet created."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()

def remember_exchange(role: str, text: str) -> None:
    """Store a message (user or assistant) in persistent memory."""
    init_db_if_needed()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO memory (role, content, created_at) VALUES (?, ?, ?)",
            (role, text, time.time()),
        )
        conn.commit()

def recall_context(limit: int = 6) -> List[Dict[str, Any]]:
    """Fetch the most recent N exchanges from memory."""
    init_db_if_needed()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM memory ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def clear_memory() -> None:
    """Erase all stored exchanges."""
    with _connect() as conn:
        conn.execute("DELETE FROM memory")
        conn.commit()