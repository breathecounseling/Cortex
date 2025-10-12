# executor/utils/vector_memory.py
from __future__ import annotations
import os, sqlite3, json, uuid, time, re
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path

import numpy as np

# --- OpenAI client: optional at runtime (Directive #7 safe) ---
_OPENAI_AVAILABLE = False
try:
    from openai import OpenAI  # type: ignore
    _OPENAI_AVAILABLE = True
except Exception:
    _OPENAI_AVAILABLE = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("CORTEX_EMBED_MODEL", "text-embedding-3-small")
SUMMARY_MODEL = os.getenv("CORTEX_SUMMARY_MODEL", "gpt-4o-mini")

# DB lives on persistent volume
DB_PATH = Path("/data") / "vector_memory.db"
os.makedirs(DB_PATH.parent.as_posix(), exist_ok=True)

# Embedding dimension (OpenAI small ~1536 today; we’ll choose 384 for fallback)
FALLBACK_DIM = int(os.getenv("CORTEX_EMBED_DIM", "384"))

# Compaction thresholds
COMPACT_THRESHOLD = int(os.getenv("CORTEX_COMPACT_THRESHOLD", "600"))   # compact when volume exceeds this many unarchived detail rows
COMPACT_BATCH = int(os.getenv("CORTEX_COMPACT_BATCH", "250"))           # how many detail rows to absorb into a summary per compaction
DEFAULT_TOPIC = "general"

# ---------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)

def init_vector_db() -> None:
    conn = _connect()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS vectors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        vector BLOB
    )""")
    conn.commit()
    conn.close()
    migrate_vector_db()
    _ensure_indices()

def migrate_vector_db() -> None:
    conn = _connect()
    c = conn.cursor()
    # Add columns if missing
    for stmt in [
        "ALTER TABLE vectors ADD COLUMN volume_id TEXT DEFAULT ''",
        "ALTER TABLE vectors ADD COLUMN volume_seq INTEGER DEFAULT 0",
        "ALTER TABLE vectors ADD COLUMN topic TEXT DEFAULT ''",
        "ALTER TABLE vectors ADD COLUMN kind TEXT DEFAULT 'detail'",  # 'detail' | 'summary'
        "ALTER TABLE vectors ADD COLUMN range_start INTEGER DEFAULT 0",
        "ALTER TABLE vectors ADD COLUMN range_end INTEGER DEFAULT 0",
        "ALTER TABLE vectors ADD COLUMN keywords TEXT DEFAULT ''",
        "ALTER TABLE vectors ADD COLUMN archived INTEGER DEFAULT 0"
    ]:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

def _ensure_indices() -> None:
    conn = _connect()
    c = conn.cursor()
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_vectors_kind ON vectors(kind)",
        "CREATE INDEX IF NOT EXISTS idx_vectors_topic ON vectors(topic)",
        "CREATE INDEX IF NOT EXISTS idx_vectors_vol ON vectors(volume_id)",
        "CREATE INDEX IF NOT EXISTS idx_vectors_arch ON vectors(archived)",
        "CREATE INDEX IF NOT EXISTS idx_vectors_range ON vectors(range_start, range_end)"
    ]:
        c.execute(stmt)
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------
# Embeddings & similarity
# ---------------------------------------------------------------------
_client = None
if _OPENAI_AVAILABLE and OPENAI_API_KEY:
    try:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        _client = None

def _hash_fallback(text: str, dim: int = FALLBACK_DIM) -> np.ndarray:
    """Deterministic pseudo-embedding when OpenAI is unavailable."""
    # Simple hashing trick: map bytes into a fixed-dim vector
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    v = rng.normal(size=dim).astype(np.float32)
    # Light L2-normalization
    n = np.linalg.norm(v)
    return v / n if n > 0 else v

def embed(text: str) -> bytes:
    """
    Return a vector as bytes (float32 array). Uses OpenAI if available,
    else a deterministic hash-based vector.
    """
    text = (text or "").strip()
    if not text:
        return _hash_fallback("").tobytes()
    if _client is not None:
        try:
            ev = _client.embeddings.create(model=EMBEDDING_MODEL, input=text)
            vec = np.array(ev.data[0].embedding, dtype=np.float32)
            # normalize for better cosine behavior
            n = np.linalg.norm(vec)
            vec = vec / n if n > 0 else vec
            return vec.tobytes()
        except Exception:
            pass
    # Fallback
    return _hash_fallback(text).tobytes()

def _cosine_sim(v1: np.ndarray, v2: np.ndarray) -> float:
    n1 = np.linalg.norm(v1); n2 = np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))

# ---------------------------------------------------------------------
# Topic detection
# ---------------------------------------------------------------------
_TOPIC_RULES = [
    (re.compile(r"\b(revenue|invoice|balance|kpi|pnl|profit|ops|operations|biz|business)\b", re.I), "bizops"),
    (re.compile(r"\b(workout|gym|steps|calorie|protein|run|yoga|sleep|meal|log my lunch)\b", re.I), "fitness"),
    (re.compile(r"\b(travel|itinerary|flight|hotel|route|drive|vacation|trip)\b", re.I), "travel"),
    (re.compile(r"\b(code|bug|test|deploy|docker|fastapi|react|vite|plugin|python|typescript)\b", re.I), "dev"),
]

def detect_topic(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return DEFAULT_TOPIC
    for rx, label in _TOPIC_RULES:
        if rx.search(t):
            return label
    return DEFAULT_TOPIC

# ---------------------------------------------------------------------
# Store & search
# ---------------------------------------------------------------------
def store_vector(role: str, text: str, topic: Optional[str] = None,
                 kind: str = "detail", volume_id: str = "", volume_seq: int = 0,
                 keywords: str = "") -> None:
    """Persist a vector row."""
    init_vector_db()
    v = embed(text)
    topic = topic or detect_topic(text)
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO vectors (role, content, vector, topic, kind, volume_id, volume_seq, keywords, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (role, text, v, topic, kind, volume_id, volume_seq, keywords))
    conn.commit()
    conn.close()

def search_similar(query: str, top_k: int = 5, topic: Optional[str] = None,
                   kind: Optional[str] = None, volume_id: Optional[str] = None) -> List[str]:
    """
    Flat cosine search over vectors. Use filters to scope by topic/kind/volume.
    Returns contents only (strings), sorted by similarity desc.
    """
    init_vector_db()
    qv = np.frombuffer(embed(query), dtype=np.float32)

    conn = _connect()
    c = conn.cursor()
    clauses = ["archived=0"]
    params: List[Any] = []
    if topic:
        clauses.append("topic=?"); params.append(topic)
    if kind:
        clauses.append("kind=?"); params.append(kind)
    if volume_id:
        clauses.append("volume_id=?"); params.append(volume_id)
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    c.execute(f"SELECT content, vector FROM vectors{where_sql}")
    rows = c.fetchall()
    conn.close()

    scored: List[Tuple[float, str]] = []
    for content, blob in rows:
        v = np.frombuffer(blob, dtype=np.float32)
        scored.append((_cosine_sim(qv, v), content))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:max(1, top_k)]]

# ---------------------------------------------------------------------
# Summarization & compaction (volumes)
# ---------------------------------------------------------------------
def _client_summary(text: str, goal: str = "Summarize key ideas in concise bullet points.") -> str:
    """Use OpenAI to summarize. Falls back to rule-based when API is missing."""
    # Guard: keep things short
    text = text[:10000]
    if _client is not None:
        try:
            resp = _client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[
                    {"role": "system", "content": goal},
                    {"role": "user", "content": text}
                ],
                max_tokens=300,
                temperature=0.2
            )
            out = (resp.choices[0].message.content or "").strip()
            return out or "Summary unavailable."
        except Exception:
            pass
    # Fallback: naive compression
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    bullets = []
    for ln in lines[:20]:
        if len(ln) > 180:
            bullets.append("• " + ln[:177] + "…")
        else:
            bullets.append("• " + ln)
    return "\n".join(bullets[:15]) or "Summary unavailable."

def _first_default_volume(conn: sqlite3.Connection) -> str:
    c = conn.cursor()
    c.execute("SELECT DISTINCT volume_id FROM vectors WHERE volume_id!='' LIMIT 1")
    row = c.fetchone()
    if row and row[0]:
        return row[0]
    # No volumes yet: create default by assigning empty volume_id rows to a new one
    vid = str(uuid.uuid4())
    c.execute("UPDATE vectors SET volume_id=? WHERE volume_id='' AND kind='detail'", (vid,))
    conn.commit()
    return vid

def _unarchived_count(conn: sqlite3.Connection, volume_id: str) -> int:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM vectors WHERE volume_id=? AND kind='detail' AND archived=0", (volume_id,))
    return int(c.fetchone()[0])

def compact_volume(volume_id: Optional[str] = None) -> bool:
    """
    Compact one volume by summarizing the oldest batch of unarchived detail rows.
    Returns True if compaction happened.
    """
    init_vector_db()
    conn = _connect()
    try:
        if not volume_id:
            volume_id = _first_default_volume(conn)

        if _unarchived_count(conn, volume_id) < COMPACT_THRESHOLD:
            return False

        c = conn.cursor()
        # Oldest unarchived detail rows
        c.execute("""
        SELECT id, content FROM vectors
        WHERE volume_id=? AND kind='detail' AND archived=0
        ORDER BY id ASC LIMIT ?
        """, (volume_id, COMPACT_BATCH))
        rows = c.fetchall()
        if not rows:
            return False

        start_id, end_id = rows[0][0], rows[-1][0]
        texts = [t for _, t in rows]
        summary_text = _client_summary("\n".join(texts))

        # Insert summary row
        topic = detect_topic(" ".join(texts[:10]))
        vbytes = embed(summary_text)
        c.execute("""
        INSERT INTO vectors(role, content, vector, topic, kind, volume_id, range_start, range_end, keywords, archived)
        VALUES('system', ?, ?, ?, 'summary', ?, ?, ?, ?, 0)
        """, (summary_text, vbytes, topic, volume_id, start_id, end_id, ""))

        # Archive originals
        c.execute("""
        UPDATE vectors SET archived=1 WHERE volume_id=? AND id BETWEEN ? AND ?
        """, (volume_id, start_id, end_id))
        conn.commit()
        return True
    finally:
        conn.close()

def summarize_if_needed() -> None:
    """
    Public entry-point. Assign a default volume if none, and compact when thresholds are exceeded.
    Safe to call every turn.
    """
    init_vector_db()
    conn = _connect()
    try:
        vid = _first_default_volume(conn)
        # Compact if needed
        _ = compact_volume(vid)
    finally:
        conn.close()

# ---------------------------------------------------------------------
# Hierarchical retrieval
# ---------------------------------------------------------------------
def find_relevant_volume(query: str, k: int = 3) -> List[str]:
    """
    Return top-k volume IDs whose summaries best match the query.
    """
    init_vector_db()
    qv = np.frombuffer(embed(query), dtype=np.float32)

    conn = _connect()
    c = conn.cursor()
    c.execute("""
    SELECT DISTINCT volume_id, vector FROM vectors
    WHERE kind='summary' AND vector!=''
    """)
    rows = c.fetchall()
    conn.close()

    if not rows:
        return []

    scored: List[Tuple[float, str]] = []
    for vid, blob in rows:
        v = np.frombuffer(blob, dtype=np.float32)
        scored.append((_cosine_sim(qv, v), vid))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [vid for _, vid in scored[:max(1, k)] if vid]

def recall_from_volume(query: str, volume_id: str, k: int = 5) -> List[str]:
    """
    Search detailed rows within a specific volume. Returns top-k content strings.
    """
    init_vector_db()
    qv = np.frombuffer(embed(query), dtype=np.float32)
    conn = _connect()
    c = conn.cursor()
    c.execute("""
    SELECT content, vector FROM vectors
    WHERE volume_id=? AND kind='detail' AND archived=0
    """, (volume_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return []

    scored: List[Tuple[float, str]] = []
    for content, blob in rows:
        v = np.frombuffer(blob, dtype=np.float32)
        scored.append((_cosine_sim(qv, v), content))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:max(1, k)]]

# ---------------------------------------------------------------------
# Convenience: combined retrieval (flat + hierarchical)
# ---------------------------------------------------------------------
def retrieve_topic_summaries(query: str, k: int = 3) -> List[str]:
    """
    Return top-k short summaries across all volumes (kind='summary').
    """
    return search_similar(query, top_k=k, kind="summary")

def hierarchical_recall(query: str, k_vols: int = 2, k_refs: int = 3) -> List[str]:
    """
    2-level recall: pick relevant volumes, then fetch top detailed refs in each.
    """
    vols = find_relevant_volume(query, k=k_vols)
    out: List[str] = []
    for vid in vols:
        refs = recall_from_volume(query, vid, k=k_refs)
        if refs:
            out.append(f"Volume {vid}:\n" + "\n".join(refs))
    return out

# ---------------------------------------------------------------------
# Small utility: export / maintenance
# ---------------------------------------------------------------------
def export_index() -> Dict[str, Any]:
    """Return a small JSON summary of volumes and counts (for debugging/diagnostics)."""
    init_vector_db()
    conn = _connect()
    c = conn.cursor()
    c.execute("""
    SELECT volume_id,
           SUM(CASE WHEN kind='detail' AND archived=0 THEN 1 ELSE 0 END) as active_detail,
           SUM(CASE WHEN kind='summary' THEN 1 ELSE 0 END) as summaries,
           SUM(CASE WHEN kind='detail' AND archived=1 THEN 1 ELSE 0 END) as archived_detail
    FROM vectors
    GROUP BY volume_id
    """)
    rows = c.fetchall()
    conn.close()
    return {
        "volumes": [
            {"volume_id": r[0], "active_detail": int(r[1]), "summaries": int(r[2]), "archived_detail": int(r[3])}
            for r in rows
        ]
    }