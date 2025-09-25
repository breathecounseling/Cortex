from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Classification:
    name: str
    details: Dict[str, Any]
    repair_proposal: str


class ExecutorError(Exception):
    def __init__(self, kind: str, details: Dict[str, Any] | None = None):
        super().__init__(kind)
        self.kind = kind
        self.details = details or {}


def classify_error(err) -> Classification | str:
    """
    Classify an error. Can accept either an Exception instance or a string traceback.
    Returns either a Classification (for Exceptions) or a simple string label (for str inputs).
    """
    # Case 1: raw string tracebacks (used in tests)
    if isinstance(err, str):
        low = err.lower()
        if "modulenotfounderror" in low:
            return "import_error"
        if "syntaxerror" in low:
            return "syntax_error"
        if "assertionerror" in low:
            return "test_failure"
        if "runtimeerror" in low:
            return "runtime_error"
        return "unknown"

    # Case 2: ExecutorError (structured errors from our system)
    if isinstance(err, ExecutorError):
        if err.kind == "plugin_not_found":
            return Classification(
                name="plugin_not_found",
                details=err.details,
                repair_proposal="Check plugin name/path; resolve with plugin_resolver.",
            )
        if err.kind == "tests_failed":
            return Classification(
                name="tests_failed",
                details=err.details,
                repair_proposal="Review traceback; isolate file; request minimal fix patch.",
            )
        if err.kind == "empty_model_output":
            return Classification(
                name="empty_model_output",
                details=err.details,
                repair_proposal="Ensure JSON schema enforced; retry with guardrails.",
            )
        if err.kind == "malformed_response":
            return Classification(
                name="malformed_response",
                details=err.details,
                repair_proposal="Parse fenced ```json; retry with explicit schema.",
            )

    # Case 3: generic Python exceptions
    if isinstance(err, ModuleNotFoundError):
        return Classification(
            name="import_error",
            details={"msg": str(err)},
            repair_proposal="Install missing module or fix PYTHONPATH.",
        )
    if isinstance(err, SyntaxError):
        return Classification(
            name="syntax_error",
            details={"msg": str(err)},
            repair_proposal="Fix Python syntax.",
        )
    if isinstance(err, AssertionError):
        return Classification(
            name="test_failure",
            details={"msg": str(err)},
            repair_proposal="Adjust tests or fix implementation to satisfy assertions.",
        )
    if isinstance(err, RuntimeError):
        return Classification(
            name="runtime_error",
            details={"msg": str(err)},
            repair_proposal="Handle runtime error appropriately.",
        )

    # Fallback
    return Classification(
        name=type(err).__name__,
        details={},
        repair_proposal="Surface full stack to user; collect context for targeted repair.",
    )


def explain_error(err: Dict[str, Any]) -> str:
    """Provide a human-readable explanation of an error dict with 'message'."""
    msg = err.get("message", "")
    classification = classify_error(msg)
    return f"Error classified as {classification}: {msg}"


def attempt_repair(err: Dict[str, Any], retries: int = 2) -> Dict[str, Any]:
    """
    Attempt a self-repair loop.
    Uses self_repair.attempt_self_repair if available.
    """
    from executor.utils import self_repair

    classification = classify_error(err.get("message", ""))
    last_result = None
    for _ in range(retries):
        last_result = self_repair.attempt_self_repair(err)
        if last_result.get("status") == "ok":
            break

    return {
        "status": last_result.get("status", "error"),
        "details": {"classification": classification, "last_result": last_result},
    }
