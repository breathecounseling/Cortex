import os
import json
import tempfile
import shutil
import pytest

import executor.plugins.conversation_manager.conversation_manager as cm


@pytest.fixture(autouse=True)
def temp_memory(monkeypatch, tmp_path):
    """
    Redirect .executor/memory to a temp dir for isolation in tests.
    """
    memdir = tmp_path / ".executor" / "memory"
    memdir.mkdir(parents=True)
    monkeypatch.setattr(cm, "_MEM_DIR", str(memdir))
    yield


def test_handle_repl_turn_formats_system_message():
    hist = [
        {"role": "user", "content": "Remember: my favorite color is green."},
        {"role": "assistant", "content": "Got it—I’ll remember that."},
    ]
    turn = cm.handle_repl_turn("What is my favorite color?", history=hist, session="test", limit=10)
    messages = turn["messages"]

    # Should include history + new turn
    assert len(messages) == 3
    assert messages[-1]["role"] == "user"
    assert "favorite color" in messages[-1]["content"]


def test_fact_extraction_color_and_food(tmp_path):
    # Fresh session
    session = "facts_test"

    # Give input with favorite color
    cm.handle_repl_turn("My favorite color is blue.", session=session)
    facts = cm.load_facts(session)
    assert facts.get("favorite_color") == "blue"

    # Give input with favorite food
    cm.handle_repl_turn("My favorite food is pizza.", session=session)
    facts = cm.load_facts(session)
    assert facts.get("favorite_food") == "pizza"


def test_limit_history(tmp_path):
    session = "limit_test"
    hist = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    turn = cm.handle_repl_turn("latest msg", history=hist, session=session, limit=5)
    messages = turn["messages"]

    # Only the last 5 from history + 1 new
    assert len(messages) == 6
    assert messages[-1]["content"] == "latest msg"
