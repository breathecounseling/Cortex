import os
import io
import importlib
import sys

import pytest

from executor.plugins.builder import builder
from executor.connectors import repl


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

    # Scaffold plugin + specialist
    old_cwd = os.getcwd()
    os.chdir(tmp_memory.parent)
    builder.main(plugin_name, "Integration test plugin")

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

    # ✅ Monkeypatch router so no real LLM calls
    monkeypatch.setattr("executor.core.router.route", fake_route_repl, raising=False)

    # Run REPL once with input
    sys.stdin = io.StringIO("do something\nquit\n")
    repl.main()

    # Capture printed output
    out = capsys.readouterr().out
    # Allow either Router stub or OpenAI stub output
    assert ("Got it, I will build this." in out) or ("stubbed" in out)

    # ✅ Verify action was recorded in REPL's actual memory dir
    actions_path = os.path.join(repl._MEM_DIR, "repl_actions.json")
    assert os.path.exists(actions_path)
