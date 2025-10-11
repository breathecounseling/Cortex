from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

# Optional: load environment from .env if present (harmless if missing)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ------------------------------------------------------------
#  Cortex FastAPI Application
# ------------------------------------------------------------
app = FastAPI(title="Cortex API")

# ─────────────────────────────────────────────────────────────
#  Mount built frontend if present
# ─────────────────────────────────────────────────────────────
_UI_DIR = Path(__file__).resolve().parent.parent / "static" / "ui"
if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")

# ─────────────────────────────────────────────────────────────
#  Core Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/")
def root() -> dict:
    """Simple API heartbeat."""
    return {"status": "ok", "message": "Cortex API is running."}

# ─────────────────────────────────────────────────────────────
#  Chat endpoint (real AI integration + safe fallback)
# ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat_endpoint(request: Request) -> dict:
    """
    Main chat interface. Returns AI response if OPENAI_API_KEY is set,
    otherwise falls back to local echo.
    """
    body = await request.json()
    message = body.get("message", "").strip()

    if not message:
        return {"status": "error", "message": "Empty message."}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Safe fallback (Directive #7)
        return {"status": "ok", "assistant_message": f"(offline echo) {message}"}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # adjust if you prefer gpt-4-turbo, etc.
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Cortex, an autonomous executive-function "
                        "manager that plans, analyzes, and builds tasks. "
                        "Respond clearly and concisely."
                    ),
                },
                {"role": "user", "content": message},
            ],
            max_tokens=500,
        )
        reply = response.choices[0].message.content
        return {"status": "ok", "assistant_message": reply}
    except Exception as e:
        return {"status": "error", "message": f"Chat error: {e}"}

# ─────────────────────────────────────────────────────────────
#  Execute endpoint (unchanged)
# ─────────────────────────────────────────────────────────────
@app.post("/execute")
async def execute_endpoint(request: Request) -> dict:
    """Executes plugin or automation tasks."""
    payload = await request.json()
    return {"status": "ok", "data": payload, "message": "Execution successful."}

# ─────────────────────────────────────────────────────────────
#  Context endpoint for UI sidebar (unchanged)
# ─────────────────────────────────────────────────────────────
@app.get("/context")
def get_context() -> dict:
    """
    Returns time / timezone / last location for the chat sidebar.
    Fails gracefully if context_state not initialized.
    """
    try:
        from executor.utils import context_state as _ctx
        return {"status": "ok", "data": _ctx.load_state()}
    except Exception as e:
        return {"status": "error", "message": f"context unavailable: {e}"}

# ─────────────────────────────────────────────────────────────
#  Health probe for Fly.io (unchanged)
# ─────────────────────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
def health_check():
    """Lightweight Fly.io health check."""
    return JSONResponse({"status": "ok", "message": "Cortex backend healthy."})