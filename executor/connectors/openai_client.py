# executor/connectors/repl.py
from __future__ import annotations
import os
import json
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime

# Core capabilities we’ll call when the model decides to “act”
from executor.connectors.openai_client import OpenAIClient
from executor.utils.error_handler import ExecutorError, classify_error

# Lightweight persistent docket for tasks/prereqs
from executor.utils.docket import Docket

SESSION = "repl"
BANNER = "Executor — chat naturally, or ask it to build. Type 'quit' to exit."

# ---- Minimal memory bridge: use conversation_manager if present; otherwise fallback to JSONL ----
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

def _fallback_path(name: str) -> str:
    return os.path.join(_MEM_DIR, f"{name}.jsonl")

def _save_turn_fallback(session: str, role: str, content: Any) -> None:
    rec = {"ts": datetime.utcnow().isoformat(), "role": role, "content": content}
    with open(_fallback_path(session), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def _load_turns_fallback(session: str) -> List[Dict[str, str]]:
    path = _fallback_path(session)
    if not os.path.exists(path):
        return []
    turns = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("role") in {"user", "assistant", "system"}:
                    turns.append({"role": rec["role"], "content": rec["content"]})
            except Exception:
                continue
    return turns[-50:]  # cap history

_FACTS_PATH = os.path.join(_MEM_DIR, f"{SESSION}_facts.json")

def _load_facts_fallback(_: str) -> Dict[str, Any]:
    if not os.path.exists(_FACTS_PATH):
        return {}
    try:
        with open(_FACTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_fact_fallback(_: str, key: str, value: Any) -> None:
    data = _load_facts_fallback(SESSION)
    data[key] = value
    with open(_FACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)

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
    if _CM_LOAD_FACTS:
        try:
            return _CM_LOAD_FACTS(session)
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

# ---- Orchestrator: model returns a structured “ask or act” plan we follow deterministically ----

STRUCTURE_INSTRUCTION = (
    "Reply ONLY with JSON matching this schema:\n"
    "{\n"
    '  "mode": "ask" | "act",\n'
    '  "question": string (when mode="ask"),\n'
    '  "facts_to_save": [{"key": string, "value": any}] (optional),\n'
    '  "tasks_to_add": [{"title": string, "priority": "low"|"normal"|"high"}] (optional),\n'
    '  "actions": [\n'
    '     {"type": "extend", "plugin": string, "goal": string}\n'
    '  ] (when mode="act")\n'
    "}\n"
    "If you are missing information to proceed safely, prefer mode='ask' and ask ONE concrete question.\n"
)

def _build_context_messages(user_text: str, docket: Docket) -> List[Dict[str, str]]:
    facts = load_facts(SESSION)
    turns = get_turns(SESSION)
    # system primer keeps behavior consistent with your spec
    sys = {
        "role": "system",
        "content": (
            "You are the Cortex Executor Orchestrator. "
            "Interact conversationally. When unsure, ask ONE clear question. "
            "Save useful facts. Maintain a task docket of prerequisites. "
            "When ready, propose concrete actions (like extending a plugin). "
            "Do not produce code directly here—return actions for the host to execute."
        ),
    }
    memory = {"role": "system", "content": f"Facts: {json.dumps(facts)}"}
    tasks = {"role": "system", "content": f"Docket: {json.dumps(docket.list_tasks())}"}
    msgs = [sys, memory, tasks]
    msgs.extend(turns[-20:])  # recent context
    msgs.append({"role": "user", "content": user_text})
    # final guard to enforce structure
    msgs.append({"role": "system", "content": STRUCTURE_INSTRUCTION})
    return msgs

def _parse_json(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # lenient fenced extraction
        import re
        m = re.search(r"```json\s*(.*?)\s*```", s, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        # fallback: first {...}
        b = s.find("{"); e = s.rfind("}")
        if b != -1 and e != -1 and e > b:
            return json.loads(s[b:e+1])
        return {}

def _handle_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for act in actions or []:
        if act.get("type") == "extend":
            plugin = act.get("plugin", "").strip()
            goal = act.get("goal", "").strip()
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

    for raw in sys.stdin:
        user_text = raw.strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print("bye")
            return

        # Build structured context and ask the model for either a clarifying question or an action plan
        msgs = _build_context_messages(user_text, docket)
        try:
            # use JSON response format to nudge strict output
            raw_out = client.chat(msgs, response_format={"type": "json_object"})
        except Exception as e:
            print(f"[transport error] {type(e).__name__}: {e}")
            continue

        data = _parse_json(raw_out)
        mode = data.get("mode")

        # Save any facts the model proposed
        for f in data.get("facts_to_save", []) or []:
            k, v = f.get("key"), f.get("value")
            if k:
                save_fact(SESSION, k, v)

        # Add any tasks the model proposed
        for t in data.get("tasks_to_add", []) or []:
            title = t.get("title")
            prio = (t.get("priority") or "normal").lower()
            if title:
                docket.add(title=title, priority=prio)

        # Behavior: ask for clarification OR execute actions
        if mode == "ask":
            q = data.get("question") or "I need one clarifying detail to proceed."
            print(q)
            save_turn(SESSION, "user", user_text)
            save_turn(SESSION, "assistant", q)
            continue

        if mode == "act":
            actions = data.get("actions") or []
            results = _handle_actions(actions)
            # echo results to user, persist in memory
            pretty = json.dumps({"actions_ran": results, "docket": docket.list_tasks()}, indent=2)
            print(pretty)
            save_turn(SESSION, "user", user_text)
            save_turn(SESSION, "assistant", pretty)
            continue

        # If the model didn’t follow the contract, fall back to simple echo + ask again
        fallback = (
            "I couldn’t parse a plan. Tell me what you want, or say 'extend <plugin> : <goal>' explicitly."
        )
        print(fallback)
        save_turn(SESSION, "user", user_text)
        save_turn(SESSION, "assistant", fallback)

if __name__ == "__main__":
    main()
