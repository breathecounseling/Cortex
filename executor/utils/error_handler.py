"""
Error Handler and Self-Repair Loop for Cortex Executor
- Classifies errors
- Suggests repair actions
- Calls patcher to attempt fixes
"""

import os
import re
import traceback
from pathlib import Path
from executor.utils import self_repair

def classify_error(message: str) -> str:
    """Categorize error messages into known types."""
    if not message:
        return "unknown"

    msg = message.lower()
    if "no module named" in msg or "importerror" in msg or "modulenotfound" in msg:
        return "import_error"
    if "syntaxerror" in msg:
        return "syntax_error"
    if "failed" in msg or "assert" in msg:
        return "test_failure"
    if "traceback" in msg or "runtimeerror" in msg:
        return "runtime_error"
    return "unknown"

def attempt_repair(error: dict, retries: int = 2) -> dict:
    """
    Attempt targeted repair based on error classification.
    Retries up to `retries` times.
    """
    msg = error.get("message", "")
    classification = classify_error(msg)
    details = {"classification": classification, "attempts": []}

    for i in range(retries):
        print(f"[ERROR HANDLER] Attempt {i+1}/{retries} for {classification}...")
        repair = self_repair.attempt_self_repair(error)
        details["attempts"].append(repair)
        if repair.get("status") == "ok":
            return {"status": "ok", "message": "Repair succeeded", "details": details}

    return {"status": "error", "message": "All repair attempts failed", "details": details}

def explain_error(error: dict) -> str:
    """Generate a human-readable explanation of the error and classification."""
    classification = classify_error(error.get("message", ""))
    return f"Error classified as: {classification}\nDetails: {error.get('message')}"
