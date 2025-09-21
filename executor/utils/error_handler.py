# executor/plugins/error_handler.py
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

def classify_error(err: Exception) -> Classification:
    if isinstance(err, ExecutorError):
        if err.kind == "empty_model_output":
            return Classification(
                name="empty_model_output",
                details=err.details,
                repair_proposal=(
                    "Use response_format=json_object, enforce a JSON contract with 'files', "
                    "and retry with 'Respond ONLY with JSON' guard."
                ),
            )
        if err.kind == "malformed_response":
            return Classification(
                name="malformed_response",
                details=err.details,
                repair_proposal=(
                    "Parse fenced ```json blocks; fall back to first balanced { ... }. "
                    "If schema missing 'files', request regeneration with explicit keys."
                ),
            )
        if err.kind == "plugin_not_found":
            return Classification(
                name="plugin_not_found",
                details=err.details,
                repair_proposal=(
                    "Resolve plugin via a canonical resolver that accepts names, dirs, or file paths. "
                    "List known plugins if ambiguity persists."
                ),
            )
        if err.kind == "tests_failed":
            report = err.details.get("report", "")
            # 👇 New branch: detect import errors in pytest logs
            if "ModuleNotFoundError: No module named 'executor'" in report:
                return Classification(
                    name="import_error",
                    details=err.details,
                    repair_proposal=(
                        "Tests cannot import the 'executor' package. "
                        "Fix by setting PYTHONPATH in patcher_utils.run_tests or "
                        "inserting sys.path in test files. "
                        "Recommend updating patcher_utils to inject PYTHONPATH automatically."
                    ),
                )
            return Classification(
                name="tests_failed",
                details=err.details,
                repair_proposal=(
                    "Provide the failing traceback back to the model and request a minimal fix patch. "
                    "Re-run focused tests; if still failing, isolate by file and bisect."
                ),
            )
    # default/fallback
    return Classification(
        name=type(err).__name__,
        details={},
        repair_proposal="Surface full stack to user; collect context for targeted repair.",
    )
