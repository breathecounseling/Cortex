"""
Tests for error_handler.py
Validates error classification and repair loop integration.
"""

import pytest
import executor.utils.error_handler as error_handler

def test_classify_import_error():
    msg = "ModuleNotFoundError: No module named 'foo'"
    result = error_handler.classify_error(msg)
    assert result == "import_error"

def test_classify_syntax_error():
    msg = "SyntaxError: invalid syntax"
    result = error_handler.classify_error(msg)
    assert result == "syntax_error"

def test_classify_test_failure():
    msg = "AssertionError: expected 2, got 3"
    result = error_handler.classify_error(msg)
    assert result == "test_failure"

def test_classify_runtime_error():
    msg = "Traceback (most recent call last): RuntimeError: failure"
    result = error_handler.classify_error(msg)
    assert result == "runtime_error"

def test_classify_unknown():
    msg = "This is some random error"
    result = error_handler.classify_error(msg)
    assert result == "unknown"

def test_classify_import_error():
    try:
        raise ModuleNotFoundError("No module named 'foo'")
    except ModuleNotFoundError as e:
        result = error_handler.classify_error(e)
    assert result.name == "import_error"

def test_explain_error_import():
    err = {"message": "ModuleNotFoundError: No module named 'bar'"}
    explanation = error_handler.explain_error(err)
    assert "import_error" in explanation

def test_attempt_repair_runs(monkeypatch):
    """
    Monkeypatch self_repair to simulate a repair loop.
    Ensures attempt_repair respects retries.
    """
    calls = {"count": 0}

    def fake_attempt(error):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"status": "error"}  # first attempt fails
        return {"status": "ok"}  # second attempt succeeds

    monkeypatch.setattr(error_handler.self_repair, "attempt_self_repair", fake_attempt)

    err = {"message": "ModuleNotFoundError: No module named 'baz'"}
    result = error_handler.attempt_repair(err, retries=2)

    assert result["status"] == "ok"
    assert calls["count"] == 2
    assert "classification" in result["details"]
    assert result["details"]["classification"] == "import_error"
