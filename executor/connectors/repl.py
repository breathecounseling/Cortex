from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from executor.utils.docket import Docket
from executor.plugins.conversation_manager import conversation_manager as cm
from executor.core import router  # ✅ use router for structured outputs

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
    docket = Docket(namespace=SESSION)

    for raw in sys.stdin:
        user_text = (raw or "").strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print("Goodbye 👋")
            return

        # Approve
        if user_text.lower().startswith("approve "):
            tid = user_text.split(" ", 1)[1].strip()
            tasks = docket.list_tasks()
            task = next((t for t in tasks if str(t.get("id")) == tid), None)
            if not task:
                print("Task not found.")
                continue
            docket.update(tid, title=_strip_idea_prefix(task["title"]), status="todo")
            print("The task has been approved and is now ready to be progressed.")
            continue

        # Reject (remove)
        if user_text.lower().startswith("reject "):
            tid = user_text.split(" ", 1)[1].strip()
            tasks = [t for t in docket.list_tasks() if str(t.get("id")) != tid]
            docket._data["tasks"] = tasks
            docket._save()
            print("The task has been rejected.")
            continue

        # Normal chat via Router
        cm_ctx = cm.handle_repl_turn(user_text, session=SESSION, limit=50)
        facts = cm.load_facts(SESSION)

        print("🤔 Thinking…")
        data = router.route(user_text, session=SESSION)

        # Show assistant message
        msg = data.get("assistant_message", "") or ""
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

        # Persist actions (create repl_actions.json even if empty)
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
        _save_actions(existing)  # ✅ now the file always exists

        # Execute immediately if anything was marked ready
        if any(isinstance(a, dict) and (a.get("status") or "").lower() == "ready" for a in data.get("actions") or []):
            _execute_ready_actions()

        # Compatibility: write facts snapshot
        try:
            _write_json(os.path.join(_MEM_DIR, f"{SESSION}_facts.json"), cm.load_facts(SESSION))
        except Exception:
            pass


if __name__ == "__main__":
    main()