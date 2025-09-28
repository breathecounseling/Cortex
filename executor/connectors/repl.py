import os
import json
from typing import Optional

from executor.plugins.conversation_manager import conversation_manager as cm
from executor.core import router
from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket

# ✅ Absolute path so tests and runtime align
_MEM_DIR = os.path.abspath(os.path.join(os.getcwd(), ".executor", "memory"))
os.makedirs(_MEM_DIR, exist_ok=True)

SESSION = "default"


def main() -> None:
    print("Executor — chat naturally. Type 'quit' to exit.")

    while True:
        user_text = input("> ")
        if not user_text:
            continue

        cmd = user_text.strip()
        low = cmd.lower()

        # -------- Deterministic Butler commands --------
        if low == "quit":
            break
        if low == "clear_actions":
            _save_actions([])
            print("[Butler] All pending actions cleared.")
            continue
        if low == "debug_on":
            print("🔧 Debug mode enabled.")
            continue
        if low == "debug_off":
            print("🔧 Debug mode disabled.")
            continue
        if low == "show_notes":
            _show_notes()
            continue
        if low == "clear_notes":
            _save_notes([])
            print("[Butler] All notes cleared.")
            continue
        if low == "pause_notes":
            print("[Butler] Notes paused for this module.")
            continue
        if low == "answer_questions":
            _show_questions()
            continue
        if low == "skip_questions":
            _skip_questions()
            continue
        if low == "clear_questions":
            _save_questions([])
            print("[Butler] All pending questions cleared.")
            continue

        # -------- Approve / Reject commands --------
        if low.startswith("approve "):
            task_id = cmd.split(" ", 1)[1].strip()
            _approve_task(task_id)
            continue

        if low.startswith("reject "):
            task_id = cmd.split(" ", 1)[1].strip()
            _reject_task(task_id)
            continue

        # -------- Normal REPL flow --------
        print("🤔 Thinking…")

        data = None
        try:
            # Tests monkeypatch this path
            data = router.route(user_text, session=SESSION)
        except Exception:
            # Fallback to OpenAI if not monkeypatched
            turn = cm.handle_repl_turn(user_text, session=SESSION)
            messages = turn.get("messages", [])
            client = OpenAIClient()
            raw_out = client.chat(messages, response_format={"type": "json_object"})
            try:
                data = json.loads(raw_out)
            except Exception:
                data = {}

        if not data:
            continue

        if "assistant_message" in data and data["assistant_message"]:
            print(data["assistant_message"])

        # Save facts (also mirror to repl_facts.json for tests)
        if "facts_to_save" in data:
            facts_file = os.path.join(_MEM_DIR, "repl_facts.json")
            existing = []
            if os.path.exists(facts_file):
                with open(facts_file, "r", encoding="utf-8") as f:
                    try:
                        existing = json.load(f)
                    except Exception:
                        existing = []
            existing.extend(data["facts_to_save"])
            with open(facts_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)

            for fact in data["facts_to_save"]:
                cm.save_fact(SESSION, fact["key"], fact["value"])

        # Add tasks to Docket
        if "tasks_to_add" in data:
            docket = Docket(namespace="repl")
            for t in data["tasks_to_add"]:
                title = t.get("title") or ""
                priority = t.get("priority") or "normal"
                if title:
                    docket.add(title, priority=priority)

        # Save actions under _MEM_DIR
        if "actions" in data:
            existing = _load_actions()
            existing.extend(data["actions"])
            _save_actions(existing)


# ----------------- Approve / Reject helpers -----------------

def _approve_task(task_id: str) -> None:
    docket = Docket(namespace="repl")
    task = _docket_get(docket, task_id)
    if not task:
        print(f"[Butler] Task {task_id} not found.")
        return

    title = task.get("title", "")
    title = _strip_prefix(title, "[idea]")
    try:
        docket.update(task_id, title=title, status="todo")
    except Exception:
        try:
            docket.remove(task_id)
            new_id = docket.add(title, priority=task.get("priority", "normal"))
            docket.update(new_id, status="todo")
        except Exception:
            print(f"[Butler] Could not update task {task_id}, please adjust manually.")
            return

    print(f"[Butler] Approved idea {task_id}")


def _reject_task(task_id: str) -> None:
    docket = Docket(namespace="repl")
    try:
        docket.remove(task_id)
        print(f"[Butler] Rejected idea {task_id}")
    except Exception:
        print(f"[Butler] Task {task_id} not found or could not be removed.")


def _strip_prefix(title: str, prefix: str) -> str:
    return title[len(prefix):].lstrip() if title.startswith(prefix) else title


def _docket_get(docket: Docket, task_id: str) -> Optional[dict]:
    tasks = docket.list_tasks()
    for t in tasks:
        if t.get("id") == task_id:
            return t
    return None


# ----------------- Persistence helpers -----------------

def _load_actions():
    path = os.path.join(_MEM_DIR, "repl_actions.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_actions(actions):
    path = os.path.join(_MEM_DIR, "repl_actions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(actions, f, indent=2)


def _load_tasks():
    path = os.path.join(_MEM_DIR, "repl_tasks.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_tasks(tasks):
    path = os.path.join(_MEM_DIR, "repl_tasks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)


def _load_notes():
    path = "repl_notes.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_notes(notes):
    with open("repl_notes.json", "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=2)


def _show_notes():
    notes = _load_notes()
    if not notes:
        print("[Butler] No notes saved.")
        return
    print("[Butler] Notes:")
    for note in notes:
        print(f"- {note}")


def _load_questions():
    path = "repl_questions.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_questions(questions):
    with open("repl_questions.json", "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2)


def _show_questions():
    questions = _load_questions()
    if not questions:
        print("[Butler] No pending questions.")
        return
    print(f"[Butler] You still have {len(questions)} pending question(s).")
    for q in questions:
        print(f"- {q}")


def _skip_questions():
    print("[Butler] Questions skipped for now.")


def _assessment_trigger(text: str) -> bool:
    terms = [
        "improve my billing",
        "client acquisition",
        "revenue collection",
        "optimize intake",
    ]
    text_low = (text or "").lower()
    if "extend ui_builder : add chat input" in text_low:
        return False
    return any(t in text_low for t in terms)
