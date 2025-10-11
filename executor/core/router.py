from __future__ import annotations
"""
Cortex Router
-------------
Purpose
--------
• Normalize raw user input into a conservative, test-friendly action contract.
• Decide *when* to invoke capabilities (plugins) while staying resilient under pytest and Fly.io.
• Optionally execute plugins and update memory/context.

Output schema
--------------
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

from typing import Any, Dict, List
import re
import logging

# ------------------------------------------------------------
#  Lightweight intent hints
# ------------------------------------------------------------
_SEARCH_HINTS = re.compile(
    r"\b(search|look\s*up|find|weather|forecast|news|near\s*me)\b",
    re.IGNORECASE,
)
_IDEA_HINT = re.compile(r"^\s*\[idea\]\s*(.+)$", re.IGNORECASE)
_FACTS_HINT = re.compile(
    r"^\s*\[fact(?:s)?\]\s*(?P<key>[^:=]+?)\s*[:=]\s*(?P<val>.+)$",
    re.IGNORECASE,
)

_WEATHER_HINT = re.compile(r"\b(weather|forecast|temperature)\b", re.I)
_NEAR_HINT = re.compile(r"\b(near\s+me|coffee|restaurant|cafe|attraction)\b", re.I)
_WHO_HINT = re.compile(r"^\s*(who|what|where)\b", re.I)

# ------------------------------------------------------------
#  Helpers
# ------------------------------------------------------------
def _normalize_text(text: Any) -> str:
    return ("" if text is None else str(text)).strip()


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

# ------------------------------------------------------------
#  Plugin Execution Layer
# ------------------------------------------------------------
def _run_actions(actions: List[dict]) -> str:
    """
    Execute any plugin actions listed in the router output and return
    a short combined summary. Each plugin must expose handle(payload).
    Failures are logged but not fatal.
    """
    if not actions:
        return ""

    results = []
    for act in actions:
        plugin_name = act.get("plugin")
        if not plugin_name:
            continue
        try:
            mod = __import__(f"executor.plugins.{plugin_name}", fromlist=["handle"])
            handle = getattr(mod, "handle", None)
            if callable(handle):
                payload = act.get("args", {})
                result = handle(payload)
                if isinstance(result, dict):
                    summary = (
                        result.get("summary")
                        or result.get("message")
                        or str(result)
                    )
                else:
                    summary = str(result)
                results.append(f"{plugin_name}: {summary}")
            else:
                results.append(f"{plugin_name}: no handle() function found")
        except Exception as e:
            logging.exception("Plugin %s failed: %s", plugin_name, e)
            results.append(f"{plugin_name} failed: {e}")
    return "\n".join(results)

# ------------------------------------------------------------
#  Memory / context integration (best effort)
# ------------------------------------------------------------
def _record_memory(role: str, content: str) -> None:
    """Store chat turns or plugin summaries into memory if available."""
    try:
        from executor.utils.memory import remember_exchange, init_db_if_needed
        init_db_if_needed()
        remember_exchange(role, content)
    except Exception:
        pass
    try:
        from executor.utils.vector_memory import store_vector, summarize_if_needed
        store_vector(role, content)
        summarize_if_needed()
    except Exception:
        pass

# ------------------------------------------------------------
#  Main routing logic
# ------------------------------------------------------------
def route(
    user_text: Any,
    session: str = "repl",
    directives: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Main router entrypoint used by REPL, API, and tests.
    Must never raise for normal inputs. Keeps all optional behaviors guarded.
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
        _record_memory("user", text)
        _record_memory("assistant", resp["assistant_message"])
        return resp

    # 2️⃣  Explicit "[fact] key: value" capture
    m_fact = _FACTS_HINT.match(text)
    if m_fact:
        key = m_fact.group("key").strip()
        val = m_fact.group("val").strip()
        resp = _base_response(f"Noted: {key} = {val}", mode="chat")
        resp["facts_to_save"].append({"key": key, "value": val})
        _record_memory("user", text)
        _record_memory("assistant", resp["assistant_message"])
        return resp

    # 3️⃣  Search intent
    if _SEARCH_HINTS.search(text):
        resp = _base_response(f"Searching the web for: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "web_search", "status": "ready", "args": {"query": text}}
        )
        summary = _run_actions(resp["actions"])
        if summary:
            resp["assistant_message"] = summary
            _record_memory("assistant", summary)
        return resp

    # 4️⃣  Other quick intents
    if _WEATHER_HINT.search(text):
        resp = _base_response(f"Checking weather for: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "weather_plugin", "status": "ready", "args": {"query": text}}
        )
        summary = _run_actions(resp["actions"])
        if summary:
            resp["assistant_message"] = summary
            _record_memory("assistant", summary)
        return resp

    if _NEAR_HINT.search(text):
        resp = _base_response(f"Searching nearby: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "google_places", "status": "ready", "args": {"query": text}}
        )
        summary = _run_actions(resp["actions"])
        if summary:
            resp["assistant_message"] = summary
            _record_memory("assistant", summary)
        return resp

    if _WHO_HINT.search(text):
        resp = _base_response(f"Looking up entity: {text}", mode="execute")
        resp["actions"].append(
            {"plugin": "google_kg", "status": "ready", "args": {"query": text}}
        )
        summary = _run_actions(resp["actions"])
        if summary:
            resp["assistant_message"] = summary
            _record_memory("assistant", summary)
        return resp

    # 5️⃣  Default fallback — memory-aware
    resp = _base_response("Okay — let me think about that.")
    try:
        _record_memory("user", text)
        _record_memory("assistant", resp["assistant_message"])
    except Exception:
        pass
    return resp