# executor/api/main.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Any, Dict
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

# 🧠 Brain + memory
from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
    save_fact,
    delete_fact,
    list_facts,
    update_or_delete_from_text,
)
from executor.utils.vector_memory import (
    store_vector,
    summarize_if_needed,
    retrieve_topic_summaries,
    hierarchical_recall,
)

# 🧩 Semantic understanding modules
from executor.core.language_intent import classify_language_intent
from executor.core.intent_facts import detect_fact_or_question

app = FastAPI()

# Mount frontend if built
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=_frontend_dir.as_posix(), html=True), name="ui")


class ChatBody(BaseModel):
    text: str | None = None
    boost: bool | None = False
    system: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def inject_facts(context: list[dict[str, str]]) -> list[dict[str, str]]:
    """Prepend known user facts to the LLM context."""
    try:
        facts = {k: v for k, v in list_facts().items() if k != "last_fact_query"}
        if facts:
            print(f"[InjectFacts] {json.dumps(facts, indent=2)}")
            context.insert(
                0,
                {
                    "role": "system",
                    "content": f"Known user facts: {json.dumps(facts)}",
                },
            )
    except Exception as e:
        print("[InjectFactsError]", e)
    return context


def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    """Build full context with recent messages, facts, and memory summaries."""
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
    """Main conversational endpoint."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}

    text = (body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or "").strip()
    if not text:
        return {"reply": "How can I help?"}

    # ROUTER phase (for plugins)
    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}

    actions = router_output.get("actions", [])

    # 🧠 No plugin actions → Semantic reasoning + memory
    if not actions:
        try:
            update_or_delete_from_text(text)

            # ─────────────────────────────────────────────
            # Semantic fact classification
            # ─────────────────────────────────────────────
            lang_intent = classify_language_intent(text)
            fact_intent = detect_fact_or_question(text)

            # Direct declaration ("My favorite color is blue")
            if fact_intent["type"] == "fact.declaration" and fact_intent["key"] and fact_intent["value"]:
                key = fact_intent["key"].strip().lower()
                val = fact_intent["value"].strip()
                print(f"[FactCapture.Semantic] {key} = {val}")
                save_fact(key, val)

            # Correction or update ("Actually it's green now")
            elif fact_intent["type"] == "fact.correction" and fact_intent["key"] and fact_intent["value"]:
                key = fact_intent["key"].strip().lower()
                val = fact_intent["value"].strip()
                print(f"[FactUpdate.Semantic] {key} = {val}")
                save_fact(key, val)

            # Fact query ("What is my favorite color?")
            elif fact_intent["type"] == "fact.query" and fact_intent["key"]:
                save_fact("last_fact_query", fact_intent["key"].strip().lower())
                print(f"[FactQuery.Semantic] pending key={fact_intent['key']}")

            # Short answer to previous question ("Blue" after asking favorite color)
            elif len(text.split()) <= 3:
                facts = list_facts()
                last_key = facts.get("last_fact_query")
                if last_key:
                    print(f"[FactAutoLink] {last_key} = {text}")
                    save_fact(last_key, text.strip())
                    delete_fact("last_fact_query")

        except Exception as e:
            print("[FactCaptureError.Semantic]", e)

        # Build conversational + factual context
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
            # summarize_if_needed() temporarily disabled until SQL fix
        except Exception as e:
            print("[VectorStoreError]", e)

        return {"reply": reply}

    # Plugin dispatch path
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
                f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally or clarify missing information.",
                context=context,
            )
            return {"reply": reply}

        return {"reply": summary}
    except Exception as e:
        return {"reply": f"Plugin error ({plugin}): {e}"}


@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
def startup_message():
    print("✅ Cortex API started — semantic memory active.")