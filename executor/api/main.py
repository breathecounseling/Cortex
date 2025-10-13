from __future__ import annotations
import os, re, json
from pathlib import Path
from typing import Any, Dict, Optional
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

app = FastAPI()

# Mount built frontend
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

def normalize_fact_key(raw: str) -> list[str]:
    """Generate possible key variants for flexible recall."""
    raw = raw.lower().strip()
    variants = {raw}
    if raw.startswith("my "):
        variants.add(raw[3:])
        variants.add(raw.replace("my ", "your ", 1))
    if raw.startswith("your "):
        variants.add(raw[5:])
        variants.add(raw.replace("your ", "my ", 1))
    variants.add(raw.replace("favourite", "favorite"))
    return list(variants)


def get_fact_fuzzy(facts: dict[str, str], query: str) -> Optional[str]:
    for k in normalize_fact_key(query):
        if k in facts:
            return facts[k]
    return None


def inject_facts(context: list[dict[str, str]]) -> list[dict[str, str]]:
    """Prepend known facts to system context."""
    try:
        facts = list_facts()
        if facts:
            print(f"[InjectFacts] {json.dumps(facts, indent=2)}")
            context.insert(
                0,
                {
                    "role": "system",
                    "content": f"Known user facts (authoritative): {json.dumps(facts)}",
                },
            )
    except Exception as e:
        print("[InjectFactsError]", e)
    return context


def substitute_facts_in_text(text: str) -> str:
    """Replace placeholders (my city, favorite color, etc.) using fuzzy matching."""
    try:
        facts = list_facts()
        for key, val in facts.items():
            for alias in normalize_fact_key(key):
                text = re.sub(rf"\b{re.escape(alias)}\b", val, text, flags=re.I)
        return text
    except Exception as e:
        print("[SubstituteFactsError]", e)
        return text


def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    """Combine conversation history, facts, and vector summaries."""
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

    text = substitute_facts_in_text(text)

    # Route to plugins or brain
    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}

    actions = router_output.get("actions", [])

    if not actions:
        try:
            update_or_delete_from_text(text)
            # Capture new factual statements
            fact_match = re.search(
                r"\bmy\s+([\w\s]+?)\s*(?:is|was|=|'s|:)\s+([^.?!]+)",
                text, re.I
            )
            if fact_match:
                key, val = fact_match.groups()
                key = key.strip().lower().replace("favourite", "favorite")
                val = val.strip().rstrip(".!?")
                print(f"[FactCapture] {key} = {val}")
                save_fact(key, val)
        except Exception as e:
            print("[FactCaptureError]", e)

        # Build enriched context
        context = build_context_with_retrieval(text)

        # Check if question directly references known facts
        facts = list_facts()
        for key in list(facts.keys()):
            if any(alias in text.lower() for alias in normalize_fact_key(key)):
                reply = f"You told me your {key} is {facts[key]}."
                break
        else:
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
            context = build_context_with_retrieval(text)
            reply = brain_chat(
                f"{text}\n\nPlugin output:\n{summary}\n\n"
                "Respond conversationally or fill in any missing information.",
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
    print("✅ Cortex API started — ready for chat and plugin actions.")