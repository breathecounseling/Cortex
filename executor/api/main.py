# executor/api/main.py
from __future__ import annotations
import os, json, re
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Sanitizer + Graph
from executor.utils.sanitizer import sanitize_value
from executor.utils import memory_graph as gmem

# Unified semantic intent + persistent session context
from executor.core.semantic_intent import analyze as analyze_intent
from executor.utils.session_context import set_last_fact, get_last_fact

# Router + plugins + brain + classic memory/vector (unchanged integrations)
from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback

from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
    save_fact,
    list_facts,
    update_or_delete_from_text,
)

from executor.utils.vector_memory import (
    store_vector,
    summarize_if_needed,
    retrieve_topic_summaries,
    hierarchical_recall,
)

# ------------------------------------------------------------
# FastAPI setup
# ------------------------------------------------------------
app = FastAPI()

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=_frontend_dir.as_posix(), html=True), name="ui")

class ChatBody(BaseModel):
    text: str | None = None
    boost: bool | None = False
    system: str | None = None
    session_id: str | None = None  # optional caller-provided session id

# ------------------------------------------------------------
def _session_id(request: Request, body: ChatBody) -> str:
    return body.session_id or request.headers.get("X-Session-ID") or "default"

def _inject_context_messages(query: str) -> list[dict[str,str]]:
    ctx: list[dict[str,str]] = []
    try:
        init_db_if_needed()
        ctx = recall_context(limit=8)
    except Exception as e:
        print("[ContextRecallError]", e)
        ctx = []
    try:
        facts = list_facts()
        if facts:
            ctx.insert(0, {"role":"system","content": f"Known facts: {json.dumps(facts)}"})
    except Exception as e:
        print("[InjectFactsError]", e)
    try:
        summaries = retrieve_topic_summaries(query, k=3)
        if summaries:
            ctx.insert(0, {"role":"system","content":"\n".join(summaries)})
    except Exception as e:
        print("[VectorSummaryError]", e)
    try:
        refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if refs:
            ctx.insert(0, {"role":"system","content":"\n".join(refs)})
    except Exception as e:
        print("[VectorRecallError]", e)
    return ctx

# ------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}

@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})

# ------------------------------------------------------------
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

    # 1) Unified semantic intent
    intent = analyze_intent(text)
    print(f"[SemanticIntent] {intent}")

    # 2) Resolve domain/key/value with persistence + canonicalization
    #    - If analyzer omitted domain/key in corrections, use persistent last fact
    domain: Optional[str] = intent.get("domain")
    key_raw: Optional[str] = intent.get("key")
    value_raw: Optional[str] = intent.get("value")
    scope: Optional[str] = intent.get("scope")
    key = gmem.canonicalize_key(key_raw) if key_raw else None
    value = sanitize_value(value_raw) if value_raw else value_raw

    if intent["intent"] in ("fact.update", "fact.delete", "fact.query") and (not domain or not key):
        # Try session context
        last_dom, last_key = get_last_fact(session_id)
        if not domain: domain = last_dom
        if not key: key = gmem.canonicalize_key(last_key) if last_key else None

    # Infer domain from key if still missing (color/food/location/misc)
    if (intent["intent"].startswith("fact") and not domain and key):
        domain = gmem.detect_domain_from_key(key)

    # 3) Execute memory action
    try:
        # --- Location updates/queries (authoritative via analyzer) ---
        if intent["intent"] == "location.update" and scope and key == scope:
            # store and set session context for follow-ups
            gmem.upsert_node("location", key, value, scope=scope)
            set_last_fact(session_id, "location", key)
            return {"reply": f"Got it — your {key} location is {value}."}

        if intent["intent"] == "location.query" and scope and key == scope:
            node = gmem.get_node("location", key, scope=scope)
            set_last_fact(session_id, "location", key)
            if key == "home":
                return {"reply": f"You live in {node['value']}."} if node else {"reply":"I'm not sure where you live."}
            if key == "current":
                return {"reply": f"You're currently in {node['value']}."} if node else {"reply":"I'm not sure where you are right now."}
            if key == "trip":
                return {"reply": f"Your trip destination is {node['value']}."} if node else {"reply":"I don't have a trip destination yet."}

        # --- Generic facts ---
        if intent["intent"] == "fact.update" and domain and key and value:
            gmem.upsert_node(domain, key, value, scope="global")
            set_last_fact(session_id, domain, key)
            return {"reply": f"Got it — your {key} is {value}."}

        if intent["intent"] == "fact.query" and domain and key:
            node = gmem.get_node(domain, key, scope="global")
            set_last_fact(session_id, domain, key)
            if node and node.get("value"):
                return {"reply": f"Your {key} is {node['value']}."}
            return {"reply": f"I’m not sure about your {key}. Tell me and I’ll remember it."}

        if intent["intent"] == "fact.delete" and domain and key:
            # delete across all scopes for robustness in 2.8.x
            for sc in gmem.get_all_scopes_for_domain(domain):
                gmem.delete_node(domain, key, sc)
            set_last_fact(session_id, domain, key)
            return {"reply": f"Got it — I’ve forgotten your {key}."}
    except Exception as e:
        print("[SemanticMemoryError]", e)

    # 4) Fallback to legacy helpers for broader regex support (keeps existing features intact)
    #    These also end up updating session context.
    try:
        confirm = gmem.extract_and_save_location(text)
        if confirm:
            # set session context heuristically (trip = default for location queries)
            set_last_fact(session_id, "location", "trip")
            return {"reply": confirm}
        maybe_loc = gmem.answer_location_question(text)
        if maybe_loc:
            set_last_fact(session_id, "location", "trip")
            return {"reply": maybe_loc}

        g_fact_confirm = gmem.extract_and_save_fact(text)
        if g_fact_confirm:
            # best effort: infer from sentence
            m = re.search(r"\bmy\s+([\w\s]+?)\s+(?:is|was|=|'s)\s+", text, re.I)
            if m:
                k = gmem.canonicalize_key(m.group(1))
                set_last_fact(session_id, gmem.detect_domain_from_key(k), k)
            return {"reply": g_fact_confirm}
    except Exception as e:
        print("[LegacyPathError]", e)

    # 5) If we reach here, route to plugins or brain
    try:
        router_output = route(text)
    except Exception as e:
        print("[RouterError]", e)
        return {"reply": f"Router error: {e}"}

    actions = router_output.get("actions", [])
    if not actions:
        context = _inject_context_messages(text)
        try:
            reply = brain_chat(text, context=context)
        except Exception as e:
            reply = f"(brain offline) {e}"

        try:
            remember_exchange("user", text)
            remember_exchange("assistant", reply)
            store_vector("user", text)
            store_vector("assistant", reply)
            summarize_if_needed()
        except Exception as e:
            print("[VectorStoreError]", e)
        return {"reply": reply}

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
            result = {
                "status": "ok",
                "summary": router_output.get("assistant_message", "Okay."),
            }

        summary = result.get("summary") or ""
        if len(summary.strip()) < 40:
            context = _inject_context_messages(text)
            try:
                reply = brain_chat(
                    f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally.",
                    context=context,
                )
                return {"reply": reply}
            except Exception as e:
                print("[ReflectionError]", e)
        return {"reply": summary}
    except Exception as e:
        print("[PluginError]", e)
        return {"reply": f"Plugin error ({plugin}): {e}"}