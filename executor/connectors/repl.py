from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List

from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket

# ----------------------------- Memory helpers -----------------------------
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

def _path(session: str, suffix: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}_{suffix}.json")

# Facts
def load_facts(session: str) -> Dict[str, Any]:
    p = _path(session, "facts")
    if os.path.exists(p):
        try:
            return json.load(open(p, "r", encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_fact(session: str, key: str, value: Any) -> None:
    p = _path(session, "facts")
    facts = load_facts(session)
    facts[key] = value
    with open(p, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)

# Turns
def load_turns(session: str) -> List[Dict[str, str]]:
    p = os.path.join(_MEM_DIR, f"{session}.jsonl")
    if not os.path.exists(p):
        return []
    turns = []
    for line in open(p, "r", encoding="utf-8"):
        try:
            rec = json.loads(line)
            if rec.get("role") in {"user", "assistant", "system"}:
                turns.append({"role": rec["role"], "content": rec["content"]})
        except Exception:
            continue
    return turns[-50:]

def save_turn(session: str, role: str, content: Any) -> None:
    rec = {"ts": _ts(), "role": role, "content": content}
    with open(os.path.join(_MEM_DIR, f"{session}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

# Pending questions
def load_pending(session: str) -> List[Dict[str, Any]]:
    p = _path(session, "questions")
    if os.path.exists(p):
        try:
            return json.load(open(p, "r", encoding="utf-8"))
        except Exception:
            return []
    return []

def save_pending(session: str, qs: List[Dict[str, Any]]) -> None:
    p = _path(session, "questions")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(qs, f, indent=2)

def add_pending(session: str, scope: str, question: str) -> None:
    qs = load_pending(session)
    qs.append({"id": len(qs)+1, "scope": scope, "question": question, "status": "pending", "asked_ts": _ts()})
    save_pending(session, qs)

# ----------------------------- Directives -----------------------------
_DEFAULT_DIRECTIVES = {
    "interaction_style": "chat-first",
    "clarification_mode": "one-at-a-time",
    "autonomous_mode": False,
    "standby_minutes": 15,
    "scope": None,
    "brainstorm_paused": [],
}

def load_directives() -> Dict[str, Any]:
    p = _path("global", "directives")
    merged = dict(_DEFAULT_DIRECTIVES)
    if os.path.exists(p):
        try:
            merged.update(json.load(open(p, "r", encoding="utf-8")))
        except Exception:
            pass
    return merged

# ----------------------------- Helpers -----------------------------
def _parse_json(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {}

def _assessment_trigger(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in ["improve", "tighten", "optimiz", "streamlin", "help with", "my goal is", "how can i"])

# ----------------------------- Main -----------------------------
SESSION = "repl"

def main():
    print("Executor — chat naturally. Type 'quit' to exit.")
    client = OpenAIClient()
    docket = Docket(namespace=SESSION)
    directives = load_directives()

    reminded = False

    for raw in sys.stdin:
        user_text = raw.strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print("bye")
            return

        # Check pending questions first turn
        if not reminded:
            pending = [q for q in load_pending(SESSION) if q["status"] == "pending"]
            if pending:
                print(f"[Butler] You still have {len(pending)} pending question(s). You can 'answer_questions', 'skip_questions', or 'clear_questions'.")
            reminded = True

        # Handle pending question commands
        if user_text.lower().startswith("answer_questions"):
            qs = load_pending(SESSION)
            for q in qs:
                if q["status"] == "pending":
                    print(f"Q: {q['question']}")
                    ans = sys.stdin.readline().strip()
                    if ans:
                        save_fact(SESSION, q.get("scope","unspecified_fact"), ans.strip(".! "))
                        q["status"] = "answered"
            save_pending(SESSION, qs)
            continue

        if user_text.lower().startswith("skip_questions") or user_text.lower() in {"not now", "no", "skip"}:
            print("[Butler] Understood, I’ll hold the pending questions for later.")
            continue

        if user_text.lower().startswith("clear_questions"):
            save_pending(SESSION, [])
            print("[Butler] All pending questions cleared.")
            continue

        # Messages for model
        msgs = [
            {"role": "system", "content": "You are the Cortex Executor Orchestrator."},
            {"role": "system", "content": f"Directives: {json.dumps(directives)}"},
            {"role": "system", "content": f"Facts: {json.dumps(load_facts(SESSION))}"},
            {"role": "system", "content": f"Docket: {json.dumps(docket.list_tasks())}"},
            {"role": "system", "content": (
                "Behaviors:\n"
                "- If the user describes extending, building, approving, or rejecting in natural language, infer the plugin and goal and output them in 'actions'.\n"
                "- If input implies goals/future-cast, enter assessment mode and generate diagnostic questions. Save unanswered ones to pending questions.\n"
                "- If the user replies with a short bare answer right after a question, map it back to the last pending question and save as a fact.\n"
                "- Always return JSON {assistant_message, mode, questions, facts_to_save, tasks_to_add, directive_updates, ideas, actions}."
            )},
            {"role": "user", "content": user_text},
        ]

        raw_out = client.chat(msgs, response_format={"type": "json_object"})
        data = _parse_json(raw_out)

        print(data.get("assistant_message", ""))

        # Save facts (defensive)
        for f in data.get("facts_to_save") or []:
            if isinstance(f, dict):
                k, v = f.get("key"), f.get("value")
                if k:
                    save_fact(SESSION, k, str(v).strip(".! "))
            elif isinstance(f, str):
                save_fact(SESSION, "unspecified_fact", f.strip(".! "))

        # Save tasks
        for t in data.get("tasks_to_add") or []:
            if isinstance(t, dict) and t.get("title"):
                docket.add(title=t["title"], priority=t.get("priority", "normal"))

        # Save pending questions if model proposes them
        for q in data.get("questions") or []:
            add_pending(SESSION, directives.get("scope") or "general", q)

if __name__ == "__main__":
    main()
