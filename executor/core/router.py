from __future__ import annotations

"""
Cortex Router
-------------
Purpose:
- Normalize raw user input into a conservative, test-friendly action contract.
- Decide *when* to invoke capabilities (plugins), but never hard-depend on optional modules.
- Stay resilient under pytest and Fly.io (no fragile imports, no background work).

Outputs follow the repo’s expected schema:
{
  "assistant_message": str,
  "mode": "execute" | "brainstorming" | "chat",
  "questions": list[str],
  "ideas": list[str],
  "facts_to_save": list[dict],
  "tasks_to_add": list[str],
  "directive_updates": dict,
  "actions": [ {"plugin": str, "status": "ready", "args": dict} ]
}
"""

from typing import Any, Dict
import re


# ---- Lightweight intent hints ----
_SEARCH_HINTS = re.compile(
    r"\b(search|look\s*up|find|weather|forecast|news|near\s*me)\b",
    re.IGNORECASE,
)
_IDEA_HINT = re.compile(r"^\s*\[idea\]\s*(.+)$", re.IGNORECASE)
_FACTS_HINT = re.compile(
    r"^\s*\[fact(?:s)?\]\s*(?P<key>[^:=]+?)\s*[:=]\s*(?P<val>.+)$",
    re.IGNORECASE,
)


def _base_response(msg: str, mode: str = "chat") -> Dict[str, Any]:
    """Return a conservative response skeleton with required fields present."""
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


def route(user_text: Any, session: str = "repl", directives: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Main router entrypoint used by REPL, API, and tests.
    Must never raise for normal inputs. Keep all optional behaviors guarded.
    """
    text = _normalize_text(user_text)
    directives = directives or {}

    # Empty input → neutral reply
    if not text:
        return _base_response("How can I help?")

    # 1️⃣  Explicit "[idea] ..." capture
    m_idea = _IDEA_HINT.match(text)
    if m_idea:
        idea_title = m_idea.group(1).strip() or "New idea"
        resp = _base_response(f"Captured idea: {idea_title}", mode="brainstorming")
        resp["ideas"].append(idea_title)
        resp["tasks_to_add"].append(f"[idea] {idea_title}")
        return resp

    # 2️⃣  Explicit "[fact] key: value" capture
    m_fact = _FACTS_HINT.match(text)
    if m_fact:
        key = m_fact.group("key").strip()
        val = m_fact.group("val").strip()
        resp = _base_response(f"Noted: {key} = {val}", mode="chat")
        resp["facts_to_save"].append({"key": key, "value": val})
        return resp

    # 3️⃣  Search intent fallback
    if _SEARCH_HINTS.search(text):
        resp = _base_response(f"Searching the web for: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "web_search", "status": "ready", "args": {"query": text}}
        )
        return resp

    # 4️⃣  Phase 2.5 auto-routing patch  🔽  (all indented inside route)
    # PATCH START: additional quick intent routing (Phase 2.5)
    _WEATHER_HINT = re.compile(r"\b(weather|forecast|temperature)\b", re.I)
    _NEAR_HINT = re.compile(r"\b(near\s+me|coffee|restaurant|cafe|attraction)\b", re.I)
    _WHO_HINT = re.compile(r"^\s*(who|what|where)\b", re.I)

    if _WEATHER_HINT.search(text):
        resp = _base_response(f"Checking weather for: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "weather_plugin", "status": "ready", "args": {"query": text}}
        )
        return resp

    if _NEAR_HINT.search(text):
        resp = _base_response(f"Searching nearby: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "google_places", "status": "ready", "args": {"query": text}}
        )
        return resp

    if _WHO_HINT.search(text):
        resp = _base_response(f"Looking up entity: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "google_kg", "status": "ready", "args": {"query": text}}
        )
        return resp
    # PATCH END

    # 5️⃣  Default fallback
    return _base_response("Okay — let me think about that.")