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
    vec = client.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding
    return np.array(vec, dtype=np.float32).tobytes()

def store_vector(role: str, text: str):
    init_vector_db()
    with _connect() as conn:
        conn.execute("INSERT INTO vectors (role, content, vector) VALUES (?,?,?)",
                     (role, text, embed(text)))
        conn.commit()

def search_similar(query: str, top_k: int = 5) -> list[str]:
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

def summarize_if_needed(limit: int = 100):
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        if count <= limit:
            return
        rows = conn.execute("SELECT id, content FROM vectors ORDER BY id ASC LIMIT 20").fetchall()
        text = "\n".join([r[1] for r in rows])
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Summarize key ideas in concise bullet points."},
                {"role": "user", "content": text}
            ],
            max_tokens=200,
        )
        summary = resp.choices[0].message.content.strip()
        conn.execute("DELETE FROM vectors WHERE id IN (SELECT id FROM vectors ORDER BY id ASC LIMIT 20)")
        conn.execute("INSERT INTO vectors (role, content, vector) VALUES (?,?,?)",
                     ("summary", summary, embed(summary)))
        conn.commit()