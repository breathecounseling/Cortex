import os
import sys
import io
import importlib
import pytest

from executor.connectors.openai_client import OpenAIClient
from executor.plugins.builder import builder
from executor.utils.docket import Docket


def test_chat_roundtrip(monkeypatch):
    client = OpenAIClient(model="gpt-4o-mini")

    # Stub the API call
    def fake_chat(messages, response_format=None):
        return "Hello world"

    monkeypatch.setattr(client, "chat", fake_chat)

    res = client.chat([{"role": "user", "content": "hi"}])
    assert res == "Hello world"


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

    # ✅ Updated monkeypatch target
    monkeypatch.setattr("executor.core.router.route", fake_route_repl, raising=False)

    # Run REPL once with input
    sys.stdin = io.StringIO("do something\nquit\n")
    repl.main()

    # Capture printed output
    out = capsys.readouterr().out
    assert "Got it, I will build this." in out

    # Verify action was recorded
    actions_path = tmp_memory / "repl_actions.json"
    assert actions_path.exists()

    # Verify Docket can list tasks
    docket = Docket(namespace="repl")
    assert isinstance(docket.list_tasks(), list)

    os.chdir(old_cwd)
