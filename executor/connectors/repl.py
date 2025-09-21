# executor/connectors/repl.py
from __future__ import annotations
import json
import os
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from executor.connectors.openai_client import OpenAIClient
from executor.plugins.builder.extend_plugin import extend_plugin
from executor.utils.error_handler import ExecutorError, classify_error
from executor.utils.docket import Docket

# ---------------------- Memory bridges ----------------------
def _try_import_cm():
    try:
        from executor.plugins.conversation_manager.conversation_manager import (  # type: ignore
            save_turn as cm_save_turn,
            get_turns as cm_get_turns,
            load_facts as cm_load_facts,
            save_fact as cm_save_fact,
        )
        return cm_save_turn, cm_get_turns, cm_load_facts, cm_save_fact
    except Exception:
        return None, None, None, None

_CM_SAVE_TURN, _CM_GET_TURNS, _CM_LOAD_FACTS, _CM_SAVE_FACT = _try_import_cm()

_MEM_DIR = os.path.join(".executor", "memory")
os.makedirs(_MEM_DIR, exist_ok=True)

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _fallback_path(name: str) -> str:
    return os.path.join(_MEM_DIR, f"{name}.jsonl")

def _save_turn_fallback(session: str, role: str, content: Any) -> None:
    rec = {"ts": _ts(), "role": role, "content": content}
    with open(_fallback_path(session), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def _load_turns_fallback(session: str) -> List[Dict[str, str]]:
    path = _fallback_path(session)
    if not os.path.exists(path):
        return []
    turns: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("role") in {"user", "assistant", "system"}:
                    turns.append({"role": rec["role"], "content": rec["content"]})
            except Exception:
                continue
    return turns[-50:]

_FACTS_PATH = os.path.join(_MEM_DIR, "repl_facts.json")

def _load_facts_fallback(_: str) -> Dict[str, Any]:
    if not os.path.exists(_FACTS_PATH):
        return {}
    try:
        with open(_FACTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_fact_fallback(_: str, key: str, value: Any) -> None:
    data = _load_facts_fallback("repl")
    data[key] = value
    with open(_FACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def save_turn(session: str, role: str, content: Any) -> None:
    if _CM_SAVE_TURN:
        try:
            _CM_SAVE_TURN(session, role=role, content=content)
            return
        except Exception:
            pass
    _save_turn_fallback(session, role, content)

def get_turns(session: str) -> List[Dict[str, str]]:
    if _CM_GET_TURNS:
        try:
            return _CM_GET_TURNS(session)
        except Exception:
            pass
    return _load_turns_fallback(session)

def load_facts(session: str) -> Dict[str, Any]:
    if _CM_LOAD_Facts := _CM_LOAD_FACTS:
        try:
            return _CM_LOAD_Facts(session)  # type: ignore
        except Exception:
            pass
    return _load_facts_fallback(session)

def save_fact(session: str, key: str, value: Any) -> None:
    if _CM_SAVE_FACT:
        try:
            _CM_SAVE_FACT(session, key=key, value=value)
            return
        except Exception:
            pass
    _save_fact_fallback(session, key, value)

# ---------------------- Persistent directives ----------------------
_DIRECTIVES_PATH = os.path.join(_MEM_DIR, "global_directives.json")

_DEFAULT_DIRECTIVES: Dict[str, Any] = {
    # Hard-coded defaults you asked for
    "interaction_style": "chat-first",
    "clarification_mode": "one-at-a-time",  # can be "one-at-a-time" or "all-at-once"
    "memory_rule": "store all user inputs and assistant outputs incrementally",
    "facts_rule": "always extract/save stable facts from normal language (no special phrasing required)",
    "task_rule": "collect missing prerequisites or subtasks in the docket before execution",
    "action_rule": "act (extend/build/sync) only after requirements are clarified",
    "error_rule": "never silently rollback; classify and propose a fix",
}

def load_directives() -> Dict[str, Any]:
    if os.path.exists(_DIRECTIVES_PATH):
        try:
            with open(_DIRECTIVES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    # Merge defaults with persisted overrides (persisted wins)
    merged = dict(_DEFAULT_DIRECTIVES)
    merged.update(data or {})
    return merged

def save_directives(updates: Dict[str, Any]) -> None:
    current = {}
    if os.path.exists(_DIRECTIVES_PATH):
        try:
            with open(_DIRECTIVES_PATH, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}
    current.update(updates or {})
    with open(_DIRECTIVES_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

# ---------------------- Orchestrator prompt ----------------------
STRUCTURE_INSTRUCTION = (
    "You are the Cortex Executor Orchestrator.\n"
    "Behaviors (MUST FOLLOW):\n"
    "1) Chat-first: speak conversationally. Keep replies clear and compact.\n"
    "2) Clarifications: when missing info, ask clarifying questions according to 'clarification_mode'.\n"
    "   - If clarification_mode='one-at-a-time': ask ONE essential question.\n"
    "   - If 'all-at-once': ask a concise checklist of questions.\n"
    "3) Facts: ALWAYS extract stable facts from normal language (no 'save fact' phrasing required) and add to 'facts_to_save'.\n"
    "   Examples: 'I want to build a nutrition tracker' -> facts_to_save includes {'key':'project','value':'nutrition tracker'}.\n"
    "4) Tasks: ALWAYS add missing prerequisites/subtasks to 'tasks_to_add' (e.g., clarify scope, pick data source, design schema).\n"
    "5) Actions: Propose concrete actions (e.g., extend) ONLY when enough info is gathered.\n"
    "6) Errors: never silently rollback; if something fails, summarize error and propose a fix.\n"
    "7) Directive updates: if the user expresses a preference ('ask all clarifying questions at once now'), include 'directive_updates'.\n"
    "You MUST return ONLY JSON with this shape:\n"
    "{\n"
    '  "assistant_message": string,                 // what to say to the user in this turn\n'
    '  "mode": "ask" | "act" | "respond",          // ask questions, execute actions, or just respond\n'
    '  "questions": [string],                      // when mode="ask"\n'
    '  "facts_to_save": [{"key": string, "value": any}],\n'
    '  "tasks_to_add": [{"title": string, "priority": "low"|"normal"|"high"}],\n'
    '  "directive_updates": {"clarification_mode": "one-at-a-time"|"all-at-once", ...},\n'
    '  "actions": [ {"type": "extend", "plugin": string, "goal": string} ]\n'
    "}\n"
    "If unsure, prefer mode='ask'. Never emit empty JSON. Never include prose outside JSON."
)

SESSION = "repl"
BANNER = "Executor — chat naturally. I’ll remember, ask clarifying questions, and act when ready. Type 'quit' to exit."

def _parse_json(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        import re
        m = re.search(r"```json\\s*(.*?)\\s*```", s, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        b = s.find("{"); e = s.rfind("}")
        if b != -1 and e != -1 and e > b:
            return json.loads(s[b:e+1])
        return {}

def _build_messages(user_text: str, docket: Docket, directives: Dict[str, Any]) -> List[Dict[str, str]]:
    facts = load_facts(SESSION)
    turns = get_turns(SESSION)

    sys_base = {
        "role": "system",
        "content": (
            "You are a helpful, proactive architect for the Cortex Executor. "
            "Follow the user's directives strictly and behave as specified."
        ),
    }
    sys_directives = {"role": "system", "content": f"Current directives: {json.dumps(directives)}"}
    sys_facts = {"role": "system", "content": f"Known facts: {json.dumps(facts)}"}
    sys_docket = {"role": "system", "content": f"Current docket: {json.dumps(docket.list_tasks())}"}
    sys_contract = {"role": "system", "content": STRUCTURE_INSTRUCTION}

    msgs: List[Dict[str, str]] = [sys_base, sys_directives, sys_facts, sys_docket]
    msgs.extend(turns[-20:])
    msgs.append({"role": "user", "content": user_text})
    msgs.append(sys_contract)
    return msgs

def _handle_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for act in actions or []:
        if act.get("type") == "extend":
            plugin = (act.get("plugin") or "").strip()
            goal = (act.get("goal") or "").strip()
            if not plugin or not goal:
                results.append({"type": "extend", "status": "error", "msg": "missing plugin/goal"})
                continue
            try:
                res = extend_plugin(plugin, goal)
                results.append({"type": "extend", "status": res.get("status"), "result": res})
            except ExecutorError as e:
                results.append({"type": "extend", "status": "error", "error": classify_error(e).__dict__})
            except Exception as e:
                results.append({"type": "extend", "status": "error", "error": f"{type(e).__name__}: {e}"})
        else:
            results.append({"type": act.get("type"), "status": "error", "msg": "unknown action"})
    return results

def main():
    print(BANNER)
    client = OpenAIClient()
    docket = Docket(namespace=SESSION)
    directives = load_directives()

    for raw in sys.stdin:
        user_text = raw.strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print("bye")
            return

        # Build messages and call model
        msgs = _build_messages(user_text, docket, directives)
        try:
            raw_out = client.chat(msgs, response_format={"type": "json_object"})
        except Exception as e:
            print(f"[transport error] {type(e).__name__}: {e}")
            continue

        data = _parse_json(raw_out)
        if not data or "assistant_message" not in data:
            # Fallback: simple chat echo if model missed the contract
            print("I couldn’t parse a plan. Could you rephrase?")
            save_turn(SESSION, "user", user_text)
            save_turn(SESSION, "assistant", "I couldn’t parse a plan. Could you rephrase?")
            continue

        # Persist directive updates first (so we obey them immediately next turn AND next session)
        if data.get("directive_updates"):
            try:
                save_directives(data["directive_updates"])
                directives = load_directives()  # refresh local copy
            except Exception:
                pass

        # Persist facts proposed by the model
        for f in data.get("facts_to_save") or []:
            k, v = f.get("key"), f.get("value")
            if k:
                save_fact(SESSION, k, v)

        # Add tasks to docket
        for t in data.get("tasks_to_add") or []:
            title = t.get("title"); prio = (t.get("priority") or "normal").lower()
            if title:
                docket.add(title=title, priority=prio)

        # Print assistant’s message (natural language)
        reply = data.get("assistant_message") or ""
        if reply:
            print(reply)

        # If the mode is "act", execute actions and summarize results
        if data.get("mode") == "act":
            results = _handle_actions(data.get("actions") or [])
            summary = json.dumps({"actions_ran": results, "docket": docket.list_tasks()}, indent=2)
            print(summary)
            # Save a compact version into memory
            save_turn(SESSION, "assistant", f"{reply}\n{summary}")
            save_turn(SESSION, "user", user_text)
            continue

        # If mode is "ask", the assistant_message should contain the questions already
        # If mode is "respond", just a normal reply
        save_turn(SESSION, "assistant", reply)
        save_turn(SESSION, "user", user_text)

if __name__ == "__main__":
    main()
