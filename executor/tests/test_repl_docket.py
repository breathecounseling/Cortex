import os
import sys
import io
import importlib
import pytest

from executor.utils.docket import Docket


@pytest.fixture
def tmp_memory(monkeypatch, tmp_path):
    """Patch Executor memory dir to a temporary path."""
    memdir = tmp_path / ".executor" / "memory"
    memdir.mkdir(parents=True)
    monkeypatch.setattr("executor.connectors.repl._MEM_DIR", str(memdir))
    monkeypatch.setattr("executor.middleware.scheduler._MEM_DIR", str(memdir))
    monkeypatch.chdir(tmp_path)
    return memdir


def test_approve_reject_flow(tmp_memory):
    repl = importlib.reload(importlib.import_module("executor.connectors.repl"))
    docket = Docket(namespace="repl")

    # Add idea task
    tid = docket.add("[idea] Test new feature", priority="normal")

    # Approve it
    sys.stdin = io.StringIO(f"approve {tid}\nquit\n")
    repl.main()
    tasks = Docket(namespace="repl").list_tasks()
    assert tasks[0]["status"] == "todo"
    assert not tasks[0]["title"].startswith("[idea]")

    # Add another idea task
    tid2 = docket.add("[idea] Another idea", priority="normal")

    # Reject it
    sys.stdin = io.StringIO(f"reject {tid2}\nquit\n")
    repl.main()
    tasks = Docket(namespace="repl").list_tasks()
    ids = [t["id"] for t in tasks]
    assert tid2 not in ids


def test_repl_smoke_normal_flow(monkeypatch, tmp_memory, capsys):
    """Simulate a normal REPL input and stub OpenAIClient.chat."""
    repl = importlib.reload(importlib.import_module("executor.connectors.repl"))
    docket = Docket(namespace="repl")

    # Stub chat to return predictable JSON
    class DummyClient:
        def chat(self, messages, response_format=None):
            return (
                '{"assistant_message": "Hello!", '
                '"facts_to_save":[{"key":"foo","value":"bar"}], '
                '"tasks_to_add":[{"title":"do something","priority":"high"}]}'
            )

    monkeypatch.setattr(repl, "OpenAIClient", lambda: DummyClient())

    # Run REPL once
    sys.stdin = io.StringIO("hello\nquit\n")
    repl.main()

    # Capture printed output
    out = capsys.readouterr().out
    assert "Hello!" in out

    # Facts should have been saved
    facts_file = tmp_memory / "repl_facts.json"
    assert facts_file.exists()
    facts = facts_file.read_text()
    assert "foo" in facts

    # Task should be in docket
    tasks = docket.list_tasks()
    assert any(t["title"] == "do something" for t in tasks)


def test_scheduler_smoke(monkeypatch, tmp_memory):
    """Smoke test scheduler process_once with stubbed OpenAIClient."""
    scheduler = importlib.reload(importlib.import_module("executor.middleware.scheduler"))
    docket = Docket(namespace="repl")

    # Stub OpenAIClient to always return a dummy JSON
    class DummyClient:
        def chat(self, messages, response_format=None):
            return '{"assistant_message":"BG test","actions":[],"tasks_to_add":[]}'

    monkeypatch.setattr(scheduler, "OpenAIClient", lambda: DummyClient())

    # No tasks → should return idle or brainstormed
    res = scheduler.process_once()
    assert res in {"idle", "brainstormed", "worked"}

    # Add a TODO task and run again
    docket.add("dummy task", priority="normal")
    res = scheduler.process_once()
    assert res in {"worked", "idle", "brainstormed"}