# executor/api/main.py
from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from executor.core.router import route
from executor.ai.router import chat as chat_llm
from executor.utils.memory import init_db_if_needed, recall_context, remember_exchange

app = FastAPI(title="Cortex Executor API")

@app.get("/")
def healthcheck():
    return {"status": "ok"}

class ChatBody(BaseModel):
    text: str
    boost: bool | None = False
    system: str | None = None

@app.post("/chat")
def chat(body: ChatBody):
    """
    Chat endpoint for Cortex with persistent memory.
    - Loads the last 6 messages from the memory DB.
    - Appends the new message.
    - Persists both user and assistant exchanges.
    """
    init_db_if_needed()

    # Retrieve last N messages for context
    context = recall_context(limit=6)
    context_text = "\n".join(f"{m['role']}: {m['content']}" for m in context)
    full_prompt = f"{context_text}\nUser: {body.text}" if context_text else body.text

    # Generate response
    reply = chat_llm(full_prompt, boost=bool(body.boost), system=body.system)

    # Store both sides
    remember_exchange("user", body.text)
    remember_exchange("assistant", reply)

    return {"reply": reply, "boost_used": bool(body.boost)}

@app.post("/execute")
def execute(user_text: str):
    """Retains existing Executor contract routing."""
    result = route(user_text)
    return {"result": result}

# === /ui route with Boost + memory (already in your current version) ===
from fastapi.responses import HTMLResponse

@app.get("/ui", response_class=HTMLResponse)
def ui():
    """Interactive Cortex Chat UI with Boost mode and local memory."""
    # (keep your current HTML/JS version here exactly as written)
    # No changes needed — it now uses backend memory automatically.
    return """..."""