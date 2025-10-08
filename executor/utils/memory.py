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

# PATCH START: broadened legacy compatibility for remember() and record_repair()

def remember(*args, **kwargs):
    """
    Backward-compatible memory writer.
    Accepts flexible args and keyword arguments such as:
    remember("system", "task_added", "details", source="docket", confidence=1.0)
    """
    init_db_if_needed()
    db_path = Path(__file__).parent / "memory.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Try to build a reasonable key/value record
    if args:
        key = ":".join(str(a) for a in args if a is not None)
    else:
        key = kwargs.get("key", "unknown")
    value = str({k: v for k, v in kwargs.items()})
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def record_repair(*args, **kwargs):
    """
    Backward-compatible repair recorder.
    Supports both legacy and new-style calls:
        record_repair(file="x", error="...", fix_summary="...", success=True)
        record_repair(path, summary)
    """
    init_db_if_needed()
    db_path = Path(__file__).parent / "memory.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    key = "repair"
    # unify summary fields
    value = str(kwargs if kwargs else args)
    c.execute("INSERT INTO memory (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# PATCH END


# PATCH END
