# executor/middleware/scheduler.py
import os, json, time
from executor.connectors.openai_client import OpenAIClient
from executor.connectors import repl
from executor.utils.docket import Docket

SESSION = "repl"
_MEM_DIR = ".executor/memory"

def _load_directives():
    p = os.path.join(_MEM_DIR, "global_directives.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def process_once() -> str:
    """
    Run one scheduler cycle.
    Returns:
        "worked" if a task was processed,
        "brainstormed" if it added ideas,
        "idle" if nothing to do,
        "error" on exception.
    """
    try:
        docket = Docket(namespace="repl")
        directives = _load_directives()
        client = OpenAIClient()
        scope = directives.get("scope")

        # TODO tasks
        tasks = [t for t in docket.list_tasks() if t.get("status") == "todo"]
        if tasks:
            task = tasks[0]
            # fake "process task"
            docket.complete(task["id"])
            return "worked"

        # Brainstorm if idle + autonomous
        if directives.get("autonomous_mode") and scope:
            return "brainstormed"

        return "idle"

    except Exception as e:
        save_turn("repl", "assistant", f"[scheduler error] {type(e).__name__}: {e}")
        return "error"

def run_forever():
    print("Executor background scheduler running...")
    while True:
        directives = _load_directives()
        docket = Docket(namespace=SESSION)
        tasks = [t for t in docket.list_tasks() if t["status"] == "todo"]
        if tasks:
            print("Background: pending tasks:", tasks[0]["title"])
        else:
            if directives.get("autonomous_mode") and directives.get("scope"):
                print(f"Background: no tasks, considering brainstorm in scope={directives['scope']}")
        time.sleep(int(directives.get("standby_minutes", 15)) * 60)
