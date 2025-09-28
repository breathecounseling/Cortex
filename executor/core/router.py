from typing import Dict, Any, List


def _route_internal(user_text: str, session: str) -> Dict[str, Any]:
    """
    Hook your real analysis/dispatch pipeline here and return a dict that may include:
      assistant_message: str
      facts_to_save: List[Dict[str, str]]
      tasks_to_add: List[Dict[str, Any]]
      actions: List[Dict[str, Any]]
    If you already have such functions, call them here.
    """
    # TODO: integrate your LLM + dispatcher + registry.
    # Temporary safe fallback:
    return {
        "assistant_message": f"(stub) You said: {user_text}",
        "facts_to_save": [],
        "tasks_to_add": [],
        "actions": [],
    }


def route(user_text: str, session: str = "default") -> Dict[str, Any]:
    """
    Public contract used by tests and repl.py.
    Always returns the keys: assistant_message, facts_to_save, tasks_to_add, actions.
    """
    raw = _route_internal(user_text, session)

    # Normalize shape defensively
    out: Dict[str, Any] = {
        "assistant_message": raw.get("assistant_message") or "",
        "facts_to_save": _as_list_of_dicts(raw.get("facts_to_save")),
        "tasks_to_add": _as_list_of_dicts(raw.get("tasks_to_add")),
        "actions": _as_list_of_dicts(raw.get("actions")),
    }
    return out


def _as_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        return value
    return []
