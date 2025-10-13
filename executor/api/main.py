from __future__ import annotations
import os, re, json
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
    list_facts,
    update_or_delete_from_text,
)
from executor.utils.vector_memory import (
    store_vector,
    summarize_if_needed,
    retrieve_topic_summaries,
    hierarchical_recall,
)
from executor.core.language_intent import classify_language_intent


app = FastAPI()

# Mount built frontend if present
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

def _summarize_facts_for_brain(facts: dict[str, str]) -> str:
    """Turn key/value memory into conversational context text."""
    if not facts:
        return ""
    lines = []
    for k, v in facts.items():
        lines.append(f"The user's {k} is {v}.")
    return " ".join(lines)


def inject_facts(context: list[dict[str, str]]) -> list[dict[str, str]]:
    """Inject known user facts in natural language so the model can reason with them."""
    try:
        facts = list_facts()
        if facts:
            friendly_summary = _summarize_facts_for_brain(facts)
            print(f"[InjectFacts] {json.dumps(facts, indent=2)}")
            context.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "You already know the following about the user. "
                        "Use this knowledge naturally in conversation: "
                        f"{friendly_summary}"
                    ),
                },
            )
    except Exception as e:
        print("[InjectFactsError]", e)
    return context


def substitute_facts_in_text(text: str) -> str:
    """Replace placeholders (my city, where I live, etc.) with stored facts for plugins."""
    try:
        facts = list_facts()
        for key, val in facts.items():
            lowkey = key.lower()
            if any(x in lowkey for x in ("live", "city", "location")):
                text = re.sub(r"\b(where\s+i\s+live|my\s+city|in\s+my\s+city)\b", val, text, flags=re.I)
            elif "color" in lowkey:
                text = re.sub(r"\b(my\s+favorite\s+color|favorite\s+color)\b", val, text, flags=re.I)
        return text
    except Exception as e:
        print("[SubstituteFactsError]", e)
        return text


def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    """Assemble working context with recent turns, facts, summaries, and long-term recall."""
    context: list[dict[str, str]] = []
    try:
        init_db_if_needed()
        context = recall_context(limit=8)
    except Exception as e:
        print("[ContextRecallError]", e)
        context = []

    # Add facts first
    context = inject_facts(context)

    # Add summaries + deep recall
    try:
        summaries = retrieve_topic_summaries(query, k=3)
        if summaries:
            context.insert(
                0,
                {"role": "system", "content": "Relevant historical summaries:\n" + "\n".join(summaries)},
            )
    except Exception as e:
        print("[VectorMemorySummaryError]", e)

    try:
        deep_refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if deep_refs:
            context.insert(
                0,
                {"role": "system", "content": "Detailed references:\n" + "\n".join(deep_refs)},
            )
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

    # Substitute known facts early for plugin-friendly phrasing
    text = substitute_facts_in_text(text)

    # Lightweight intent classification
    lang_intent = classify_language_intent(text)
    print(f"[LangIntent] {lang_intent} :: {text}")

    # Core router for plugins
    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}
    actions = router_output.get("actions", [])

    # 🧠 Brain + memory mode
    if not actions:
        try:
            # Clean and detect corrections
            update_or_delete_from_text(text)

            if lang_intent == "declaration":
                cleaned = re.sub(r"^(well|actually|no|yeah|ok|okay|so)[,.\s]+", "", text.strip(), flags=re.I)
                fact_match = re.search(
                    r"^\s*my\s+([\w\s]+?)\s*(?:is|was|=|'s|:)\s+([^.?!]+)",
                    cleaned,
                    re.I,
                )
                if fact_match:
                    key, val = fact_match.groups()
                    key = key.strip().lower().replace("favourite", "favorite")
                    val = val.strip()
                    if not re.match(r"^(who|what|where|when|why|how)\b", val, re.I):
                        val = re.sub(r"[.?!\s]+$", "", val)
                        print(f"[FactCapture] key='{key}' val='{val}'")
                        save_fact(key, val)
        except Exception as e:
            print("[FactCaptureError]", e)

        # Build context AFTER saving facts
        try:
            context = build_context_with_retrieval(text)
            reply = brain_chat(text, context=context)
        except Exception as e:
            reply = f"(brain offline) {e}"

        # Record exchanges and store vectors
        try:
            remember_exchange("user", text)
            remember_exchange("assistant", reply)
            store_vector("user", text)
            store_vector("assistant", reply)
            summarize_if_needed()
        except Exception as e:
            print("[VectorStoreError]", e)

        return {"reply": reply}

    # Plugin dispatch
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
                    f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally or fill in any missing information.",
                    context=context,
                )
                return {"reply": reply}
            except Exception as e:
                print("[ReflectionError]", e)
        return {"reply": summary}
    except Exception as e:
        return {"reply": f"Plugin error ({plugin}): {e}"}


@app.post("/execute")
def execute(body: Dict[str, Any]) -> Dict[str, Any]:
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