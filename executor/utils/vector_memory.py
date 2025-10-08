from __future__ import annotations
import os, sqlite3, numpy as np
from openai import OpenAI

DB_PATH = "/data/vector_memory.db" if os.path.exists("/data") else "vector_memory.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_vector_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                vector BLOB
            )
        """)
        conn.commit()

def embed(text: str) -> bytes:
    """Get a compact embedding and store as bytes."""
    vec = client.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding
    return np.array(vec, dtype=np.float32).tobytes()

def store_vector(role: str, text: str):
    init_vector_db()
    with _connect() as conn:
        conn.execute("INSERT INTO vectors (role, content, vector) VALUES (?, ?, ?)",
                     (role, text, embed(text)))
        conn.commit()

def search_similar(query: str, top_k: int = 5) -> list[str]:
    """Return top_k most similar stored contents."""
    init_vector_db()
    qvec = np.frombuffer(embed(query), dtype=np.float32)
    results = []
    with _connect() as conn:
        for role, content, blob in conn.execute("SELECT role, content, vector FROM vectors"):
            vec = np.frombuffer(blob, dtype=np.float32)
            sim = float(np.dot(qvec, vec) / (np.linalg.norm(qvec)*np.linalg.norm(vec)))
            results.append((sim, role, content))
    results.sort(reverse=True)
    return [f"{r[1]}: {r[2]}" for r in results[:top_k]]