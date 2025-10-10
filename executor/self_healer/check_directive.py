"""
check_directive.py
------------------
Runs the repository validation steps defined in GPT_PATCHING_DIRECTIVE.md.

Exit codes:
    0 : all checks passed
    1 : syntax or import failure
    2 : pytest failure
"""

from __future__ import annotations
import subprocess, sys, compileall, importlib, traceback, time

def syntax_check() -> bool:
    print("[Healer] Syntax check...")
    ok = compileall.compile_dir("executor", quiet=1)
    if not ok:
        print("[Healer] Syntax errors detected.")
    return ok

def import_check() -> bool:
    print("[Healer] Import check...")
    try:
        importlib.import_module("executor.api.main")
        importlib.import_module("executor.core.router")
        print("[Healer] Import check passed.")
        return True
    except Exception:
        traceback.print_exc()
        return False

def test_check() -> bool:
    print("[Healer] Running pytest...")
    try:
        result = subprocess.run(["pytest", "-q"], capture_output=True, text=True, timeout=300)
        print(result.stdout)
        if result.returncode == 0:
            print("[Healer] All tests passed.")
            return True
        print("[Healer] Test failures detected.")
        return False
    except Exception as e:
        print("[Healer] Pytest error:", e)
        return False

def verify_all() -> bool:
    start = time.time()
    ok = syntax_check() and import_check() and test_check()
    dur = round(time.time() - start, 2)
    print(f"[Healer] Verification complete in {dur}s -> {'PASS' if ok else 'FAIL'}")
    return ok

if __name__ == "__main__":
    if verify_all():
        sys.exit(0)
    else:
        sys.exit(1)