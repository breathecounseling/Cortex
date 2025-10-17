"""
executor/api/main.py
--------------------
Phase 2.15 — Temporal + NBA + Goal Switching + Deadlines
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
from executor.core.inference_engine import infer_contextual_preferences

# Goals + Resume + Scheduler
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
        # optional background scheduler (safe in single-instance dev)
        start_scheduler(interval_s=600)
    except Exception as e:
        print("[SchedulerStartupError]", e)

# -------------------- root/health --------------------
@app.get("/")
def root() -> Dict[str, Any]: return {"status": "ok", "message": "Echo API is running."}

@app.get("/health", include_in_schema=False)
def health(): return JSONResponse({"status": "ok"})

# -------------------- inference refresh --------------------
@app.get("/refresh_inference")
def refresh_inference():
    data = infer_contextual_preferences()
    return {"status": "ok", "inferred": len(data)}

# -------------------- goals API --------------------
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

@app.get("/goals/resume")
def goals_resume(session_id: Optional[str] = None):
    sid = session_id or "default"
    text = build_resume_prompt(sid)
    return {"status": "ok", "reply": text or "No open goal to resume."}

# -------------------- temporal checks endpoint --------------------
@app.get("/check_reminders")
def check_reminders():
    """
    For Fly cron or manual ping. Returns all nudges/deadlines/NBA messages
    computed by the scheduler across sessions (no push; poll & display).
    """
    msgs = check_all_sessions()
    return {"count": len(msgs), "messages": msgs}

# -------------------- context builder for LLM --------------------
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
            context.insert(0, {"role":"system","content": f"Known facts: {json.dumps(facts)}"})
    except Exception as e:
        print("[InjectFactsError]", e)
    try:
        summaries = retrieve_topic_summaries(query, k=3)
        if summaries:
            context.insert(0, {"role":"system","content":"\n".join(summaries)})
    except Exception as e:
        print("[VectorSummaryError]", e)
    try:
        refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if refs:
            context.insert(0, {"role":"system","content":"\n".join(refs)})
    except Exception as e:
        print("[VectorRecallError]", e)
    return context

# -------------------- main chat --------------------
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

    # Explicit topic change
    m_topic = re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b(.+)$", text)
    if m_topic:
        topic = m_topic.group(2).strip(" .!?")
        if topic:
            set_topic(session_id, topic)

    replies: list[str] = []

    for p in parsed_intents:
        intent = reason_about_context(p, text, session_id=session_id)

        # reasoner direct reply (nudge/goal.*)
        if isinstance(intent, dict) and intent.get("reply") and intent.get("intent") in {
            "nudge","goal.create","goal.close","goal.resume","goal.switch","goal.deadline"
        }:
            replies.append(intent["reply"])
            if intent.get("intent") in {"goal.create","goal.close","goal.resume","goal.switch","goal.deadline"}:
                final_reply = " ".join(r for r in replies if r).strip()
                add_turn("assistant", final_reply, session_id)
                return {"reply": final_reply}
            continue

        # guard: reasoner reply without "intent"
        if not isinstance(intent, dict) or "intent" not in intent:
            if isinstance(intent, dict) and "reply" in intent:
                replies.append(intent["reply"]); continue
            replies.append("I’m not sure how to handle that request right now."); continue

        # consent/reflective
        if intent.get("intent") == "reflective.question" or (intent.get("intimacy", 0) > intimacy_level):
            replies.append("If you want me to go deeper here, I can ask a more personal question. Would you like that?")
            continue

        # temporal recall (pre-filled)
        if intent.get("intent") == "temporal.recall" and intent.get("reply"):
            replies.append(intent["reply"]); continue

        # location queries
        if intent["intent"] == "location.query" and intent.get("scope") and intent.get("key"):
            node = gmem.get_node("location", intent["key"], scope=intent["scope"])
            if intent["key"] == "home":
                replies.append(f"You live in {node['value']}." if node else "I'm not sure where you live.")
            elif intent["key"] == "current":
                replies.append(f"You're currently in {node['value']}." if node else "I'm not sure where you are right now.")
            else:
                replies.append(f"Your trip destination is {node['value']}." if node else "I don't have a trip destination yet.")
            set_last_fact(session_id, "location", intent["key"]); continue

        # fact queries
        if intent["intent"].startswith("fact.query") and intent.get("key"):
            domain = intent.get("domain") or gmem.detect_domain_from_key(intent["key"])
            node = gmem.get_node(domain, intent["key"], scope="global")
            replies.append(
                f"Your {intent['key']} is {node['value']}."
                if node and node.get("value") else
                f"I’m not sure about your {intent['key']}. Tell me and I’ll remember it."
            )
            set_last_fact(session_id, domain, intent["key"]); continue

        # preference queries
        if intent.get("intent") == "preference.query":
            qdom = intent.get("domain") or gmem.detect_domain_from_key(intent.get("key") or "")
            if qdom == "food":
                likes = [p["item"] for p in get_preferences("food", min_strength=0.0) if p["polarity"] > 0]
                dislikes = [p["item"] for p in get_dislikes("food")]
                parts = []
                if likes: parts.append(f"you love {', '.join(sorted(set(likes)))}")
                if dislikes: parts.append(f"you don't like {', '.join(sorted(set(dislikes)))}")
                replies.append("Based on what you've shared, " + " and ".join(parts) + ".")
            elif qdom == "ui":
                likes = [p["item"] for p in get_preferences("ui", min_strength=0.0) if p["polarity"] > 0]
                replies.append(
                    f"You like these layout styles: {', '.join(sorted(set(likes)))}."
                    if likes else "I don't have any saved layout preferences yet."
                )
            else:
                replies.append("I can check what you like if you tell me the category (e.g., foods, layouts).")
            continue

        # preferences (persist)
        if intent["intent"] == "preference.statement" and intent.get("key"):
            item = intent["key"]; polarity = +1 if intent.get("polarity") == 1 else -1
            try:
                domain = intent.get("domain") or gmem.detect_domain_from_key(item)
                record_preference(domain, item, polarity=polarity, strength=0.8, source="parser")
            except Exception as e:
                print("[PreferenceWriteError]", e)
            replies.append(f"Noted — you {('like' if polarity > 0 else 'don’t like')} {item}.")
            continue

        # negation delete
        if intent.get("intent") == "fact.delete" and intent.get("domain") and intent.get("key"):
            for sc in gmem.get_all_scopes_for_domain(intent["domain"]):
                gmem.delete_node(intent["domain"], intent["key"], sc)
            set_last_fact(session_id, intent["domain"], intent["key"])
            replies.append(f"Okay — I’ve cleared your {intent['key']}. What should it be now?")
            continue

        # updates
        if intent.get("intent") == "fact.update" and intent.get("key") and intent.get("value"):
            domain = intent.get("domain") or gmem.detect_domain_from_key(intent["key"])
            val = sanitize_value(intent["value"])
            gmem.upsert_node(domain, intent["key"], val, scope="global")
            set_last_fact(session_id, domain, intent["key"])
            replies.append(f"Got it — your {intent['key']} is {val}.")
            continue

        # planning handoff
        if intent.get("intent") in ("goal.statement", "project.request"):
            frame = reason_about_goal(text, session_id=session_id)
            context = gather_design_context(frame.get("goal"), session_id=session_id)
            ui_palette = context["ui_prefs"].get("palette")
            shape = context["ui_prefs"].get("shape_pref")
            food_likes = context["domain_prefs"].get("food", {}).get("likes", [])
            hint_parts = []
            if ui_palette: hint_parts.append(f"I’ll use your {ui_palette} palette")
            if shape: hint_parts.append(f"and keep the {shape} style")
            if food_likes: hint_parts.append(f"and remember you like {', '.join(food_likes[:2])}")
            hint = " ".join(hint_parts).strip()
            q2 = clarifying_line(frame["next_question"])
            replies.append(f"{hint}. {q2}" if hint else q2); continue

    # Fallback: router/brain
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
            try:
                add_turn("assistant", reply, session_id)
                remember_exchange("user", text)
                remember_exchange("assistant", reply)
                store_vector("user", text)
                store_vector("assistant", reply)
                summarize_if_needed()
            except Exception as e:
                print("[VectorStoreError]", e)
            return {"reply": reply}
        action = actions[0]; plugin = action.get("plugin"); args = action.get("args", {})
        try:
            if plugin == "web_search": result = web_search.handle(args)
            elif plugin == "weather_plugin": result = weather_plugin.handle(args)
            elif plugin == "google_places": result = google_places.handle(args)
            elif plugin == "feedback": result = feedback.handle(args)
            else: result = {"status": "ok", "summary": router_output.get("assistant_message", "Okay.")}
            summary = result.get("summary") or ""
            if len(summary.strip()) < 40:
                context_block = build_context_with_retrieval(text)
                try:
                    reply = brain_chat(
                        f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally.",
                        context=context_block,
                    ); add_turn("assistant", reply, session_id); return {"reply": reply}
                except Exception as e:
                    print("[ReflectionError]", e)
            add_turn("assistant", summary, session_id); return {"reply": summary}
        except Exception as e:
            print("[PluginError]", e); return {"reply": f"Plugin error ({plugin}): {e}"}

    final_reply = " ".join(r for r in replies if r).strip()
    add_turn("assistant", final_reply, session_id)
    return {"reply": final_reply}