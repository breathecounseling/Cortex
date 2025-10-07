import os
import json
import importlib
import pytest

from executor.utils.docket import Docket


def test_scheduler_brainstorm_and_dispatch(monkeypatch, tmp_path, capsys):
    # Setup temp memory
    memdir = tmp_path / ".executor" / "memory"
    memdir.mkdir(parents=True)
    directives = {"autonomous_mode": True, "scope": "test_scope", "standby_minutes": 0}
    with open(memdir / "global_directives.json", "w") as f:
        json.dump(directives, f)

    monkeypatch.chdir(tmp_path)

    # Reload scheduler fresh
    scheduler = importlib.reload(importlib.import_module("executor.middleware.scheduler"))

    # Stub router to return ideas + a ready action
    def fake_route(user_text, session="repl", directives=None):
        return {
            "assistant_message": "Brainstormed an idea.",
            "mode": "brainstorming",
            "questions": [],
            "ideas": ["new brainstormed idea"],
            "facts_to_save": [],
            "tasks_to_add": [],
            "directive_updates": {},
            "actions": [
                {"plugin": "dispatch_test_plugin", "goal": "test brainstorm goal", "status": "ready", "args": {}}
            ],
        }

    monkeypatch.setattr("executor.core.router.route", fake_route)

    # Stub Dispatcher to always succeed
    class DummyDispatcher:
        def dispatch(self, action):
            return {"status": "ok", "message": f"Handled {action['goal']}"}

    monkeypatch.setattr("executor.core.dispatcher.Dispatcher", lambda registry=None: DummyDispatcher())

    # Run one cycle
    res = scheduler.process_once()
    assert res == "brainstormed"

    # Capture output
    out = capsys.readouterr().out
    assert "Brainstormed an idea" in out or "Dispatched action" in out

    # Check docket for added idea task
    docket = Docket(namespace="repl")
    tasks = docket.list_tasks()
    assert any(t["title"].startswith("[idea] new brainstormed idea") for t in tasks)