# executor/tests/test_repl_docket.py
import os
import json
import tempfile
import shutil
import builtins
import io
import sys
import pytest

from executor.utils.docket import Docket

# We’ll import repl after patching _MEM_DIR to a tmp dir
import importlib

@pytest.fixture
def tmp_memory(monkeypatch, tmp_path):
    memdir = tmp_path / ".executor" / "memory"
    memdir.mkdir(parents=True)
    monkeypatch.setattr("executor.connectors.repl._MEM_DIR", str(memdir))
    monkeypatch.setattr("executor.utils.docket.os.path.join", os.path.join)  # ensure normal join
    monkeypatch.chdir(tmp_path)
    return memdir


def test_approve_reject_flow(tmp_memory, monkeypatch, capsys):
    # reload repl to use patched memory dir
    repl = importlib.reload(importlib.import_module("executor.connectors.repl"))

    docket = Docket(namespace="repl")

    # Add an idea task manually
    tid = docket.add("[idea] Test new feature", priority="normal")
    tasks = docket.list_tasks()
    assert tasks[0]["title"].startswith("[idea]")

    # Simulate approve command
    user_text = f"approve {tid}"
    sys.stdin = io.StringIO(user_text + "\nquit\n")
    repl.main()

    tasks = Docket(namespace="repl").list_tasks()
    assert tasks[0]["status"] == "todo"
    assert not tasks[0]["title"].startswith("[idea]")

    # Add another idea task
    tid2 = docket.add("[idea] Another idea", priority="normal")
    # Simulate reject command
    user_text = f"reject {tid2}"
    sys.stdin = io.StringIO(user_text + "\nquit\n")
    repl.main()

    tasks = Docket(namespace="repl").list_tasks()
    # task list should not contain tid2 anymore
    ids = [t["id"] for t in tasks]
    assert tid2 not in ids