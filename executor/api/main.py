from __future__ import annotations
import os, json, re
from pathlib import Path
from typing import Any, Dict
from executor.utils.sanitizer import sanitize_value

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Core router + plugins
from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback

# 🧠 Brain + flat memory
from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
    save_fact,
    list_facts,
    update_or_delete_from_text,
)

# Vector memory (safe to keep on; summarization optional)
from executor.utils.vector_memory import (
    store_vector,
    summarize_if_needed,
    retrieve_topic_summaries,
    hierarchical_recall,
)

# 🌐 Graph Memory (locations + general facts)
from executor.utils import memory_graph as gmem

app = FastAPI()

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=_frontend_dir.as_posix(), html=True), name="ui")


class ChatBody(BaseModel):
    text: str | None = None
    boost: bool | None = False
    system: str | None = None


# ------------------------------------------------------------
# Helper utilities
# ------------------------------------------------------------
def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    """Build recent chat + summaries + vector recall context."""
    context: list[dict[str, str]] = []
    try:
        init_db_if_needed()
        context = recall_context(limit=8)
    except Exception as e:
        print("[ContextRecallError]", e)
        context = []

    # Facts (inject for persistent memory)
    try:
        facts = list_facts()
        if facts:
            context.insert(
                0,
                {"role": "system", "content": f"Known facts: {json.dumps(facts)}"},
            )
    except Exception as e:
        print("[InjectFactsError]", e)

    # Summaries + long-term recall
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


# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}


@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    """Main conversational endpoint with semantic + graph memory."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    text = (
        body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or ""
    ).strip()
    if not text:
        return {"reply": "How can I help?"}

    # 1️⃣ Semantic classification
    from executor.core.language_intent import classify_language_intent
    from executor.core.intent_facts import detect_fact_or_question
    lang_type = classify_language_intent(text)
    semantic = detect_fact_or_question(text)
    print(f"[LangIntent] {lang_type} :: {text}")

    # 2️⃣ Handle forget/correction
    try:
        g_forget = gmem.forget_fact_or_location(text)
        if g_forget:
            return {"reply": g_forget}
    except Exception as e:
        print("[ForgetError.Graph]", e)

    # 3️⃣ Handle location logic
    try:
        confirm = gmem.extract_and_save_location(text)
        if confirm:
            return {"reply": confirm}
        maybe_loc = gmem.answer_location_question(text)
        if maybe_loc:
            return {"reply": maybe_loc}
    except Exception as e:
        print("[GraphLocationError]", e)

    # 4️⃣ Handle fact declarations / queries via graph
    try:
        # Declarative (regex-level)
        g_fact_confirm = gmem.extract_and_save_fact(text)
        if g_fact_confirm:
            return {"reply": g_fact_confirm}

        # Semantic declaration (LLM-level)
        if semantic["type"] == "fact.declaration" and semantic.get("key") and semantic.get("value"):
            domain = gmem.detect_domain_from_key(semantic["key"])
            value = sanitize_value(semantic["value"])
            gmem.upsert_node(domain, semantic["key"], value, scope="global")
            print(f"[Graph] Upserted: {domain}.{semantic['key']} = {value}")
            return {"reply": f"Got it — your {semantic['key']} is {value}."}

        # Queries
        if semantic["type"] == "fact.query" and semantic.get("key"):
            domain = gmem.detect_domain_from_key(semantic["key"])
            node = gmem.get_node(domain, semantic["key"], scope="global")
            if node and node.get("value"):
                return {"reply": f"Your {semantic['key']} is {node['value']}."}
            return {"reply": f"I’m not sure about your {semantic['key']}. Tell me and I’ll remember it."}
    except Exception as e:
        print("[GraphFactError]", e)

    # 5️⃣ Route via router or fall back to brain
    try:
        router_output = route(text)
    except Exception as e:
        print("[RouterError]", e)
        return {"reply": f"Router error: {e}"}

    actions = router_output.get("actions", [])
    if not actions:
        context = build_context_with_retrieval(text)
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

    # 6️⃣ Plugin dispatch
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
            context = build_context_with_retrieval(text)
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


@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
def startup_message() -> None:
    print("✅ Cortex API started — Phase 2.8 semantic baseline with scoped context.")