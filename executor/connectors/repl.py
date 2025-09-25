# executor/connectors/repl.py
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List

from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket

# ----------------------------- Memory bridges -----------------------------
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

def _turns_path(session: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}.jsonl")

def _facts_path(session: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}_facts.json")

def _globals_path() -> str:
    return os.path.join(_MEM_DIR, "global_directives.json")

def _save_turn_fallback(session: str, role: str, content: Any) -> None:
    rec = {"ts": _ts(), "role": role, "content": content}
    with open(_turns_path(session), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def _load_turns_fallback(session: str) -> List[Dict[str, str]]:
    p = _turns_path(session)
    if not os.path.exists(p):
        return []
    out: List[Dict[str, str]] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("role") in {"user", "assistant", "system"}:
                    out.append({"role": rec["role"], "content": rec["content"]})
            except Exception:
                continue
    return out[-50:]

def _load_facts_fallback(session: str) -> Dict[str, Any]:
    p = _facts_path(session)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_fact_fallback(session: str, key: str, value: Any) -> None:
    data = _load_facts_fallback(session)
    data[key] = value
    with open(_facts_path(session), "w", encoding="utf-8") as f:
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

# ----------------------------- Directives -----------------------------
_DEFAULT_DIRECTIVES: Dict[str, Any] = {
    "interaction_style": "chat-first",
    "clarification_mode": "one-at-a-time",
    "autonomous_mode": False,
    "standby_minutes": 15,
    "scope": None,
    "brainstorm_paused": [],
}

def load_directives() -> Dict[str, Any]:
    path = _globals_path()
    merged = dict(_DEFAULT_DIRECTIVES)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged.update(data or {})
        except Exception:
            pass
    return merged

# ----------------------------- Helpers -----------------------------
def _assessment_trigger(text: str) -> bool:
    t = text.lower()
    patterns = ["improve", "tighten", "optimiz", "streamlin", "help with", "let's talk", "my goal is", "how can i"]
    return any(p in t for p in patterns)

def _parse_json(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {}

# ----------------------------- Main -----------------------------
SESSION = "repl"

def main():
    print("Executor — chat naturally. Type 'quit' to exit.")
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

        # Approve/reject idea tasks
        if user_text.lower().startswith("approve "):
            tid = user_text.split(" ", 1)[1].strip()
            tasks = docket.list_tasks()
            for t in tasks:
                if t["id"] == tid and t["title"].startswith("[idea]"):
                    t["title"] = t["title"].replace("[idea] ", "", 1)
                    t["status"] = "todo"
                    docket._save()
                    print(f"✅ Promoted idea {tid} to TODO: {t['title']}")
                    break
            continue

        if user_text.lower().startswith("reject "):
            tid = user_text.split(" ", 1)[1].strip()
            tasks = docket.list_tasks()
            new_tasks = [t for t in tasks if t["id"] != tid]
            if len(new_tasks) != len(tasks):
                docket._data["tasks"] = new_tasks
                docket._save()
                print(f"❌ Rejected idea {tid}, removed from docket.")
            continue

        msgs = [
            {"role": "system", "content": "You are the Cortex Executor Orchestrator."},
            {"role": "system", "content": f"Directives: {json.dumps(directives)}"},
            {"role": "system", "content": f"Facts: {json.dumps(load_facts(SESSION))}"},
            {"role": "system", "content": f"Docket: {json.dumps(docket.list_tasks())}"},
            {"role": "system", "content": (
                "Behaviors:\n"
                "- If input implies goals/future-cast (improve, tighten, help with, let's talk, my goal is, how can I), "
                "enter ASSESSMENT MODE: ask dynamic diagnostic questions, infer missing info, do gap analysis vs facts, "
                "and propose objectives/tasks.\n"
                "- Else: handle as chat, brainstorm, or actions.\n"
                "- Always return JSON {assistant_message, mode, questions, facts_to_save, tasks_to_add, directive_updates, ideas, actions}."
            )},
            {"role": "user", "content": user_text},
        ]

        raw_out = client.chat(msgs, response_format={"type": "json_object"})
        data = _parse_json(raw_out)

        print(data.get("assistant_message", ""))
            for f in data.get("facts_to_save") or []:
                if isinstance(f, dict):
                    k, v = f.get("key"), f.get("value")
                    if k:
                        save_fact(SESSION, k, v)
                elif isinstance(f, str):
                    # fallback: treat as bare value, try to map to last pending question if available
                    save_fact(SESSION, "unspecified_fact", f.strip())


if __name__ == "__main__":
    main()
