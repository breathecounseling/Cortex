# executor/api/main.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Core routers + interpreters
from executor.core.router import route
from executor.core.language_intent import classify_language_intent
from executor.core.intent_facts import detect_fact_or_question

# Plugins
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback

# Brain + memory
from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
    save_fact,
    load_fact,
    list_facts,
    update_or_delete_from_text,
)
from executor.utils.vector_memory import (
    store_vector,
    summarize_if_needed,
    retrieve_topic_summaries,
    hierarchical_recall,
)

app = FastAPI()

# Mount frontend if present
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=_frontend_dir.as_posix(), html=True), name="ui")


class ChatBody(BaseModel):
    text: str | None = None
    boost: bool | None = False
    system: str | None = None


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def inject_facts(context: list[dict[str, str]]) -> list[dict[str, str]]:
    """Insert known user facts at the top of the context."""
    try:
        facts = list_facts()
        if facts:
            context.insert(
                0,
                {"role": "system", "content": f"Known user facts: {json.dumps(facts)}"},
            )
    except Exception as e:
        print("[InjectFactsError]", e)
    return context


def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    """Build multi-layer recall context."""
    context: list[dict[str, str]] = []
    try:
        init_db_if_needed()
        context = recall_context(limit=8)
    except Exception as e:
        print("[ContextRecallError]", e)
        context = []
    context = inject_facts(context)
    try:
        summaries = retrieve_topic_summaries(query, k=3)
        if summaries:
            context.insert(0, {"role": "system", "content": "\n".join(summaries)})
    except Exception as e:
        print("[VectorMemorySummaryError]", e)
    try:
        deep_refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if deep_refs:
            context.insert(0, {"role": "system", "content": "\n".join(deep_refs)})
    except Exception as e:
        print("[VectorMemoryDetailError]", e)
    return context


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}


@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    """Unified chat endpoint with semantic and language intent classification."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    text = (body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or "").strip()
    if not text:
        return {"reply": "How can I help?"}

    # -----------------------------------------------------------------------
    # 🧩 Stage 1 — Language-level intent
    # -----------------------------------------------------------------------
    lang_intent = classify_language_intent(text)
    print(f"[LangIntent] {lang_intent} :: {text}")

    # -----------------------------------------------------------------------
    # 🧠 Stage 2 — Semantic interpretation (facts)
    # -----------------------------------------------------------------------
    if lang_intent in {"declaration", "question", "meta"}:
        fact_intent = detect_fact_or_question(text)
        intent_type = fact_intent.get("type")
        key, val = fact_intent.get("key"), fact_intent.get("value")

        if intent_type == "fact.correction":
            update_or_delete_from_text(text)
        elif intent_type == "fact.declaration" and key and val:
            print(f"[FactCapture] {key} = {val}")
            save_fact(key, val)
            return {"reply": f"Got it! Your {key} is {val}."}
        elif intent_type == "fact.query" and key:
            known = load_fact(key)
            if known:
                return {"reply": f"Your {key} is {known}."}

    # -----------------------------------------------------------------------
    # ⚙️ Stage 3 — Commands, meta actions, and builder integration
    # -----------------------------------------------------------------------
    if lang_intent == "command":
        # This is where Cortex can later dispatch builder, planner, or plugin actions
        # e.g. "add milk to my shopping list", "create a new module"
        # For now, we’ll stub routing into a future task planner
        text_lower = text.lower()
        if "add" in text_lower and "list" in text_lower:
            return {"reply": "✅ Added that item to your list (stub)."}
        if "remind" in text_lower or "reminder" in text_lower:
            return {"reply": "⏰ Reminder set (stub)."}
        if "plan" in text_lower or "module" in text_lower or "build" in text_lower:
            return {"reply": "🧩 Starting feature planning (stub for builder integration)."}
        # Fallback if command unrecognized
        return {"reply": "Command recognized — but I don’t yet have a handler for that action."}

    # -----------------------------------------------------------------------
    # 🌐 Stage 4 — Normal routing (plugins or brain)
    # -----------------------------------------------------------------------
    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}

    actions = router_output.get("actions", [])
    if not actions:
        try:
            context = build_context_with_retrieval(text)
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

    # -----------------------------------------------------------------------
    # 🔌 Stage 5 — Plugin dispatch
    # -----------------------------------------------------------------------
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
        summary = result.get("summary") or ""
        if len(summary.strip()) < 40 or summary.lower().startswith(("no ", "error", "none")):
            context = build_context_with_retrieval(text)
            reply = brain_chat(
                f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally or fill in any missing information.",
                context=context,
            )
            return {"reply": reply}
        return {"reply": summary}
    except Exception as e:
        return {"reply": f"Plugin error ({plugin}): {e}"}


@app.post("/execute")
def execute(body: Dict[str, Any]) -> Dict[str, Any]:
    """Direct execution for plugin and command testing."""
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