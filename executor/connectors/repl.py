from __future__ import annotations
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from executor.connectors.openai_client import OpenAIClient
from executor.plugins.builder.extend_plugin import extend_plugin
from executor.utils.docket import Docket
from executor.plugins.conversation_manager import conversation_manager as cm

_MEM_DIR = os.path.join(".executor", "memory")
os.makedirs(_MEM_DIR, exist_ok=True)

SESSION = "repl"
debug_mode = False


def _assessment_trigger(text: str) -> bool:
    """
    Legacy helper: detect if input is a business/assessment style query.
    Used by tests in test_assessment_trigger.py.
    """
    if not text:
        return False
    t = text.lower()
    keywords = ["billing", "invoice", "revenue", "client", "acquisition", "intake", "budget"]
    return any(k in t for k in keywords)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_actions(session: str) -> List[Dict[str, Any]]:
    path = os.path.join(_MEM_DIR, f"{session}_actions.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_actions(session: str, acts: List[Dict[str, Any]]) -> None:
    path = os.path.join(_MEM_DIR, f"{session}_actions.json")
    _write_json(path, acts)


def queue_action(session: str, plugin: str, goal: str, status: str = "pending") -> str:
    acts = load_actions(session)
    aid = str(len(acts) + 1)
    acts.append({"id": aid, "plugin": plugin, "goal": goal, "status": status, "queued_ts": _ts()})
    save_actions(session, acts)
    return aid


def clear_actions(session: str) -> None:
    save_actions(session, [])


def _execute_ready_actions(docket: Docket) -> None:
    ready = [a for a in load_actions(SESSION) if a["status"] == "ready"]
    for a in ready:
        plugin = a["plugin"]
        goal = a["goal"]
        try:
            res = extend_plugin(plugin, goal)
            ok = res.get("status") == "ok"
            a["status"] = "done" if ok else "error"
        except Exception as e:
            a["status"] = "error"
            print(f"❌ Build error for {plugin}: {type(e).__name__}: {e}", flush=True)
    save_actions(SESSION, ready)


def main():
    global debug_mode
    print("Executor — at your service. Let’s chat. Type 'quit' to exit.", flush=True)
    client = OpenAIClient()
    docket = Docket(namespace=SESSION)

    for raw in sys.stdin:
        user_text = raw.strip()
        if not user_text:
            continue

        if user_text.lower() in {"quit", "exit"}:
            print("Goodbye 👋", flush=True)
            return

        if user_text.lower() == "clear_actions":
            clear_actions(SESSION)
            print("All pending actions cleared.")
            continue

        # Conversation manager
        cm_result = cm.handle_repl_turn(user_text, session=SESSION, limit=50)
        facts = cm.load_facts(SESSION)

        msgs = [
            {"role": "system", "content": "Butler contract"},
            {"role": "system", "content": f"Facts: {json.dumps(facts)}"},
            *cm_result["messages"],
        ]

        print("🤔 Thinking…", flush=True)
        raw_out = client.chat(msgs, response_format={"type": "json_object"})
        data = {}
        try:
            data = json.loads(raw_out)
        except Exception:
            pass

        msg = data.get("assistant_message", "")
        if msg:
            print(msg, flush=True)
        cm.record_assistant(SESSION, msg)

        # Save facts
        for f in data.get("facts_to_save") or []:
            if isinstance(f, dict):
                cm.save_fact(SESSION, f["key"], f["value"])

        # Save tasks
        for t in data.get("tasks_to_add") or []:
            if isinstance(t, dict) and t.get("title"):
                docket.add(title=t["title"], priority=t.get("priority", "normal"))

        # Queue actions
        actions = data.get("actions") or []
        for a in actions:
            if isinstance(a, dict):
                queue_action(SESSION, a.get("plugin", ""), a.get("goal", ""), a.get("status", "pending"))
            elif isinstance(a, str):
                queue_action(SESSION, "repl", a, "pending")

        # Execute ready actions
        if any(isinstance(a, dict) and (a.get("status") or "").lower() == "ready" for a in actions):
            _execute_ready_actions(docket)

        # Compatibility: write repl_facts.json for tests
        try:
            facts_file = os.path.join(_MEM_DIR, f"{SESSION}_facts.json")
            facts_dict = cm.load_facts(SESSION)
            with open(facts_file, "w", encoding="utf-8") as fh:
                json.dump(facts_dict, fh)
        except Exception:
            pass


if __name__ == "__main__":
    main()
