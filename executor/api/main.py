# executor/api/main.py — Echo 2.9.5 (clause pre-split, topic-aware domain)
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
from executor.core.semantic_intent import analyze as analyze_intent
from executor.utils.session_context import set_last_fact, get_last_fact, get_topic
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

def _session_id(request: Request, body: ChatBody) -> str:
    return body.session_id or request.headers.get("X-Session-ID") or "default"

@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Echo API is running."}

@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})

# --- small helper to apply writes for updates (used by clause path)
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
    add_turn("user", text, session_id=session_id)

    # --- 0) Clause pre-split (2.9.5 bridge): handle multi-intent before main pipeline
    clauses = gmem.split_clauses(text)
    if len(clauses) > 1:
        replies: list[str] = []
        for clause in clauses:
            sub_intent = analyze_intent(clause)
            print(f"[SemanticIntent:Clause] {sub_intent}")
            sub_intent = reason_about_context(sub_intent, clause, session_id=session_id)
            # Try to apply writes for sub-intents (location/fact updates)
            r = _apply_update(sub_intent, session_id)
            if r:
                replies.append(r)
        if replies:
            return {"reply": " ".join(r for r in replies if r)}

    # --- 1) Semantic intent + context reasoning
    intent = analyze_intent(text)
    print(f"[SemanticIntent] {intent}")
    intent = reason_about_context(intent, text, session_id=session_id)

    domain: Optional[str] = intent.get("domain")
    key_raw: Optional[str] = intent.get("key")
    value_raw: Optional[str] = intent.get("value")
    scope: Optional[str] = intent.get("scope")
    key = gmem.canonicalize_key(key_raw) if key_raw else None
    value = sanitize_value(value_raw) if value_raw else value_raw

    # --- Topic-aware override: if topic exists and domain is weak/ambiguous
    topic = get_topic(session_id)
    if topic and key and (not domain or domain in ("misc", "favorite", "current")):
        inferred = gmem.detect_domain_from_key(f"{topic} {key}")
        if inferred:
            domain = inferred

    # --- 2) Resolve defaults
    if intent["intent"] in ("fact.update", "fact.delete", "fact.query") and (not domain or not key):
        last_dom, last_key = get_last_fact(session_id)
        if not domain: domain = last_dom
        if not key:    key    = gmem.canonicalize_key(last_key) if last_key else None
    if intent["intent"].startswith("fact") and not domain and key:
        domain = gmem.detect_domain_from_key(key)

    try:
        # --- 3) Location updates/queries
        if intent["intent"] == "location.update" and scope and key == scope:
            if (not value) or re.search(r"\b(but|and|then)\b", text, re.I):
                confirm = gmem.extract_and_save_location(text)
                if confirm:
                    set_last_fact(session_id, "location", key)
                    add_turn("assistant", confirm, session_id)
                    return {"reply": confirm}
                else:
                    print("[LocationUpdateWarning] No value extracted; skipping write.")
            else:
                gmem.upsert_node("location", key, value, scope=scope)
                set_last_fact(session_id, "location", key)
                reply = f"Got it — your {key} location is {value}."
                add_turn("assistant", reply, session_id)
                return {"reply": reply}

        if intent["intent"] == "location.query" and scope and key == scope:
            node = gmem.get_node("location", key, scope=scope)
            set_last_fact(session_id, "location", key)
            msg = (
                f"You live in {node['value']}." if key == "home" and node else
                f"You're currently in {node['value']}." if key == "current" and node else
                f"Your trip destination is {node['value']}." if key == "trip" and node else
                "I'm not sure where you are right now."
            )
            add_turn("assistant", msg, session_id)
            return {"reply": msg}

        # --- 4) Generic facts
        if intent["intent"] == "fact.update" and domain and key and value:
            detected = gmem.detect_domain_from_key(key)
            if detected and detected != domain:
                domain = detected
            if domain == "location" and key in ("home","current","trip"):
                gmem.delete_node(domain, key, scope=key)
                gmem.upsert_node(domain, key, value, scope=key)
            else:
                gmem.upsert_node(domain, key, value, scope="global")
            set_last_fact(session_id, domain, key)
            reply = f"Got it — your {key} is {value}."
            add_turn("assistant", reply, session_id)
            return {"reply": reply}

        if intent["intent"].startswith("fact.query") and key:
            if not domain:
                domain = gmem.detect_domain_from_key(key)
            node = gmem.get_node(domain, key, scope="global")
            set_last_fact(session_id, domain, key)
            msg = (f"Your {key} is {node['value']}."
                   if node and node.get("value")
                   else f"I’m not sure about your {key}. Tell me and I’ll remember it.")
            add_turn("assistant", msg, session_id)
            return {"reply": msg}

        if intent["intent"] == "fact.delete" and domain and key:
            for sc in gmem.get_all_scopes_for_domain(domain):
                gmem.delete_node(domain, key, sc)
            set_last_fact(session_id, domain, key)
            msg = f"Okay — I’ve cleared your {key}. What should it be now?"
            add_turn("assistant", msg, session_id)
            return {"reply": msg}

    except Exception as e:
        print("[SemanticMemoryError]", e)

    # --- 5) Legacy helper fallback
    try:
        confirm = gmem.extract_and_save_location(text)
        if confirm:
            set_last_fact(session_id, "location", "trip")
            add_turn("assistant", confirm, session_id)
            return {"reply": confirm}

        maybe_loc = gmem.answer_location_question(text)
        if maybe_loc:
            set_last_fact(session_id, "location", "trip")
            add_turn("assistant", maybe_loc, session_id)
            return {"reply": maybe_loc}

        g_fact_confirm = gmem.extract_and_save_fact(text)
        if g_fact_confirm:
            m = re.search(r"\bmy\s+([\w\s]+?)\s+(?:is|was|=|'s)\s+", text, re.I)
            if m:
                k = gmem.canonicalize_key(m.group(1))
                set_last_fact(session_id, gmem.detect_domain_from_key(k), k)
            add_turn("assistant", g_fact_confirm, session_id)
            return {"reply": g_fact_confirm}
    except Exception as e:
        print("[LegacyPathError]", e)

    # --- 6) Router or brain fallback
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

    # --- 7) Plugin dispatch
    action = actions[0]; plugin = action.get("plugin"); args = action.get("args", {})
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

@app.on_event("startup")
def startup_message() -> None:
    print("✅ Echo API started — Phase 2.9.5 (clause pre-split + topic-aware domain).")