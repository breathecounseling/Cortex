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
        return result.returncode == 0
    except Exception as e:
        print("[Healer] Pytest error:", e)
        return False

def verify_all() -> bool:
    start = time.time()
    ok = syntax_check() and import_check() and test_check()
    print(f"[Healer] Verification complete in {round(time.time()-start,2)}s -> {'PASS' if ok else 'FAIL'}")
    return ok

if __name__ == "__main__":
    sys.exit(0 if verify_all() else 1)