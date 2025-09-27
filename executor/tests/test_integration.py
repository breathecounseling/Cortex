import os
import sys
import io
import importlib
import pytest

from executor.utils.docket import Docket
from executor.plugins.builder import builder


@pytest.fixture
def tmp_memory(monkeypatch, tmp_path):
    """Patch Executor memory dir to a temporary path for both REPL and Scheduler."""
    memdir = tmp_path / ".executor" / "memory"
    memdir.mkdir(parents=True)
    monkeypatch.setattr("executor.connectors.repl._MEM_DIR", str(memdir))
    monkeypatch.setattr("executor.middleware.scheduler._MEM_DIR", str(memdir))
    monkeypatch.chdir(tmp_path)
    return memdir


def test_full_cycle_repl_and_scheduler(monkeypatch, tmp_memory, capsys):
    """
    End-to-end test:
    - REPL handles user input → queues a ready action
    - Scheduler runs → brainstorms and dispatches action
    - Both update Docket and produce visible output
    """
    plugin_name = "full_cycle_plugin"
    plugin_dir = tmp_memory.parent / "executor" / "plugins" / plugin_name
    os.makedirs(plugin_dir.parent, exist_ok=True)

    # Scaffold plugin with specialist
    old_cwd = os.getcwd()
    os.chdir(tmp_memory.parent)
    builder.main(plugin_name, "Full-cycle integration test plugin")

    # Import repl fresh
    repl = importlib.reload(importlib.import_module("executor.connectors.repl"))

    # Stub Router for REPL → ready action
    def fake_route_repl(user_text, session="repl", directives=None):
        return {
            "assistant_message": "Got it, I will build this.",
            "mode": "execution",
            "questions": [],
            "ideas": [],
            "facts_to_save": [],
            "tasks_to_add": [],
            "directive_updates": {},
            "actions": [
                {"plugin": plugin_name, "goal": "initial goal", "status": "ready", "args": {}}
            ],
        }

    monkeypatch.setattr("executor.connectors.repl.router.route", fake_route_repl)

    # Run REPL once
    sys.stdin = io.StringIO("do something\nquit\n")
    repl.main()

    # Capture output
    out1 = capsys.readouterr().out
    assert "Got it, I will build this." in out1

    # Now import scheduler
    scheduler = importlib.reload(importlib.import_module("executor.middleware.scheduler"))

    # Stub Router for scheduler → brainstorm + action
    def fake_route_scheduler(user_text, session="repl", directives=None):
        return {
            "assistant_message": "Brainstormed background idea.",
            "mode": "brainstorming",
            "questions": [],
            "ideas": ["background improvement"],
            "facts_to_save": [],
            "tasks_to_add": [],
            "directive_updates": {},
            "actions": [
                {"plugin": plugin_name, "goal": "background goal", "status": "ready", "args": {}}
            ],
        }

    monkeypatch.setattr("executor.core.router.route", fake_route_scheduler)

    # Stub Dispatcher to always succeed
    class DummyDispatcher:
        def dispatch(self, action):
            return {"status": "ok", "message": f"Handled {action['goal']}"}

    monkeypatch.setattr("executor.core.dispatcher.Dispatcher", lambda registry=None: DummyDispatcher())

    # Enable autonomous mode
    directives = {"autonomous_mode": True, "scope": "test_scope", "standby_minutes": 0}
    with open(tmp_memory / "global_directives.json", "w") as f:
        import json
        json.dump(directives, f)

    # Run scheduler once
    res = scheduler.process_once()
    assert res == "brainstormed"

    out2 = capsys.readouterr().out
    assert "Brainstormed background idea." in out2 or "Dispatched action" in out2

    # Verify docket contains idea from scheduler
    docket = Docket(namespace="repl")
    tasks = docket.list_tasks()
    assert any("[idea] background improvement" in t["title"] for t in tasks)

    os.chdir(old_cwd)