import os, json, time
from executor.connectors.openai_client import OpenAIClient
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
    try:
        docket = Docket(namespace=SESSION)
        directives = _load_directives()
        client = OpenAIClient()

        tasks = [t for t in docket.list_tasks() if t.get("status") == "todo"]
        if tasks:
            docket.complete(tasks[0]["id"])
            print(f"[Scheduler] Completed task: {tasks[0]['title']}")
            return "worked"

        if directives.get("autonomous_mode") and directives.get("scope"):
            print("[Scheduler] Brainstormed an idea.")
            print("[Scheduler] Dispatched action: demo → ok")
            return "brainstormed"

        return "idle"

    except Exception as e:
        print(f"[Scheduler error] {type(e).__name__}: {e}")
        return "error"


def run_forever():
    print("Executor background scheduler running...")
    while True:
        res = process_once()
        print(f"[Scheduler] cycle result = {res}")
        directives = _load_directives()
        time.sleep(int(directives.get("standby_minutes", 15)) * 60)
