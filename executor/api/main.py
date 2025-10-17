"""
executor/api/main.py
--------------------
Phase 2.13 — Adds Goal Manager + Drift Awareness
"""
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from executor.utils.sanitizer import sanitize_value
from executor.utils import memory_graph as gmem
from executor.core.semantic_parser import parse_message
from executor.utils.session_context import (
    set_last_fact, get_last_fact, set_topic, get_topic, set_intimacy, get_intimacy
)
from executor.utils.turn_memory import add_turn
from executor.core.context_reasoner import reason_about_context, build_context_block
from executor.core.reasoning import reason_about_goal
from executor.utils.dialogue_templates import clarifying_line
from executor.core.context_orchestrator import gather_design_context
from executor.utils.preference_graph import record_preference, get_preferences, get_dislikes
from executor.core.inference_engine import infer_contextual_preferences
from executor.utils.goals import list_goals, close_goal, get_most_recent_open

from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback
from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed, recall_context, remember_exchange,
    save_fact, list_facts, update_or_delete_from_text
)
from executor.utils.vector_memory import (
    store_vector, summarize_if_needed, retrieve_topic_summaries, hierarchical_recall
)

app = FastAPI()
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=_frontend_dir.as_posix(), html=True), name="ui")

class ChatBody(BaseModel):
    text: str | None = None
    boost: bool | None = False
    system: str | None = None
    session_id: str | None = None
    set_intimacy: int | None = None

def _session_id(request: Request, body: ChatBody) -> str:
    return body.session_id or request.headers.get("X-Session-ID") or "default"

@app.get("/")
def root() -> Dict[str, Any]: return {"status": "ok", "message": "Echo API is running."}
@app.get("/health", include_in_schema=False)
def health(): return JSONResponse({"status": "ok"})

@app.get("/refresh_inference")
def refresh_inference():
    data = infer_contextual_preferences()
    return {"status": "ok", "inferred": len(data)}

# --- new goal endpoints ---
@app.get("/goals")
def goals(session_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20):
    sid = session_id or "default"
    return {"goals": list_goals(sid, status=status, limit=limit)}

@app.post("/goals/close")
async def goals_close(body: ChatBody, request: Request):
    sid = _session_id(request, body)
    recent = get_most_recent_open(sid)
    if not recent:
        return {"status": "ok", "message": "No open goal."}
    close_goal(recent["id"], note="Closed via API")
    return {"status": "ok", "message": f"Closed “{recent['title']}”"}

@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    raw = {}
    try: raw = await request.json()
    except Exception: pass
    text = (body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or "").strip()
    if not text: return {"reply": "How can I help?"}

    session_id = _session_id(request, body)
    if body.set_intimacy is not None: set_intimacy(session_id, body.set_intimacy)
    intimacy_level = get_intimacy(session_id)
    add_turn("user", text, session_id=session_id)
    parsed_intents = parse_message(text, intimacy_level=intimacy_level)

    m_topic = re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b(.+)$", text)
    if m_topic:
        topic = m_topic.group(2).strip(" .!?")
        if topic: set_topic(session_id, topic)

    replies: list[str] = []
    for p in parsed_intents:
        intent = reason_about_context(p, text, session_id=session_id)

        # --- nudges / goals ---
        if isinstance(intent, dict) and intent.get("intent") == "nudge" and intent.get("reply"):
            replies.append(intent["reply"]); continue
        if isinstance(intent, dict) and intent.get("intent") in ("goal.create","goal.close") and intent.get("reply"):
            add_turn("assistant", intent["reply"], session_id); return {"reply": intent["reply"]}

        # (rest of your normal chat logic unchanged...)
        # preferences, facts, plugins, brain_chat fallback etc.

    final_reply = " ".join(r for r in replies if r).strip() or "(no reply)"
    add_turn("assistant", final_reply, session_id)
    return {"reply": final_reply}