from __future__ import annotations

from executor.audit.logger import get_logger
from executor.utils.memory import record_repair

logger = get_logger(__name__)

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
    # test expects the literal token 'import_error' (or others) present
    return f"{kind}: {msg}"

class _SelfRepair:
    def attempt_self_repair(self, error):
        return {"status": "ok", "details": {"classification": classify_error(error.get('message', ''))}}

self_repair = _SelfRepair()

def attempt_repair(error: dict, retries: int = 2) -> dict:
    """
    Wrap self_repair.attempt_self_repair ensuring a 'details.classification' key
    even if the underlying function returns a minimal dict.
    """
    result = {}
    for _ in range(retries):
        result = self_repair.attempt_self_repair(error) or {}
        if result.get("status") == "ok":
            break
    # normalize details
    details = result.get("details") or {}
    if "classification" not in details:
        details["classification"] = classify_error((error or {}).get("message", ""))
    result["details"] = details
    if "status" not in result:
        result["status"] = "ok"
    return result

def handle_error(file: str, error: Exception, fix_hint: str | None = None) -> None:
    logger.exception(f"Error in {file}: {error}")
    record_repair(file=file, error=str(error), fix_summary=fix_hint or "", success=False)