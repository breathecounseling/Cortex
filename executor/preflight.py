"""
Preflight verification for Cortex
---------------------------------
Purpose:
    - Run syntax and import checks before starting Uvicorn.
    - Prevent startup loops when a commit contains invalid Python.

Exit codes:
    0 : All checks passed
    1 : Syntax error detected
    2 : Import failure
    3 : Unexpected runtime exception
"""

from __future__ import annotations
import sys, compileall, importlib, traceback, time

def syntax_check() -> bool:
    print("[Preflight] Running syntax check...")
    ok = compileall.compile_dir("executor", quiet=1)
    if not ok:
        print("[Preflight] Syntax errors found.")
    return ok

def import_check() -> bool:
    print("[Preflight] Verifying core imports...")
    try:
        importlib.import_module("executor.api.main")
        importlib.import_module("executor.core.router")
        print("[Preflight] Import check passed.")
        return True
    except Exception:
        print("[Preflight] Import check failed:")
        traceback.print_exc()
        return False

def main() -> None:
    start = time.time()
    try:
        if not syntax_check():
            sys.exit(1)
        if not import_check():
            sys.exit(2)
        elapsed = round(time.time() - start, 2)
        print(f"[Preflight] All checks passed in {elapsed}s.")
        sys.exit(0)
    except Exception:
        print("[Preflight] Unexpected exception:")
        traceback.print_exc()
        sys.exit(3)

if __name__ == "__main__":
    main()