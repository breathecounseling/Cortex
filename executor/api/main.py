# executor/api/main.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Router + plugins
from executor.core.router import route
from executor.plugins.web_search import web_search
from executor.plugins.weather_plugin import weather_plugin
import executor.plugins.google_places.google_places as google_places
from executor.plugins.feedback import feedback

# Semantic understanding
from executor.core.language_intent import classify_language_intent, extract_location_or_trip
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
    update_or_delete_from_text,
)

# Vector memory (safe to keep on; summarization optional)
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
# Helpers
# ---------------------------------------------------------------------------

SCOPED_KEYS = {
    "home": "home location",
    "current": "current location",
    "trip": "trip destination",
}
EPHEMERAL_KEYS = {"last_fact_query"}

def _facts_for_prompt() -> dict[str, str]:
    """Facts excluding ephemeral keys."""
    facts = list_facts()
    return {k: v for k, v in facts.items() if k not in EPHEMERAL_KEYS and not k.startswith("context:")}

def inject_facts(context: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Prepend scoped and general facts for the LLM.
    We explicitly surface home/current/trip context for disambiguation.
    """
    facts = _facts_for_prompt()
    try:
        segments: list[str] = []
        if "home location" in facts:
            segments.append(f"The user's home location is {facts['home location']}.")
        if "current location" in facts:
            segments.append(f"The user is currently in {facts['current location']}.")
        if "trip destination" in facts:
            segments.append(f"The user is planning a trip to {facts['trip destination']}.")

        # Add non-scoped facts as sentences
        for k, v in facts.items():
            if k not in {"home location", "current location", "trip destination"}:
                segments.append(f"The user's {k} is {v}.")

        if segments:
            context.insert(0, {"role": "system", "content": "Known user facts (authoritative): " + " ".join(segments)})
        else:
            context.insert(0, {"role": "system", "content": "Note: no current facts stored; if prior chat mentions facts, they may be outdated."})
    except Exception as e:
        print("[InjectFactsError]", e)
    return context


def build_context_with_retrieval(query: str) -> list[dict[str, str]]:
    """Assemble recent chat + facts + (optional) summaries/recall."""
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
            context.insert(0, {"role": "system", "content": "Relevant summaries:\n" + "\n".join(summaries)})
    except Exception as e:
        print("[VectorSummariesError]", e)

    try:
        deep_refs = hierarchical_recall(query, k_vols=2, k_refs=3)
        if deep_refs:
            context.insert(0, {"role": "system", "content": "Detailed recall:\n" + "\n".join(deep_refs)})
    except Exception as e:
        print("[VectorRecallError]", e)

    return context


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Cortex API is running."}


@app.post("/chat")
async def chat(body: ChatBody, request: Request) -> Dict[str, Any]:
    """Main conversational endpoint – semantic-only fact handling + scoped context."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    text = (body.text or raw.get("message") or raw.get("prompt") or raw.get("content") or "").strip()
    if not text:
        return {"reply": "How can I help?"}

    # 0) Route plugins early (kept simple & stable)
    try:
        router_output = route(text)
    except Exception as e:
        return {"reply": f"Router error: {e}"}
    actions = router_output.get("actions", [])

    # 1) Apply memory corrections/deletions (user-visible confirmation)
    try:
        mem_action = update_or_delete_from_text(text)
        if mem_action.get("action") == "deleted":
            key = mem_action.get("key") or "that information"
            # IMPORTANT: do not return yet; this turn might also contain a new declaration ("forget X, it's Y now")
            deletion_notice = f"Got it — I've forgotten {key}."
        else:
            deletion_notice = None
    except Exception as e:
        deletion_notice = None
        print("[MemoryDeleteHandlerError]", e)

    # 2) Semantic understanding
    try:
        lang_int = classify_language_intent(text)
        fact_int = detect_fact_or_question(text)
        # Location/trip extraction (scoped)
        loc = extract_location_or_trip(text)
        if loc and loc.get("kind") in SCOPED_KEYS and loc.get("value"):
            save_fact(SCOPED_KEYS[loc["kind"]], loc["value"])
            # If this was purely a scoped-location turn, confirm immediately
            if not actions and fact_int.get("type") in {None, "other"}:
                reply = f"Got it — your {SCOPED_KEYS[loc['kind']]} is {loc['value']}."
                # Continue to brain below to keep flow natural; we won't early-return the loc message unless nothing else applies.

        # Direct declaration ("My favorite color is blue")
        if fact_int["type"] == "fact.declaration" and fact_int["key"] and fact_int["value"]:
            key = fact_int["key"].strip().lower()
            val = fact_int["value"].strip()
            # If same turn had a deletion notice that targeted same key, we've already deleted – now re-save.
            save_fact(key, val)
            if deletion_notice:
                return {"reply": f"{deletion_notice} And updated — your {key} is {val}."}
            return {"reply": f"Got it — your {key} is {val}."}

        # Correction ("Actually it's green now") — if key present, overwrite
        if fact_int["type"] == "fact.correction" and fact_int["key"]:
            key = fact_int["key"].strip().lower()
            # If a value is present, set it; if not, treat as forget-only
            if fact_int.get("value"):
                val = fact_int["value"].strip()
                save_fact(key, val)
                return {"reply": f"Updated — your {key} is {val}."}
            else:
                delete_fact(key)
                return {"reply": f"Got it — I've forgotten {key}."}

        # Fact query ("What is my favorite color?")
        if fact_int["type"] == "fact.query" and fact_int["key"]:
            key = fact_int["key"].strip().lower()
            val = load_fact(key)
            if val:
                return {"reply": f"Your {key} is {val}."}
            # Mark last_fact_query so a short answer next turn can link
            save_fact("last_fact_query", key)
            return {"reply": f"I’m not sure about your {key}. Tell me and I’ll remember it."}

        # Short answer linking: if last_fact_query is set and user replied with a short value
        facts_now = list_facts()
        last_q = facts_now.get("last_fact_query")
        if last_q and len(text.split()) <= 3:
            save_fact(last_q, text.strip())
            delete_fact("last_fact_query")
            return {"reply": f"Thanks — your {last_q} is {text.strip()}."}

        # If the turn was only a deletion (and no new declaration), confirm now
        if deletion_notice and not actions:
            return {"reply": deletion_notice}

    except Exception as e:
        print("[SemanticHandlerError]", e)

    # 3) If no plugin action, brain + memory flow
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
            # Re-enable if your summarizer is stable
            # summarize_if_needed()
        except Exception as e:
            print("[VectorStoreError]", e)

        return {"reply": reply}

    # 4) Plugin dispatch
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
                f"{text}\n\nPlugin output:\n{summary}\n\nRespond conversationally or fill in missing information.",
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
def startup_message() -> None:
    print("✅ Cortex API started — Phase 2.8 semantic baseline with scoped context.")