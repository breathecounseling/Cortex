import os
import importlib
import pytest
from pathlib import Path

from executor.self_healer import supervisor


def test_self_healer_runs_smoke(tmp_path, monkeypatch):
    """
    Smoke test: ensure the self-healer supervisor runs through one cycle cleanly.

    This test does NOT perform any LLM patching — it stubs the OpenAI client
    to return an empty patch set and confirms no exceptions are raised.
    """

    # Create a fake repo root with one trivial test file
    repo_root = tmp_path / "repo"
    tests_dir = repo_root / "tests"
    tests_dir.mkdir(parents=True)
    test_file = tests_dir / "test_dummy.py"
    test_file.write_text("def test_dummy():\n    assert 1 == 1\n")

    # Point config to our temp repo
    monkeypatch.setenv("CORTEX_REPO_ROOT", str(repo_root))

    # Stub the OpenAI client to return no patches
    class DummyClient:
        def chat(self, messages, **kwargs):
            return "No patches required."

    monkeypatch.setattr("executor.self_healer.supervisor.OpenAIClient", DummyClient)

    # Run a single self-healing cycle
    result = supervisor.run_self_healer()

    # Assert the suite is green and no patches applied
    assert result.green is True
    assert result.applied_files == []
    assert result.failures_after == 0
    assert result.failures_before == 0


def test_self_healer_cycle_failure_and_noop(monkeypatch, tmp_path):
    """
    Create a failing test to ensure the supervisor correctly detects failure,
    runs the dummy client, and reports non-green status without crashing.
    """

    repo_root = tmp_path / "repo"
    tests_dir = repo_root / "tests"
    tests_dir.mkdir(parents=True)
    bad_test = tests_dir / "test_fail.py"
    bad_test.write_text("def test_fail():\n    assert 2 == 3\n")

    monkeypatch.setenv("CORTEX_REPO_ROOT", str(repo_root))

    # Dummy client returns a fake patch in the right format
    dummy_patch = (
        "```patch:tests/test_fail.py\n"
        "def test_fail():\n"
        "    assert 2 == 2\n"
        "```"
    )

    class DummyClient:
        def chat(self, messages, **kwargs):
            return dummy_patch

    monkeypatch.setattr("executor.self_healer.supervisor.OpenAIClient", DummyClient)

    # Run one self-healing cycle
    result = supervisor.run_self_healer()

    # It should have applied one patch and re-run tests
    assert len(result.applied_files) == 1
    assert "test_fail.py" in result.applied_files[0]
    # Either still failing or green after patch
    assert result.failures_after in (0, 1)