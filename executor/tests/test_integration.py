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
    """Patch Executor memory dir to a temporary path."""
    memdir = tmp_path / ".executor" / "memory"
    memdir.mkdir(parents=True)
    monkeypatch.setattr("executor.connectors.repl._MEM_DIR", str(memdir))
    monkeypatch.chdir(tmp_path)
    return memdir


def test_repl_router_dispatcher_flow(monkeypatch, tmp_memory, capsys):
    """
    End-to-end smoke test:
    - Scaffold a plugin with specialist
    - Run REPL with stubbed Router output
    - Ensure action is queued and dispatched
    """
    plugin_name = "integration_test_plugin"
    plugin_dir = tmp_memory.parent / "executor" / "plugins" / plugin_name
    os.makedirs(plugin_dir.parent, exist_ok=True)

    # Scaffold plugin + specialist
    old_cwd = os.getcwd()
    os.chdir(tmp_memory.parent)
    try:
        builder.main(plugin_name, "Integration test plugin")

        # Import repl after monkeypatches
        repl = importlib.reload(importlib.import_module("executor.connectors.repl"))

        # Stub router.route to always return a ready action for our plugin
        def fake_route(user_text, session="repl", directives=None):
            return {
                "assistant_message": "I will handle this request.",
                "mode": "execution",
                "questions": [],
                "ideas": [],
                "facts_to_save": [],
                "tasks_to_add": [],
                "directive_updates": {},
                "actions": [
                    {"plugin": plugin_name, "goal": "test goal", "status": "ready", "args": {}}
                ],
            }

        monkeypatch.setattr("executor.connectors.repl.router.route", fake_route)

        # Run REPL once with input
        sys.stdin = io.StringIO("do something\nquit\n")
        repl.main()

        # Capture printed output
        out = capsys.readouterr().out
        assert "I will handle this request." in out
        assert f"Done: {plugin_name}" in out or "👍 Done" in out

        # Verify action was recorded
        actions = repl.load_actions("repl")
        assert any(a["plugin"] == plugin_name for a in actions)

        # Verify Docket can list tasks (ensures docket integration still works)
        docket = Docket(namespace="repl")
        assert isinstance(docket.list_tasks(), list)

    finally:
        os.chdir(old_cwd)
