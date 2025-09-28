import os
import json
from executor.plugins.conversation_manager import conversation_manager as cm
from executor.core import router

SESSION = "default"


def main() -> None:
    print("Executor — chat naturally. Type 'quit' to exit.")

    while True:
        user_text = input("> ")
        if not user_text:
            continue

        cmd = user_text.strip().lower()
        if cmd == "quit":
            break
        if cmd == "clear_actions":
            _save_actions([])
            print("[Butler] All pending actions cleared.")
            continue
        if cmd == "debug_on":
            print("🔧 Debug mode enabled.")
            continue
        if cmd == "debug_off":
            print("🔧 Debug mode disabled.")
            continue
        if cmd == "show_notes":
            _show_notes()
            continue
        if cmd == "clear_notes":
            _save_notes([])
            print("[Butler] All notes cleared.")
            continue
        if cmd == "pause_notes":
            print("[Butler] Notes paused for this module.")
            continue
        if cmd == "answer_questions":
            _show_questions()
            continue
        if cmd == "skip_questions":
            _skip_questions()
            continue
        if cmd == "clear_questions":
            _save_questions([])
            print("[Butler] All pending questions cleared.")
            continue

        # Normal REPL flow
        print("🤔 Thinking…")
        data = router.route(user_text, session=SESSION)

        # Show assistant message
        if "assistant_message" in data:
            print(data["assistant_message"])

        # Save facts
        if "facts_to_save" in data:
            for fact in data["facts_to_save"]:
                cm.save_fact(SESSION, fact["key"], fact["value"])

        # Save tasks
        if "tasks_to_add" in data:
            existing = _load_tasks()
            existing.extend(data["tasks_to_add"])
            _save_tasks(existing)

        # Save actions
        if "actions" in data:
            existing = _load_actions()
            existing.extend(data["actions"])
            _save_actions(existing)


# ----------------- Helpers for persistence -----------------

def _load_tasks():
    path = "repl_tasks.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_tasks(tasks):
    with open("repl_tasks.json", "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)


def _load_actions():
    path = "repl_actions.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_actions(actions):
    with open("repl_actions.json", "w", encoding="utf-8") as f:
        json.dump(actions, f, indent=2)


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
