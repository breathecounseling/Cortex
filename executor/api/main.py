from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

# Optional: load environment from .env (harmless if not present)
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
#  CHAT ENDPOINT — Restored Cortex Router flow
# ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat_endpoint(request: Request) -> dict:
    """
    Main chat interface routed through Cortex's executive layers.
    Uses Router → Focus Manager → Plugins → Memory stack.
    Falls back gracefully if router or plugin chain fails.
    """
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return {"status": "error", "message": "Empty message."}

    try:
        # Primary: use Cortex Router
        from executor.core import router
        response = router.route_input(message)
        # Router returns dict {status, assistant_message, ...}
        if isinstance(response, dict):
            return response
        return {"status": "ok", "assistant_message": str(response)}

    except Exception as e:
        # Safe fallback if Router or plugins unavailable
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {
                "status": "ok",
                "assistant_message": f"(offline echo) {message}",
                "detail": f"Router unavailable: {e}"
            }
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            r = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Cortex, an autonomous executive-function manager. "
                            "If internal routing fails, respond concisely and safely."
                        )
                    },
                    {"role": "user", "content": message},
                ],
                max_tokens=500,
            )
            reply = r.choices[0].message.content
            return {"status": "ok", "assistant_message": reply}
        except Exception as inner:
            return {"status": "error", "message": f"Router and fallback failed: {inner}"}


# ─────────────────────────────────────────────────────────────
#  EXECUTION ENDPOINT (unchanged)
# ─────────────────────────────────────────────────────────────
@app.post("/execute")
async def execute_endpoint(request: Request) -> dict:
    """Executes plugin or automation tasks."""
    payload = await request.json()
    return {"status": "ok", "data": payload, "message": "Execution successful."}


# ─────────────────────────────────────────────────────────────
#  CONTEXT ENDPOINT (unchanged)
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
#  HEALTH PROBE (unchanged)
# ─────────────────────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
def health_check():
    """Lightweight Fly.io health check."""
    return JSONResponse({"status": "ok", "message": "Cortex backend healthy."})