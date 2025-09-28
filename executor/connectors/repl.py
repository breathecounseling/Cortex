from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket
from executor.plugins.conversation_manager import conversation_manager as cm

_MEM_DIR = os.path.join(".executor", "memory")
os.makedirs(_MEM_DIR, exist_ok=True)
SESSION = "repl"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_actions() -> List[Dict[str, Any]]:
    path = os.path.join(_MEM_DIR, f"{SESSION}_actions.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_actions(actions: List[Dict[str, Any]]) -> None:
    path = os.path.join(_MEM_DIR, f"{SESSION}_actions.json")
    _write_json(path, actions)


def _queue_action(plugin: str, goal: str, status: str = "pending") -> str:
    actions = _load_actions()
    aid = str(len(actions) + 1)
    actions.append(
        {"id": aid, "plugin": plugin, "goal": goal, "status": status, "queued_ts": _ts()}
    )
    _save_actions(actions)
    return aid


def _execute_ready_actions() -> None:
    actions = _load_actions()
    for a in actions:
        if (a.get("status") or "").lower() == "ready":
            a["status"] = "done"
    _save_actions(actions)


def _strip_idea_prefix(title: str) -> str:
    if title.startswith("[idea] "):
        return title[len("[idea] ") :]
    if title.startswith("[idea]"):
        return title[len("[idea]") :].lstrip()
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

        # Approve flow
        if user_text.lower().startswith("approve "):
            tid = user_text.split(" ", 1)[1].strip()
            task = next((t for t in docket.list_tasks() if str(t.get("id")) == tid), None)
            if task:
                new_title = _strip_idea_prefix(task["title"])
                docket.update(tid, title=new_title, status="todo")
                print("The task has been approved and is now ready to be progressed.")
            else:
                print("Task not found.")
            continue

        # Reject flow
        if user_text.lower().startswith("reject "):
            tid = user_text.split(" ", 1)[1].strip()
            docket.update(tid, status="rejected")
            print("The task has been rejected.")
            continue

        # Normal chat path
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
            data = {
                "assistant_message": "stubbed",
                "actions": [],
                "tasks_to_add": [],
                "facts_to_save": [],
            }

        msg = data.get("assistant_message", "")
        if msg:
            print(msg)
        cm.record_assistant(SESSION, msg)

        for f in data.get("facts_to_save") or []:
            if isinstance(f, dict) and "key" in f and "value" in f:
                cm.save_fact(SESSION, f["key"], f["value"])

        for t in data.get("tasks_to_add") or []:
            if isinstance(t, dict) and t.get("title"):
                docket.add(title=t["title"], priority=t.get("priority", "normal"))

        actions = data.get("actions") or []
        for a in actions:
            if isinstance(a, dict):
                _queue_action(a.get("plugin", ""), a.get("goal", ""), a.get("status", "pending"))
            elif isinstance(a, str):
                _queue_action("repl", a, "pending")

        if any(isinstance(a, dict) and (a.get("status") or "").lower() == "ready" for a in actions):
            _execute_ready_actions()

        try:
            facts_file = os.path.join(_MEM_DIR, f"{SESSION}_facts.json")
            _write_json(facts_file, cm.load_facts(SESSION))
        except Exception:
            pass


if __name__ == "__main__":
    main()
