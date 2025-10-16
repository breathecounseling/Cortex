# executor/api/main.py — Phase 2.10a.1 (semantic parser + consent gate; delete confirmation)
from __future__ import annotations
import os, json, re
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
    set_last_fact, get_last_fact,
    set_topic, get_topic,
    set_intimacy, get_intimacy
)
from executor.utils.turn_memory import add_turn
from executor.core.context_reasoner import reason_about_context, build_context_block
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
    store_vector, summarize_if_needed,
    retrieve_topic_summaries, hierarchical_recall
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
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Echo API is running."}

@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})

def _apply_update(intent: Dict[str, Any], session_id: str) -> Optional[str]:
    domain = intent.get("domain")
    key    = gmem.canonicalize_key(intent.get("key")) if intent.get("key") else None
    scope  = intent.get("scope")
    value  = sanitize_value(intent.get("value")) if intent.get("value") else None

    if intent.get("intent") == "location.update" and key in ("home","current","trip") and value:
        gmem.upsert_node("location", key, value, scope=key)
        set_last_fact(session_id, "location", key)
        return f"Got it — your {key} location is {value}."

    if intent.get("intent") == "fact.update" and domain and key and value:
        detected = gmem.detect_domain_from_key(key)
        domain = detected or domain
        if domain == "location" and key in ("home","current","trip"):
            gmem.delete_node(domain, key, scope=key)
            gmem.upsert_node(domain, key, value, scope=key)
        else:
            gmem.upsert_node(domain, key, value, scope="global")
        set_last_fact(session_id, domain, key)
        return f"Got it — your {key} is {value}."
    return None

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

    # 1) Parse into (possibly multiple) intents
    parsed_intents = parse_message(text, intimacy_level=intimacy_level)

    # 1a) Topic setter (parser already emits smalltalk; we persist the label here)
    m_topic = re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b(.+)$", text)
    if m_topic:
        topic = m_topic.group(2).strip(" .!?")
        if topic:
            set_topic(session_id, topic)

    replies: list[str] = []

    for p in parsed_intents:
        intent = reason_about_context(p, text, session_id=session_id)

        # Consent gate for reflective items
        if intent.get("intent") == "reflective.question" or (intent.get("intimacy", 0) > intimacy_level):
            replies.append("If you want me to go deeper here, I can ask a more personal question. Would you like that?")
            continue

        # Location queries
        if intent["intent"] == "location.query" and intent.get("scope") and intent.get("key"):
            node = gmem.get_node("location", intent["key"], scope=intent["scope"])
            if intent["key"] == "home":
                replies.append(f"You live in {node['value']}." if node else "I'm not sure where you live.")
            elif intent["key"] == "current":
                replies.append(f"You're currently in {node['value']}." if node else "I'm not sure where you are right now.")
            else:
                replies.append(f"Your trip destination is {node['value']}." if node else "I don't have a trip destination yet.")
            set_last_fact(session_id, "location", intent["key"])
            continue

        # Fact queries
        if intent["intent"].startswith("fact.query") and intent.get("key"):
            domain = intent.get("domain") or gmem.detect_domain_from_key(intent["key"])
            node = gmem.get_node(domain, intent["key"], scope="global")
            replies.append(f"Your {intent['key']} is {node['value']}." if node and node.get("value")
                           else f"I’m not sure about your {intent['key']}. Tell me and I’ll remember it.")
            set_last_fact(session_id, domain, intent["key"])
            continue

        # Preferences (ack only; Phase 2.11 will persist weighted prefs)
        if intent["intent"] == "preference.statement" and intent.get("key"):
            replies.append(f"Noted — you {('like' if intent.get('polarity')==1 else 'don’t like')} {intent['key']}.")
            continue

        # Negation → delete confirmation
        if intent.get("intent") == "fact.delete" and intent.get("domain") and intent.get("key"):
            # perform deletes across scopes for consistency with 2.9
            for sc in gmem.get_all_scopes_for_domain(intent["domain"]):
                gmem.delete_node(intent["domain"], intent["key"], sc)
            set_last_fact(session_id, intent["domain"], intent["key"])
            replies.append(f"Okay — I’ve cleared your {intent['key']}. What should it be now?")
            continue

        # Updates
        write_reply = _apply_update(intent, session_id)
        if write_reply:
            replies.append(write_reply)

    if not replies:
        # router/brain fallback
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

        # plugin dispatch
        action = actions[0]
        plugin = action.get("plugin"); args = action.get("args", {})
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
            summary = result.get("summary") or ""
            if len(summary.strip()) < 40:
                context_block = build_context_block(text, session_id=session_id)
                try:
                    reply = brain_chat(
                        f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally.",
                        context=[{"role": "system", "content": context_block}],
                    )
                    add_turn("assistant", reply, session_id)
                    return {"reply": reply}
                except Exception as e:
                    print("[ReflectionError]", e)
            add_turn("assistant", summary, session_id)
            return {"reply": summary}
        except Exception as e:
            print("[PluginError]", e)
            return {"reply": f"Plugin error ({plugin}): {e}"}

    final_reply = " ".join(r for r in replies if r).strip()
    add_turn("assistant", final_reply, session_id)
    return {"reply": final_reply}