from __future__ import annotations
import os, sqlite3, json, uuid, time, re
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
import numpy as np

_OPENAI_AVAILABLE = False
try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except Exception:
    _OPENAI_AVAILABLE = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("CORTEX_EMBED_MODEL", "text-embedding-3-small")
SUMMARY_MODEL = os.getenv("CORTEX_SUMMARY_MODEL", "gpt-4o-mini")

DB_PATH = Path("/data") / "vector_memory.db"
os.makedirs(DB_PATH.parent.as_posix(), exist_ok=True)
FALLBACK_DIM = int(os.getenv("CORTEX_EMBED_DIM", "384"))
COMPACT_THRESHOLD = int(os.getenv("CORTEX_COMPACT_THRESHOLD", "600"))
COMPACT_BATCH = int(os.getenv("CORTEX_COMPACT_BATCH", "250"))
DEFAULT_TOPIC = "general"

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
        vector BLOB,
        topic TEXT DEFAULT '',
        kind TEXT DEFAULT 'detail',
        volume_id TEXT DEFAULT '',
        range_start INTEGER DEFAULT 0,
        range_end INTEGER DEFAULT 0,
        keywords TEXT DEFAULT '',
        archived INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()

def _client_instance():
    if _OPENAI_AVAILABLE and OPENAI_API_KEY:
        try:
            return OpenAI(api_key=OPENAI_API_KEY)
        except Exception:
            return None
    return None

_client = _client_instance()

def _hash_fallback(text: str, dim: int = FALLBACK_DIM) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    v = rng.normal(size=dim).astype(np.float32)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v

def embed(text: str) -> bytes:
    text = (text or "").strip()
    if not text:
        return _hash_fallback("").tobytes()
    if _client:
        try:
            ev = _client.embeddings.create(model=EMBEDDING_MODEL, input=text)
            vec = np.array(ev.data[0].embedding, dtype=np.float32)
            vec /= np.linalg.norm(vec) or 1.0
            return vec.tobytes()
        except Exception:
            pass
    return _hash_fallback(text).tobytes()

def _cosine_sim(v1: np.ndarray, v2: np.ndarray) -> float:
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    return float(np.dot(v1, v2) / (n1 * n2)) if n1 and n2 else 0.0

def store_vector(role: str, text: str, topic: Optional[str] = None) -> None:
    init_vector_db()
    conn = _connect()
    try:
        v = embed(text)
        topic = topic or "general"
        conn.execute(
            "INSERT INTO vectors (role, content, vector, topic, kind, archived) VALUES (?, ?, ?, ?, 'detail', 0)",
            (role, text, v, topic)
        )
        conn.commit()
    except Exception as e:
        print("[VectorStoreError]", e)
    finally:
        conn.close()

def _client_summary(text: str) -> str:
    if _client:
        try:
            resp = _client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[
                    {"role": "system", "content": "Summarize key ideas in concise bullet points."},
                    {"role": "user", "content": text[:10000]},
                ],
                max_tokens=300,
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            print("[VectorSummaryError]", e)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join("• " + ln[:180] for ln in lines[:15])

def summarize_if_needed() -> None:
    """Compact details into summaries safely (fixed parameter binding)."""
    init_vector_db()
    conn = _connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM vectors WHERE kind='detail' AND archived=0"
        ).fetchone()[0]
        if count < COMPACT_THRESHOLD:
            return
        rows = conn.execute(
            "SELECT id, content FROM vectors WHERE kind='detail' AND archived=0 ORDER BY id ASC LIMIT ?",
            (COMPACT_BATCH,),
        ).fetchall()
        if not rows:
            return
        start_id, end_id = rows[0][0], rows[-1][0]
        text = "\n".join(t for _, t in rows)
        summary = _client_summary(text)
        vec = embed(summary)
        conn.execute(
            "INSERT INTO vectors (role, content, vector, topic, kind, range_start, range_end, archived)"
            " VALUES ('system', ?, ?, 'general', 'summary', ?, ?, 0)",
            (summary, vec, start_id, end_id),
        )
        conn.execute(
            "UPDATE vectors SET archived=1 WHERE id BETWEEN ? AND ? AND kind='detail'",
            (start_id, end_id),
        )
        conn.commit()
    except Exception as e:
        print("[VectorMemorySummaryError]", e)
    finally:
        conn.close()

# ---------------------------------------------------------------------
# Retrieval helpers restored
# ---------------------------------------------------------------------

def retrieve_topic_summaries(query: str, k: int = 3) -> list[str]:
    """
    Return top-k short summaries across all vectors.
    Used by main.py for memory context injection.
    """
    init_vector_db()
    conn = _connect()
    try:
        qv = np.frombuffer(embed(query), dtype=np.float32)
        c = conn.cursor()
        rows = c.execute(
            "SELECT content, vector FROM vectors WHERE kind='summary' AND archived=0"
        ).fetchall()
        scored = []
        for content, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            scored.append((_cosine_sim(qv, v), content))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:max(1, k)]]
    except Exception as e:
        print("[RetrieveTopicSummariesError]", e)
        return []
    finally:
        conn.close()


def hierarchical_recall(query: str, k_vols: int = 2, k_refs: int = 3) -> list[str]:
    """
    Two-level recall stub for compatibility; returns top detailed memories.
    """
    init_vector_db()
    conn = _connect()
    try:
        qv = np.frombuffer(embed(query), dtype=np.float32)
        c = conn.cursor()
        rows = c.execute(
            "SELECT content, vector FROM vectors WHERE kind='detail' AND archived=0"
        ).fetchall()
        scored = []
        for content, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            scored.append((_cosine_sim(qv, v), content))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [t for _, t in scored[:max(1, k_refs)]]
        return top
    except Exception as e:
        print("[HierarchicalRecallError]", e)
        return []
    finally:
        conn.close()