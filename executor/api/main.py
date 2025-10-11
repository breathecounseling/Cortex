from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

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


@app.post("/chat")
async def chat_endpoint(request: Request) -> dict:
    """Main chat interface."""
    body = await request.json()
    message = body.get("message", "")
    return {"status": "ok", "assistant_message": f"Echo: {message}"}


@app.post("/execute")
async def execute_endpoint(request: Request) -> dict:
    """Executes plugin or automation tasks."""
    payload = await request.json()
    return {"status": "ok", "data": payload, "message": "Execution successful."}


# ─────────────────────────────────────────────────────────────
#  Context endpoint for UI sidebar
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
#  Health probe for Fly.io
# ─────────────────────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
def health_check():
    """Lightweight Fly.io health check."""
    return JSONResponse({"status": "ok", "message": "Cortex backend healthy."})