# executor/core/router.py
from __future__ import annotations
from typing import Any, Dict
from pathlib import Path
import json, time, re
from executor.core.intent import infer_intent
from executor.utils.memory import list_facts

# ---------------------------------------------------------------------------
# Simple on-disk cache for intent classification
# ---------------------------------------------------------------------------
_CACHE_PATH = Path("/data") / "intent_cache.json"
_CACHE_TTL = 3600  # seconds (1 hour)

def _load_cache() -> Dict[str, Dict[str, Any]]:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text())
    except Exception:
        pass
    return {}

def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass

def _get_cached_intent(text: str) -> Dict[str, Any] | None:
    cache = _load_cache()
    entry = cache.get(text)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > _CACHE_TTL:
        return None
    return entry.get("plan")

def _set_cached_intent(text: str, plan: Dict[str, Any]) -> None:
    cache = _load_cache()
    cache[text] = {"plan": plan, "ts": time.time()}
    _save_cache(cache)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _base_response(msg: str, mode: str = "chat") -> Dict[str, Any]:
    return {
        "assistant_message": msg,
        "mode": mode,
        "questions": [],
        "ideas": [],
        "facts_to_save": [],
        "tasks_to_add": [],
        "directive_updates": {},
        "actions": [],
    }

def _normalize_text(text: Any) -> str:
    return ("" if text is None else str(text)).strip()

def _resolve_facts_in_text(text: str) -> str:
    """Replace pronouns/placeholders with known facts so plugins can act on them."""
    try:
        facts = list_facts()
        for key, val in facts.items():
            lowkey = key.lower().strip()
            if lowkey in ("live in", "location", "where i live", "city"):
                text = text.replace("where I live", val)
                text = text.replace("my city", val)
            elif lowkey in ("favorite color", "color"):
                text = text.replace("my favorite color", val)
            elif lowkey in ("name", "my name"):
                text = text.replace("my name", val)
        return text
    except Exception:
        return text

# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------
def route(
    user_text: Any,
    session: str = "repl",
    directives: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    LLM-driven intent router with caching, fact resolution, and pronoun-aware gating.
    """
    text = _normalize_text(user_text)
    text = _resolve_facts_in_text(text)
    directives = directives or {}
    if not text:
        return _base_response("How can I help?")

    # --- SELF-REFERENCE OVERRIDE (restored from 2.7-green) ---
    # If user asks about themselves, keep it in brain/memory path
    if re.search(r"\b(my|mine|i|me)\b", text.lower()):
        if any(q in text.lower() for q in ("what", "who", "where", "when")):
            return _base_response("Okay — let me think about that.")

    # --- Try cached plan first ---
    plan = _get_cached_intent(text)
    if not plan:
        available_plugins = {
            "web_search": {"description": "Perform general or factual web/news searches."},
            "weather_plugin": {"description": "Get current or forecasted weather data."},
            "google_places": {"description": "Find nearby businesses, attractions, or places."},
            "feedback": {"description": "Record explicit feedback about Cortex's performance."},
        }
        plan = infer_intent(text, available_plugins)
        _set_cached_intent(text, plan)

    plugin = plan.get("target_plugin", "none")
    params = plan.get("parameters", {})
    confidence = float(plan.get("confidence", 1.0)) if isinstance(
        plan.get("confidence"), (int, float, str)
    ) else 1.0

    # --- Confidence gating & plugin dispatch ---
    if plugin and plugin != "none" and confidence >= 0.75:
        resp = _base_response(f"Routing to {plugin}", mode="execute")
        resp["actions"].append(
            {"plugin": plugin, "status": "ready", "args": params or {"query": text}}
        )
        return resp

    # --- Default fallback → handled by brain ---
    return _base_response("Okay — let me think about that.")