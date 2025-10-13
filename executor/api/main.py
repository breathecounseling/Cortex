from __future__ import annotations
import os, json
from pathlib import Path
from typing import Any, Dict
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Core
from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback

# Semantic intent classifiers
from executor.core.language_intent import classify_language_intent
from executor.core.intent_facts import detect_fact_or_question

# Brain + memory
from executor.ai.router import chat as brain_chat
from executor.utils.memory import (
    init_db_if_needed,
    recall_context,
    remember_exchange,
    save_fact,
    delete_fact,
    load_fact,
    list_facts,
)
from executor.utils.vector_memory import (
    store_vector,
    summarize_if_needed,
    retrieve_topic_summaries,
    hierarchical_recall,
)

app = FastAPI()

# Mount UI if present
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
    """Context = recent chat + stored facts + summaries + deep recall."""
    context: list[dict[str, str]] = []
    try:
        init_db_if_needed()
        context = recall_context(limit=8)
    except Exception:
        context = []
    context = inject_facts(context)

    try:
        summaries = retrieve_topic_summaries(query, k=3)
        if summaries:
            context.insert(
                0,
                {"role": "system", "content": "Relevant summaries:\n" + "\n".join(summaries)},
            )
    except Exception:
        pass

    try:
        deep_refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if deep_refs:
            context.insert(
                0,
                {"role": "system", "content": "Detailed recall:\n" + "\n".join(deep_refs)},
            )
    except Exception:
        pass

    return context


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}


@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    """Main chat handler — semantic intent interpretation."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    text = (
        body.text
        or raw.get("message")
        or raw.get("prompt")
        or raw.get("content")
        or ""
    ).strip()
    if not text:
        return {"reply": "How can I help?"}

    # Run classifiers
    lang_int = classify_language_intent(text)
    fact_int = detect_fact_or_question(text)
    print(f"[LangIntent] {lang_int} :: {text}")

    # Handle known fact actions
    try:
        if fact_int["type"] == "fact.declaration" and fact_int["key"] and fact_int["value"]:
            save_fact(fact_int["key"], fact_int["value"])
            return {"reply": f"Got it — your {fact_int['key']} is {fact_int['value']}."}

        elif fact_int["type"] == "fact.query" and fact_int["key"]:
            val = load_fact(fact_int["key"])
            if val:
                return {"reply": f"Your {fact_int['key']} is {val}."}
            return {"reply": f"I’m not sure about your {fact_int['key']}. Feel free to tell me!"}

        elif fact_int["type"] == "fact.correction" and fact_int["key"]:
            delete_fact(fact_int["key"])
            return {"reply": f"Got it — I've forgotten {fact_int['key']}."}
    except Exception as e:
        print("[SemanticFactHandlerError]", e)

    # Fall back to plugin routing
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

        # Record & vectorize
        try:
            remember_exchange("user", text)
            remember_exchange("assistant", reply)
            store_vector("user", text)
            store_vector("assistant", reply)
            summarize_if_needed()
        except Exception as e:
            print("[VectorStoreError]", e)

        return {"reply": reply}

    # Plugins
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
            try:
                context = build_context_with_retrieval(text)
                reply = brain_chat(
                    f"{text}\n\nPlugin output:\n{summary}\n\n"
                    "Respond conversationally or fill in any missing information.",
                    context=context,
                )
                return {"reply": reply}
            except Exception:
                pass
        return {"reply": summary}
    except Exception as e:
        return {"reply": f"Plugin error ({plugin}): {e}"}


@app.get("/health", include_in_schema=False)
def health():
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
def startup_message() -> None:
    print("✅ Cortex API started — semantic intent baseline.")