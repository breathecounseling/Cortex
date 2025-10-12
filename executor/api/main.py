from __future__ import annotations
import os, re, json
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback

# 🧠 Brain + memory
from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
    save_fact,
    list_facts,
)
from executor.utils.vector_memory import store_vector, summarize_if_needed

app = FastAPI()

# Mount built frontend at /ui if present
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=_frontend_dir.as_posix(), html=True), name="ui")


class ChatBody(BaseModel):
    text: str | None = None
    boost: bool | None = False
    system: str | None = None


@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}


@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    # Tolerate UI variations: message/prompt/content
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    text = (body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or "").strip()
    if not text:
        return {"reply": "How can I help?"}

    # ---- ROUTER PHASE ----
    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}

    actions = router_output.get("actions", [])

    # ---- 🧠  If no plugin actions, fall back to brain + memory ----
    if not actions:
        try:
            init_db_if_needed()
            context = recall_context(limit=6)
        except Exception:
            context = []

        # 💾 inject stored user facts as part of context
        try:
            facts = list_facts()
            if facts:
                context.insert(
                    0,
                    {
                        "role": "system",
                        "content": f"Known user facts: {json.dumps(facts)}",
                    },
                )
        except Exception:
            pass

        # 💾 capture new facts like "My X is Y"
        try:
            fact_match = re.match(r"\bmy\s+([\w\s]+?)\s+is\s+(.+)", text, re.I)
            if fact_match:
                key, val = fact_match.groups()
                save_fact(key.strip().lower(), val.strip())
        except Exception:
            pass

        try:
            reply = brain_chat(text, context=context)
        except Exception as e:
            reply = f"(brain offline) {e}"

        # record exchanges + vectors (best-effort)
        try:
            remember_exchange("user", text)
            remember_exchange("assistant", reply)
            store_vector("user", text)
            store_vector("assistant", reply)
            summarize_if_needed()
        except Exception:
            pass

        return {"reply": reply}

    # ---- PLUGIN DISPATCH ----
    action = actions[0]
    plugin = action.get("plugin")
    args = action.get("args", {})

    try:
        if plugin == "web_search":
            result = web_search.handle(args)
        elif plugin == "weather_plugin":
            result = weather_plugin.handle(args)
        elif plugin == "google_places":
            result = google_places.handle(args)
        elif plugin == "feedback":
            result = feedback.handle(args)
        else:
            result = {"status": "ok", "summary": router_output.get("assistant_message", "Okay.")}

        # 🧠 reflection: if plugin output is empty or non-conversational, rewrite via brain
        summary = result.get("summary") or ""
        if len(summary.strip()) < 40 or summary.lower().startswith(("no ", "error", "none")):
            try:
                reply = brain_chat(
                    f"{text}\n\nPlugin output:\n{summary}\n\n"
                    "Respond conversationally or fill in any missing information."
                )
                return {"reply": reply}
            except Exception:
                pass

        return {"reply": summary}
    except Exception as e:
        return {"reply": f"Plugin error ({plugin}): {e}"}


@app.post("/execute")
def execute(body: Dict[str, Any]) -> Dict[str, Any]:
    plugin = body.get("plugin")
    args = body.get("args", {})
    if not plugin:
        return {"status": "error", "message": "Missing plugin name."}
    try:
        if plugin == "web_search":
            return web_search.handle(args)
        if plugin == "weather_plugin":
            return weather_plugin.handle(args)
        if plugin == "google_places":
            return google_places.handle(args)
        if plugin == "feedback":
            return feedback.handle(args)
    except Exception as e:
        return {"status": "error", "message": f"{plugin} failed: {e}"}
    return {"status": "error", "message": f"Unknown plugin: {plugin}"}


@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
def startup_message() -> None:
    print("✅ Cortex API started — ready for chat and plugin actions.")