"""
executor/api/main.py
--------------------
Phase 2.15 — Temporal + NBA + Goal Switching + Deadlines (stable)
"""

from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Core + Reasoning
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
from executor.core.inference_engine import suggest_next_goal, infer_contextual_preferences

# Goals + Scheduler
from executor.utils.goals import list_goals, close_goal, get_most_recent_open
from executor.utils.goal_resume import build_resume_prompt
from executor.utils.scheduler import check_all_sessions, start_scheduler

# Router / Plugins / Brain
from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback
from executor.ai.router import chat as brain_chat

# Memory + Vectors
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
    return request.headers.get("X-Session-ID") or body.session_id or "default"

@app.on_event("startup")
def _startup():
    try:
        start_scheduler(interval_s=600)
    except Exception as e:
        print("[SchedulerStartupError]", e)

@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Echo API running."}

@app.get("/health", include_in_schema=False)
def health(): return JSONResponse({"status": "ok"})

@app.get("/goals")
def goals(session_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20):
    sid = session_id or "default"
    return {"goals": list_goals(sid, status=status, limit=limit)}

@app.get("/check_reminders")
def check_reminders():
    msgs = check_all_sessions()
    return {"count": len(msgs), "messages": msgs}

def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    context: list[dict[str, str]] = []
    try:
        init_db_if_needed()
        context = recall_context(limit=8)
    except Exception as e:
        print("[ContextRecallError]", e)
        context = []
    try:
        facts = list_facts()
        if facts:
            context.insert(0, {"role": "system", "content": f"Known facts: {json.dumps(facts)}"})
    except Exception as e:
        print("[InjectFactsError]", e)
    try:
        summaries = retrieve_topic_summaries(query, k=3)
        if summaries:
            context.insert(0, {"role": "system", "content": "\n".join(summaries)})
    except Exception as e:
        print("[VectorSummaryError]", e)
    try:
        refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if refs:
            context.insert(0, {"role": "system", "content": "\n".join(refs)})
    except Exception as e:
        print("[VectorRecallError]", e)
    return context

@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    text = (body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or "").strip()
    if not text:
        return {"reply": "How can I help?"}

    session_id = _session_id(request, body)
    if body.set_intimacy is not None:
        set_intimacy(session_id, body.set_intimacy)
    intimacy_level = get_intimacy(session_id)

    add_turn("user", text, session_id=session_id)
    parsed_intents = parse_message(text, intimacy_level=intimacy_level)

    m_topic = re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b(.+)$", text)
    if m_topic:
        topic = m_topic.group(2).strip(" .!?")
        if topic:
            set_topic(session_id, topic)

    replies: list[str] = []

    for p in parsed_intents:
        intent = reason_about_context(p, text, session_id=session_id)
        if isinstance(intent, dict) and intent.get("reply"):
            replies.append(intent["reply"])
            continue

        if not isinstance(intent, dict):
            replies.append("I’m not sure how to handle that request yet.")
            continue

        if intent.get("intent") == "reflective.question" or (intent.get("intimacy", 0) > intimacy_level):
            replies.append("If you want me to go deeper here, I can ask a more personal question. Would you like that?")
            continue

        if intent.get("intent") == "temporal.recall" and intent.get("reply"):
            replies.append(intent["reply"])
            continue

        if intent.get("intent") == "goal.suggest":
            replies.append(intent["reply"])
            continue

        if intent.get("intent") == "fact.query" and intent.get("key"):
            domain = intent.get("domain") or gmem.detect_domain_from_key(intent["key"])
            node = gmem.get_node(domain, intent["key"], scope="global")
            replies.append(
                f"Your {intent['key']} is {node['value']}."
                if node and node.get("value")
                else f"I’m not sure about your {intent['key']}. Tell me and I’ll remember it."
            )
            continue

        if intent.get("intent") == "preference.query":
            qdom = intent.get("domain") or gmem.detect_domain_from_key(intent.get("key") or "")
            likes = [p["item"] for p in get_preferences(qdom, min_strength=0.0) if p["polarity"] > 0]
            dislikes = [p["item"] for p in get_dislikes(qdom)]
            if likes or dislikes:
                summary = []
                if likes: summary.append(f"you like {', '.join(sorted(set(likes)))}")
                if dislikes: summary.append(f"you don’t like {', '.join(sorted(set(dislikes)))}")
                replies.append("Based on what you’ve shared, " + " and ".join(summary) + ".")
            else:
                replies.append(f"I don’t have much data on your {qdom} preferences yet.")
            continue

        if intent.get("intent") == "preference.statement" and intent.get("key"):
            item = intent["key"]
            polarity = +1 if intent.get("polarity") == 1 else -1
            try:
                domain = intent.get("domain") or gmem.detect_domain_from_key(item)
                record_preference(domain, item, polarity=polarity, strength=0.8, source="parser")
            except Exception as e:
                print("[PreferenceWriteError]", e)
            replies.append(f"Noted — you {('like' if polarity > 0 else 'don’t like')} {item}.")
            continue

    # fallback → route + LLM
    if not replies:
        try:
            router_output = route(text)
        except Exception as e:
            print("[RouterError]", e)
            return {"reply": f"Router error: {e}"}

        actions = router_output.get("actions", [])
        if not actions:
            context_block = build_context_block(text, session_id=session_id)
            try:
                reply = brain_chat(context_block)
            except Exception as e:
                reply = f"(brain offline) {e}"
            add_turn("assistant", reply, session_id)
            return {"reply": reply}

        action = actions[0]
        plugin = action.get("plugin")
        args = action.get("args", {})
        try:
            if plugin == "web_search": result = web_search.handle(args)
            elif plugin == "weather_plugin": result = weather_plugin.handle(args)
            elif plugin == "google_places": result = google_places.handle(args)
            elif plugin == "feedback": result = feedback.handle(args)
            else: result = {"status": "ok", "summary": router_output.get("assistant_message", "Okay.")}
            summary = result.get("summary") or ""
            if len(summary.strip()) < 40:
                context_block = build_context_with_retrieval(text)
                reply = brain_chat(
                    f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally.",
                    context=context_block,
                )
                add_turn("assistant", reply, session_id)
                return {"reply": reply}
            add_turn("assistant", summary, session_id)
            return {"reply": summary}
        except Exception as e:
            print("[PluginError]", e)
            return {"reply": f"Plugin error ({plugin}): {e}"}

    final_reply = " ".join(r for r in replies if r).strip()
    add_turn("assistant", final_reply, session_id)
    return {"reply": final_reply}