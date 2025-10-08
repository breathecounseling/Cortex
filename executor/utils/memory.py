# PATCH START: legacy compatibility layer

from pathlib import Path
import sqlite3

def init_db_if_needed():
    """Backward-compatible DB init for modules still calling the legacy memory API."""
    try:
        from executor.utils.memory import init_db  # reuse modern init if present
        init_db()
    except Exception:
        db_path = Path(__file__).parent / "memory.db"
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            "CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY, key TEXT, value TEXT)"
        )
        conn.commit()
        conn.close()

def remember(data: dict):
    """Record simple key/value data for context recall."""
    init_db_if_needed()
    db_path = Path(__file__).parent / "memory.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for k, v in data.items():
        c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()

def record_repair(file_path: str, patch_summary: str):
    """Persist repair actions for the self-healer."""
    init_db_if_needed()
    db_path = Path(__file__).parent / "memory.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memory (key, value) VALUES (?, ?)",
        (f"repair:{file_path}", patch_summary),
    )
    conn.commit()
    conn.close()

# PATCH END
