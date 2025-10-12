from __future__ import annotations
import hashlib, json, sqlite3, time
from pathlib import Path
from typing import Optional, Tuple

CACHE_DB = Path(__file__).parent / "web_cache.db"
DEFAULT_TTL_SECONDS = 6 * 60 * 60  # 6 hours

def _init():
    conn = sqlite3.connect(CACHE_DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS cache(
        qhash TEXT PRIMARY KEY,
        provider TEXT,
        payload TEXT,
        created_at INTEGER
    )""")
    conn.commit(); conn.close()

def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def get(query: str) -> Optional[Tuple[str, dict]]:
    _init()
    qhash = _h(query.strip().lower())
    conn = sqlite3.connect(CACHE_DB); c = conn.cursor()
    c.execute("SELECT provider, payload, created_at FROM cache WHERE qhash=?", (qhash,))
    row = c.fetchone(); conn.close()
    if not row: return None
    provider, payload, created_at = row
    # TTL check
    if int(time.time()) - int(created_at) > DEFAULT_TTL_SECONDS:
        return None
    try:
        return provider, json.loads(payload)
    except Exception:
        return None

def put(query: str, provider: str, payload: dict) -> None:
    _init()
    qhash = _h(query.strip().lower())
    conn = sqlite3.connect(CACHE_DB); c = conn.cursor()
    c.execute("REPLACE INTO cache(qhash, provider, payload, created_at) VALUES (?,?,?,?)",
              (qhash, provider, json.dumps(payload)[:1_000_000], int(time.time())))
    conn.commit(); conn.close()