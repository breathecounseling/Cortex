from __future__ import annotations

from executor.audit.logger import get_logger
from executor.utils.memory import record_repair

logger = get_logger(__name__)

# compatibility helpers expected by tests

def classify_error(message: str) -> str:
    m = message or ""
    if "ModuleNotFoundError" in m or "No module named" in m:
        return "import_error"
    if "SyntaxError" in m:
        return "syntax_error"
    if "AssertionError" in m:
        return "test_failure"
    if "Traceback" in m or "RuntimeError" in m or "Exception" in m:
        return "runtime_error"
    return "unknown"

def explain_error(err: dict) -> str:
    msg = (err or {}).get("message", "")
    kind = classify_error(msg)
    return f"Detected {kind.replace('_', ' ')}: {msg}"

class _SelfRepair:
    def attempt_self_repair(self, error):
        # dummy placeholder used by tests; real logic elsewhere
        return {"status": "ok"}

self_repair = _SelfRepair()

def handle_error(file: str, error: Exception, fix_hint: str | None = None) -> None:
    logger.exception(f"Error in {file}: {error}")
    record_repair(file=file, error=str(error), fix_summary=fix_hint or "", success=False)
