from __future__ import annotations
from typing import Any, Dict
from pathlib import Path
import json, time, re
from executor.core.intent import infer_intent
from executor.utils.memory import list_facts

_CACHE_PATH = Path("/data") / "intent_cache.json"
_CACHE_TTL = 3600  # 1 hour

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
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
# Utilities
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
    """Replace pronouns/placeholders with stored facts so plugins get real values."""
    try:
        facts = list_facts()
        low = text.lower()

        # --- replace city/location ---
        for k, v in facts.items():
            lk = k.lower()
            if any(x in lk for x in ("live", "location", "city")):
                text = re.sub(r"\b(where\s+i\s+live|my\s+city|in\s+my\s+city)\b", v, text, flags=re.I)

        # --- replace favorite color ---
        for k, v in facts.items():
            lk = k.lower()
            if "color" in lk:
                text = re.sub(r"\b(my\s+favorite\s+color|favorite\s+color)\b", v, text, flags=re.I)

        # --- replace other simple pronouns ---
        text = text.replace("my location", facts.get("live in", facts.get("location", "")))
        return text
    except Exception:
        return text

# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------
def route(user_text: Any, session: str = "repl", directives: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Intent router with caching, fact resolution, and pronoun-aware gating.
    """
    text = _normalize_text(user_text)
    text = _resolve_facts_in_text(text)
    directives = directives or {}
    if not text:
        return _base_response("How can I help?")

    # --- keep contextual questions in brain layer ---
    if re.search(r"\b(my|i|me|mine)\b", text.lower()):
        # questions about self ("Who is the mayor of my city?") stay in brain
        if any(x in text.lower() for x in ("who", "what", "where")):
            return _base_response("Okay — let me think about that.")

    # --- try cache ---
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
    confidence = float(plan.get("confidence", 1.0)) if isinstance(plan.get("confidence"), (int, float, str)) else 1.0

    if plugin and plugin != "none" and confidence >= 0.75:
        resp = _base_response(f"Routing to {plugin}", mode="execute")
        resp["actions"].append({"plugin": plugin, "status": "ready", "args": params or {"query": text}})
        return resp

    return _base_response("Okay — let me think about that.") 