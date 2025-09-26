# executor/connectors/repl.py
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

# ----------------------------- Paths & helpers -----------------------------
_MEM_DIR = os.path.join(".executor", "memory")
os.makedirs(_MEM_DIR, exist_ok=True)

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _path(session: str, suffix: str) -> str:
    return os.path.join(_MEM_DIR, f"{session}_{suffix}.json")

SESSION = "repl"
debug_mode = False  # toggled by debug_on/debug_off

def _read_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ----------------------------- Pending questions -----------------------------
def load_pending_q(session: str) -> List[Dict[str, Any]]:
    return _read_json(_path(session, "questions"), [])

def save_pending_q(session: str, qs: List[Dict[str, Any]]) -> None:
    _write_json(_path(session, "questions"), qs)

def add_pending_q(session: str, scope: str, question: str) -> None:
    qs = load_pending_q(session)
    qs.append({"id": len(qs)+1, "scope": scope, "question": question, "status": "pending", "asked_ts": _ts()})
    save_pending_q(session, qs)

# ----------------------------- Action queue -----------------------------
def load_actions(session: str) -> List[Dict[str, Any]]:
    return _read_json(_path(session, "actions"), [])

def save_actions(session: str, acts: List[Dict[str, Any]]) -> None:
    _write_json(_path(session, "actions"), acts)

def queue_action(session: str, plugin: str, goal: str, status: str = "pending") -> str:
    acts = load_actions(session)
    norm_plugin = (plugin or "").strip().lower().replace(" ", "_").replace("-", "_")
    norm_goal = (goal or "").strip()
    for a in acts:
        if a["plugin"].strip().lower() == norm_plugin and a["goal"].strip() == norm_goal and a["status"] in {"pending","ready","running"}:
            return a["id"]  # already queued
    aid = str(len(acts)+1)
    acts.append({"id": aid, "plugin": norm_plugin, "goal": norm_goal, "status": status, "queued_ts": _ts()})
    save_actions(session, acts)
    return aid

def mark_last_action_ready(session: str) -> Optional[Dict[str, Any]]:
    acts = load_actions(session)
    for a in reversed(acts):
        if a["status"] == "pending":
            a["status"] = "ready"
            save_actions(session, acts)
            return a
    return None

def pop_ready_actions(session: str) -> List[Dict[str, Any]]:
    acts = load_actions(session)
    ready = [a for a in acts if a["status"] == "ready"]
    for a in acts:
        if a["status"] == "ready":
            a["status"] = "running"
    save_actions(session, acts)
    return ready

def complete_action(session: str, action_id: str, ok: bool) -> None:
    acts = load_actions(session)
    for a in acts:
        if a["id"] == action_id:
            a["status"] = "done" if ok else "error"
            a["completed_ts"] = _ts()
            break
    save_actions(session, acts)

def clear_actions(session: str) -> None:
    save_actions(session, [])

# ----------------------------- Directives -----------------------------
_DEFAULT_DIRECTIVES = {
    "interaction_style": "creative-partner",  # default style
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
            merged.update(_read_json(p, {}))
        except Exception:
            pass
    return merged

# ----------------------------- Instruction contract -----------------------------
STRUCTURE_INSTRUCTION = (
    "You are the Cortex Executor Orchestrator.\n"
    "Behaviors:\n"
    "- Act as a polite, creative, helpful partner.\n"
    "- Chat-first: respond naturally but ALWAYS emit structured JSON.\n"
    "- Only queue actions when the user clearly requests building/extending modules.\n"
    "- Always return JSON with keys: assistant_message, mode, questions, facts_to_save, tasks_to_add, directive_updates, ideas, actions.\n"
)

# ----------------------------- Model helpers -----------------------------
def _parse_json(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {}

_ADD_PAT = re.compile(r"\b(add|build|create|implement|extend)\b", re.I)

def _infer_action_from_text(text: str) -> Optional[Dict[str, Any]]:
    if not _ADD_PAT.search(text):
        return None
    plugin = "repl"
    m = re.search(r"\bextend\s+([a-zA-Z_][\w\-]*)", text, re.I)
    if m:
        plugin = m.group(1).lower().replace("-", "_")
    goal = text.strip()
    return {"plugin": plugin, "goal": goal, "status": "pending"}

# ----------------------------- Action execution -----------------------------
def _execute_ready_actions(docket: Docket) -> None:
    from executor.plugins.repo_analyzer import repo_analyzer
    from executor.plugins.builder import builder

    ready = pop_ready_actions(SESSION)
    for a in ready:
        raw_name, goal, aid = a["plugin"], a["goal"], a["id"]
        plugin = raw_name.strip().lower().replace(" ", "_").replace("-", "_")
        try:
            try:
                res = extend_plugin(plugin, goal)
            except Exception as e:
                if "plugin_not_found" in str(e):
                    if debug_mode:
                        print(f"[Butler] Plugin '{plugin}' not found. Scaffolding with builder…")
                    builder.main(plugin_name=plugin, description=f"Auto-generated for goal: {goal}")
                    res = extend_plugin(plugin, goal)
                else:
                    raise
            ok = res.get("status") == "ok"
            complete_action(SESSION, aid, ok)
            if debug_mode:
                print(json.dumps({"action": a, "result": res}, indent=2))
            elif ok:
                print(f"👍 Done building {plugin}.")
            else:
                print(f"❌ Build failed for {plugin}. See details above.")
        except Exception as e:
            complete_action(SESSION, aid, False)
            print(f"❌ Build error for {plugin}: {type(e).__name__}: {e}")

# ----------------------------- Main loop -----------------------------
def main():
    global debug_mode
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

        # Debug commands
        if user_text.lower() == "debug_on":
            debug_mode = True
            print("🔧 Debug mode enabled.")
            continue
        if user_text.lower() == "debug_off":
            debug_mode = False
            print("🔧 Debug mode disabled.")
            continue
        if user_text.lower() == "show_actions":
            acts = load_actions(SESSION)
            if acts:
                print(json.dumps(acts, indent=2))
            else:
                print("No actions queued.")
            continue
        if user_text.lower() == "clear_actions":
            clear_actions(SESSION)
            print("All pending actions cleared.")
            continue

        # simple “build now” intents
        if user_text.lower() in {"go ahead and build it", "proceed", "do it", "build now", "execute"}:
            a = mark_last_action_ready(SESSION)
            if a:
                if not debug_mode:
                    print(f"👌 Understood. Building {a['plugin']}…")
                else:
                    print(f"[Butler] Marked action ready: extend {a['plugin']}: {a['goal']}. Executing…")
                _execute_ready_actions(docket)
            else:
                print("I don’t have a pending action to build yet.")
            continue

        # pending question reminder on first input
        if not reminded:
            pqs = [q for q in load_pending_q(SESSION) if q["status"] == "pending"]
            if pqs:
                print(f"I have {len(pqs)} pending question(s) for you. You can 'answer_questions', 'skip_questions', or 'clear_questions'.")
            reminded = True

        # pending question commands
        low = user_text.lower()
        if low.startswith("answer_questions"):
            qs = load_pending_q(SESSION)
            for q in qs:
                if q["status"] == "pending":
                    print(f"Q: {q['question']}")
                    ans = sys.stdin.readline().strip()
                    if ans:
                        cm.save_fact(SESSION, (directives.get("scope") or "unspecified_fact"), ans.strip(".! "))
                        q["status"] = "answered"
            save_pending_q(SESSION, qs)
            continue
        if low.startswith("skip_questions") or low in {"not now", "no", "skip"}:
            print("Understood, I’ll hold the pending questions for later.")
            continue
        if low.startswith("clear_questions"):
            save_pending_q(SESSION, [])
            print("All pending questions cleared.")
            continue

        # Unified conversation manager
        cm_result = cm.handle_repl_turn(user_text, session=SESSION, limit=50)
        history_msgs = cm_result.get("messages", [])
        facts = cm.load_facts(SESSION)

        msgs = [
            {"role": "system", "content": STRUCTURE_INSTRUCTION},
            {"role": "system", "content": f"Directives: {json.dumps(directives)}"},
            {"role": "system", "content": f"Facts: {json.dumps(facts)}"},
            {"role": "system", "content": f"Docket: {json.dumps(docket.list_tasks())}"},
            *history_msgs,
        ]

        raw_out = client.chat(msgs, response_format={"type": "json_object"})
        data = _parse_json(raw_out)

        # friendly assistant message
        msg = data.get("assistant_message", "")
        if msg:
            print(msg)
        cm.record_assistant(SESSION, msg)

        # Save facts
        for f in data.get("facts_to_save") or []:
            if isinstance(f, dict):
                k, v = f.get("key"), f.get("value")
                if k:
                    cm.save_fact(SESSION, k, str(v).strip(".! "))
            elif isinstance(f, str):
                cm.save_fact(SESSION, "unspecified_fact", f.strip(".! "))

        # Save tasks
        for t in data.get("tasks_to_add") or []:
            if isinstance(t, dict) and t.get("title"):
                docket.add(title=t["title"], priority=t.get("priority", "normal"))

        # Queue actions
        actions = data.get("actions") or []
        for a in actions:
            plugin = (a.get("plugin") or "").strip()
            goal = (a.get("goal") or "").strip()
            status = (a.get("status") or "pending").strip().lower()
            if plugin and goal:
                aid = queue_action(SESSION, plugin, goal, status=status)
                if debug_mode:
                    print(f"[Butler] Queued action {aid}: extend {plugin}: {goal} (status={status})")

        # fallback inference
        if not actions:
            inferred = _infer_action_from_text(user_text)
            if inferred:
                aid = queue_action(SESSION, inferred["plugin"], inferred["goal"], status="pending")
                if debug_mode:
                    print(f"[Butler] Noted your build request and queued action {aid}: extend {inferred['plugin']}: {inferred['goal']} (status=pending).")
                else:
                    print(f"Okay, I’ve noted your build request for {inferred['plugin']}. Say 'do it' when ready.")
                continue

        if any((a.get("status") or "").lower() == "ready" for a in actions):
            _execute_ready_actions(docket)

if __name__ == "__main__":
    main()