import os, json, time
from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket

# NEW imports
from executor.core import router
from executor.core.registry import SpecialistRegistry
from executor.core.dispatcher import Dispatcher

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
        docket = Docket(namespace=SESSION)
        directives = _load_directives()
        registry = SpecialistRegistry()
        dispatcher = Dispatcher(registry)

        # Handle TODO tasks
        tasks = [t for t in docket.list_tasks() if t.get("status") == "todo"]
        if tasks:
            task = tasks[0]
            # For now just mark complete, but could dispatch later
            docket.complete(task["id"])
            print(f"[Scheduler] Completed task: {task['title']}")
            return "worked"

        # Brainstorm if idle + autonomous
        if directives.get("autonomous_mode") and directives.get("scope"):
            scope = directives["scope"]
            # Ask Router for brainstorming ideas
            data = router.route(f"Brainstorm new ideas for scope: {scope}", session=SESSION)

            msg = data.get("assistant_message", "")
            if msg:
                print(f"[Scheduler] {msg}")

            # Add any ideas as [idea] tasks
            for idea in data.get("ideas", []):
                docket.add(f"[idea] {idea}", priority="normal")

            # Dispatch any ready actions
            for a in data.get("actions", []):
                if a.get("status") == "ready":
                    result = dispatcher.dispatch(a)
                    print(f"[Scheduler] Dispatched action: {a['goal']} → {result.get('status')}")

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