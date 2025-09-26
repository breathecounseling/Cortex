from __future__ import annotations
import json
from typing import Dict, Any, List

from executor.connectors.openai_client import OpenAIClient
from executor.plugins.repo_analyzer import repo_analyzer
from executor.plugins.conversation_manager import conversation_manager as cm

# ---------------- Contract ----------------

CONTRACT_INSTRUCTION = (
    "You are the Cortex Executor Parser.\n"
    "Role:\n"
    "- Translate natural conversation into structured JSON.\n"
    "- Never output plain strings or prose outside JSON.\n\n"
    "JSON schema:\n"
    "{\n"
    "  assistant_message: str,\n"
    "  mode: 'brainstorming' | 'clarification' | 'execution',\n"
    "  questions: [{id, scope, question}],\n"
    "  ideas: [str],\n"
    "  facts_to_save: [{key, value}],\n"
    "  tasks_to_add: [{title, priority}],\n"
    "  directive_updates: {},\n"
    "  actions: [{plugin, goal, status, args}]\n"
    "}\n\n"
    "Behaviors:\n"
    "- If user request is vague, return mode=brainstorming with clarifying questions.\n"
    "- If some facts are missing, mode=clarification and include facts_to_save.\n"
    "- Only when sufficient detail is given, return mode=execution with at least one ready action.\n"
    "- assistant_message must always be present to display to the user.\n"
)

# ---------------- Router ----------------

def _parse_json(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except Exception:
        # Try to salvage JSON between braces
        b, e = raw.find("{"), raw.rfind("}")
        if b != -1 and e != -1 and e > b:
            try:
                return json.loads(raw[b:e+1])
            except Exception:
                pass
    return {
        "assistant_message": "⚠️ Sorry, I could not parse a structured response.",
        "mode": "brainstorming",
        "questions": [],
        "ideas": [],
        "facts_to_save": [],
        "tasks_to_add": [],
        "directive_updates": {},
        "actions": [],
    }

def route(user_text: str, session: str = "repl", directives: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Main Router entrypoint.
    - Takes raw user input + session context.
    - Returns structured JSON contract.
    """
    client = OpenAIClient()
    repo_index = repo_analyzer.scan_repo()
    facts = cm.load_facts(session)

    msgs = [
        {"role": "system", "content": CONTRACT_INSTRUCTION},
        {"role": "system", "content": f"Available plugins: {json.dumps(list(repo_index.keys()))}"},
        {"role": "system", "content": f"Facts: {json.dumps(facts)}"},
        {"role": "user", "content": user_text},
    ]

    raw_out = client.chat(msgs, response_format={"type": "json_object"})
    data = _parse_json(raw_out)

    # Ensure required keys exist
    for key, default in [
        ("assistant_message", ""),
        ("mode", "brainstorming"),
        ("questions", []),
        ("ideas", []),
        ("facts_to_save", []),
        ("tasks_to_add", []),
        ("directive_updates", {}),
        ("actions", []),
    ]:
        data.setdefault(key, default)

    # Normalize actions: enforce dict format and plugin existence
    normalized: List[Dict[str, Any]] = []
    for a in data.get("actions", []):
        if isinstance(a, dict):
            plugin = (a.get("plugin") or "").strip().lower().replace(" ", "_")
            goal = (a.get("goal") or "").strip()
            status = (a.get("status") or "pending").lower()
            args = a.get("args", {})
            if plugin and goal:
                if plugin not in repo_index:
                    # Mark as pending until plugin is built
                    status = "pending"
                normalized.append({"plugin": plugin, "goal": goal, "status": status, "args": args})
    data["actions"] = normalized

    return data
