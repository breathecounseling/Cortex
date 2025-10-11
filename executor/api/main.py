from __future__ import annotations
import os
from typing import List, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# ---- Cortex core + AI wrappers (from the known-good zip) ----
# Router decides when to call plugins vs model
from executor.core.router import route as route_intent
# LLM wrapper used when we need a free-form reply
from executor.ai.router import chat as chat_llm

# Memory & summarization layers
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
)
from executor.utils.vector_memory import (
    store_vector,
    search_similar,
)
from executor.utils.summarizer import summarize_if_needed

# ------------------------------------------------------------
#  FastAPI app
# ------------------------------------------------------------
app = FastAPI(title="Cortex API")

# Serve built UI (Vite) at /ui if present
_UI_DIR = Path(__file__).resolve().parent.parent / "static" / "ui"
if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")

# ------------------------------------------------------------
#  Health & root
# ------------------------------------------------------------
@app.get("/")
def root() -> dict:
    return {"status": "ok", "message": "Cortex API is running."}

@app.get("/health", include_in_schema=False)
def health_check():
    return JSONResponse({"status": "ok", "message": "Cortex backend healthy."})

# ------------------------------------------------------------
#  Context endpoint for the UI sidebar (unchanged)
# ------------------------------------------------------------
@app.get("/context")
def get_context() -> dict:
    try:
        from executor.utils import context_state as _ctx
        return {"status": "ok", "data": _ctx.load_state()}
    except Exception as e:
        return {"status": "error", "message": f"context unavailable: {e}"}

# ------------------------------------------------------------
#  CHAT — restored brain/memory flow
# ------------------------------------------------------------
@app.post("/chat")
async def chat_endpoint(request: Request) -> dict:
    """
    Restored Cortex stack:
      1) init short-term memory
      2) recall recent context
      3) semantic recall from vector memory (if API key present)
      4) route intent (plugins) OR call LLM wrapper
      5) persist exchanges
      6) store vectors + maybe summarize
    Always fails safe per Directive #7.
    """
    body = await request.json()
    user_text: str = (body.get("message") or body.get("text") or "").strip()
    boost: bool = bool(body.get("boost", False))
    system: str | None = body.get("system")

    if not user_text:
        return {"status": "error", "message": "Empty message."}

    # 1) Ensure memory DB exists
    try:
        init_db_if_needed()
    except Exception:
        pass

    # 2) Recall short-term context (best-effort)
    ctx: List[Dict[str, str]] = []
    try:
        # prefer newer signature with limit
        ctx = recall_context(limit=6)
    except TypeError:
        try:
            ctx = recall_context()
        except Exception:
            ctx = []

    context_text = "\n".join(
        f"{m.get('role','')}:{m.get('content','')}" for m in ctx
    ) if isinstance(ctx, list) else str(ctx)

    # 3) Semantic memory recall — only when OPENAI_API_KEY available
    memory_text = ""
    if os.getenv("OPENAI_API_KEY"):
        try:
            memories = search_similar(user_text, top_k=5)
            memory_text = "\n".join(memories)
        except Exception:
            memory_text = ""

    # 4) Route intent to plugins; if router returns a usable assistant_message, use it.
    assistant_message: str | None = None
    try:
        routed = route_intent(user_text, session="repl", directives=None)
        # Expect dict with possibly 'assistant_message' or 'summary'
        if isinstance(routed, dict):
            assistant_message = routed.get("assistant_message") or routed.get("summary")
    except Exception:
        # Router not available or plugin error — fall back to LLM below
        assistant_message = None

    # If router didn't produce a message, call the LLM wrapper (with memory/context)
    if not assistant_message:
        prompt = user_text
        if memory_text:
            prompt = f"Relevant past memory:\n{memory_text}\n\nUser: {user_text}"
        if context_text:
            prompt = f"{prompt}\n\n(Recent context)\n{context_text}"
        try:
            assistant_message = chat_llm(prompt, boost=boost, system=system)
        except Exception as e:
            # last-resort offline mode
            assistant_message = f"(offline echo) {user_text}\n\n(detail: {e})"

    # 5) Persist exchanges (best-effort)
    try:
        remember_exchange("user", user_text)
        remember_exchange("assistant", assistant_message or "")
    except Exception:
        pass

    # 6) Store vectors and maybe summarize (only if embeddings available)
    if os.getenv("OPENAI_API_KEY"):
        try:
            store_vector("user", user_text)
            store_vector("assistant", assistant_message or "")
            summarize_if_needed()
        except Exception:
            pass

    return {
        "status": "ok",
        "assistant_message": assistant_message or "",
        "used_router": bool(assistant_message),  # for quick sanity in logs
    }

# ------------------------------------------------------------
#  EXECUTE (kept as-is)
# ------------------------------------------------------------
@app.post("/execute")
async def execute_endpoint(request: Request) -> dict:
    payload = await request.json()
    return {"status": "ok", "data": payload, "message": "Execution successful."}