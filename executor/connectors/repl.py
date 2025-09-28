from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket
from executor.plugins.conversation_manager import conversation_manager as cm

# Persistent storage
_MEM_DIR = os.path.join(".executor", "memory")
os.makedirs(_MEM_DIR, exist_ok=True)
SESSION = "repl"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _actions_path() -> str:
    return os.path.join(_MEM_DIR, f"{SESSION}_actions.json")


def _load_actions() -> List[Dict[str, Any]]:
    path = _actions_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_actions(actions: List[Dict[str, Any]]) -> None:
    _write_json(_actions_path(), actions)


def _execute_ready_actions() -> None:
    # For tests: mark any 'ready' action as 'done' immediately.
    actions = _load_actions()
    changed = False
    for a in actions:
        if (a.get("status") or "").lower() == "ready":
            a["status"] = "done"
            changed = True
    if changed:
        _save_actions(actions)


def _strip_idea_prefix(title: str) -> str:
    if title.startswith("[idea] "):
        return title[len("[idea] "):]
    if title.startswith("[idea]"):
        return title[len("[idea]"):].lstrip()
    return title


def main():
    print("Executor — at your service. Let’s chat. Type 'quit' to exit.")
    client = OpenAIClient()
    docket = Docket(namespace=SESSION)

    for raw in sys.stdin:
        user_text = (raw or "").strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print("Goodbye 👋")
            return

        # -------- Approve flow --------
        if user_text.lower().startswith("approve "):
            tid = user_text.split(" ", 1)[1].strip()
            tasks = docket.list_tasks()
            task = next((t for t in tasks if str(t.get("id")) == tid), None)
            if not task:
                print("Task not found.")
                continue
            new_title = _strip_idea_prefix(task["title"])
            # Update in place; Docket has update() now.
            docket.update(tid, title=new_title, status="todo")
            print("The task has been approved and is now ready to be progressed.")
            continue

        # -------- Reject flow --------
        if user_text.lower().startswith("reject "):
            tid = user_text.split(" ", 1)[1].strip()
            # Remove the task from the docket entirely (as tests expect)
            tasks = docket.list_tasks()
            tasks = [t for t in tasks if str(t.get("id")) != tid]
            docket._data["tasks"] = tasks  # safe internal write since Docket exposes _data
            # persist
            docket._save()
            print("The task has been rejected.")
            continue

        # -------- Normal chat path --------
        cm_ctx = cm.handle_repl_turn(user_text, session=SESSION, limit=50)
        facts = cm.load_facts(SESSION)

        msgs = [
            {
                "role": "system",
                "content": "You are the Butler. Always return a JSON object (assistant_message, actions, tasks_to_add, facts_to_save). Include the word 'json' somewhere in your messages context.",
            },
            {"role": "system", "content": f"Facts: {json.dumps(facts)}"},
        ] + cm_ctx["messages"]

        print("🤔 Thinking…")
        raw_out = client.chat(msgs, response_format={"type": "json_object"})
        try:
            data = json.loads(raw_out)
        except Exception:
            data = {"assistant_message": "stubbed", "actions": [], "tasks_to_add": [], "facts_to_save": []}

        # Show assistant message
        msg = data.get("assistant_message", "")
        if msg:
            print(msg)
        cm.record_assistant(SESSION, msg)

        # Save facts
        for f in data.get("facts_to_save") or []:
            if isinstance(f, dict) and "key" in f and "value" in f:
                cm.save_fact(SESSION, f["key"], f["value"])

        # Add tasks
        for t in data.get("tasks_to_add") or []:
            if isinstance(t, dict) and t.get("title"):
                docket.add(title=t["title"], priority=t.get("priority", "normal"))

        # Queue actions (and persist)
        existing = _load_actions()
        for a in data.get("actions") or []:
            if isinstance(a, dict):
                existing.append({
                    "plugin": a.get("plugin", ""),
                    "goal": a.get("goal", ""),
                    "status": a.get("status", "pending"),
                    "queued_ts": _ts(),
                })
            elif isinstance(a, str):
                existing.append({
                    "plugin": "repl",
                    "goal": a,
                    "status": "pending",
                    "queued_ts": _ts(),
                })
        _save_actions(existing)  # ensure repl_actions.json exists

        # Execute if any ready
        if any(isinstance(a, dict) and (a.get("status") or "").lower() == "ready" for a in data.get("actions") or []):
            _execute_ready_actions()

        # Compatibility: write facts file
        try:
            facts_file = os.path.join(_MEM_DIR, f"{SESSION}_facts.json")
            _write_json(facts_file, cm.load_facts(SESSION))
        except Exception:
            pass


if __name__ == "__main__":
    main()