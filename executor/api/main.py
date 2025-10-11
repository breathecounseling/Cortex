from __future__ import annotations
import os
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Optional env loader; harmless if missing
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ------------------------------------------------------------
#  FastAPI app
# ------------------------------------------------------------
app = FastAPI(title="Cortex API")

# Verbose request logging so Fly logs show /chat calls
logging.basicConfig(level=logging.INFO)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logging.info("%s %s", request.method, request.url.path)
    return await call_next(request)

# ------------------------------------------------------------
#  Serve built UI (Vite) at /ui if present
# ------------------------------------------------------------
_UI_DIR = Path(__file__).resolve().parent.parent / "static" / "ui"
if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")

# ------------------------------------------------------------
#  Heartbeat & Health
# ------------------------------------------------------------
@app.get("/")
def root() -> dict:
    return {"status": "ok", "message": "Cortex API is running."}

@app.get("/health", include_in_schema=False)
def health_check():
    return JSONResponse({"status": "ok", "message": "Cortex backend healthy."})

# ------------------------------------------------------------
#  Context endpoint (unchanged)
# ------------------------------------------------------------
@app.get("/context")
def get_context() -> dict:
    try:
        from executor.utils import context_state as _ctx
        return {"status": "ok", "data": _ctx.load_state()}
    except Exception as e:
        return {"status": "error", "message": f"context unavailable: {e}"}

# ------------------------------------------------------------
#  CHAT — restore full brain path via Router + plugins + memory
# ------------------------------------------------------------
@app.post("/chat")
async def chat_endpoint(request: Request) -> dict:
    """
    Route chat through Cortex Router. This:
      1) initializes logging/memory (best-effort),
      2) ensures plugin packages import (registry side-effects),
      3) calls router.route_input(...) if present, else router.route(...),
      4) normalizes the result to {status, assistant_message},
      5) falls back to AI (or offline echo) if router fails.
    """
    body = await request.json()
    message: str = (body.get("message") or body.get("text") or "").strip()
    if not message:
        return {"status": "error", "message": "Empty message."}

    # 1) initialize logging + memory (no-op if already done)
    try:
        from executor.audit.logger import initialize_logging  # type: ignore
        initialize_logging()
    except Exception:
        pass
    try:
        from executor.utils.memory import init_db_if_needed  # type: ignore
        init_db_if_needed()
    except Exception:
        pass

    # 2) ensure plugins import (some registries rely on import side-effects)
    try:
        import executor.plugins  # noqa: F401
    except Exception as e:
        logging.warning("Plugins import failed: %s", e)

    # 3) call router entrypoint (route_input preferred; fallback to route)
    try:
        from executor.core import router  # type: ignore
        logging.info("Router module loaded: %s", router.__file__)

        if hasattr(router, "route_input"):
            routed = router.route_input(message)
        elif hasattr(router, "route"):
            routed = router.route(message)
        else:
            raise RuntimeError("Router has no route_input/route")

        # 4) normalize router response
        if isinstance(routed, dict):
            # Prefer assistant_message, then summary/message
            assistant = routed.get("assistant_message") or routed.get("summary") or routed.get("message")
            if assistant:
                return {"status": routed.get("status", "ok"), "assistant_message": assistant, "data": routed.get("data")}
            # If router returned a dict but no text, at least pass it through
            return {"status": routed.get("status", "ok"), "assistant_message": "Okay — let me think about that.", "data": routed}

        # non-dict, stringify
        return {"status": "ok", "assistant_message": str(routed)}

    except Exception as e:
        logging.exception("Router path failed: %s", e)
        # 5) AI fallback (keeps startup safe per Directive #7)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {"status": "ok", "assistant_message": f"(offline echo) {message}", "detail": str(e)}
        try:
            from openai import OpenAI  # type: ignore
            client = OpenAI(api_key=api_key)
            r = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are Cortex. The internal router failed; answer helpfully and concisely."},
                    {"role": "user", "content": message},
                ],
                max_tokens=500,
            )
            reply = r.choices[0].message.content
            return {"status": "ok", "assistant_message": reply}
        except Exception as inner:
            return {"status": "error", "message": f"Router and fallback failed: {inner}"}

# ------------------------------------------------------------
#  Execute (unchanged)
# ------------------------------------------------------------
@app.post("/execute")
async def execute_endpoint(request: Request) -> dict:
    payload = await request.json()
    return {"status": "ok", "data": payload, "message": "Execution successful."}