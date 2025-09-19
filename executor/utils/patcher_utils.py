"""
Patcher Utilities with Diff Mode + Partial Fixes + Heartbeats
"""

import subprocess
import shutil
import os


def run_pytest(test_file: str):
    """Run pytest on a single file, return (passed, output, fail_count)."""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q", test_file],
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout, 0
    except subprocess.CalledProcessError as e:
        # Count how many tests failed
        fails = e.stdout.count("FAILED") + e.stdout.count("ERROR")
        return False, e.stdout + "\n" + e.stderr, fails


def request_patch(plugin_name: str, code: str, test_code: str, error_log: str, ask_executor, last_patch: str = ""):
    """Ask GPT-5 for an improved version of the plugin code using the provided ask_executor."""
    prompt = f"""
You are an AI code patcher. A plugin named {plugin_name} failed its tests.

Important repo rules:
- Plugins live in executor/plugins/<plugin_name>/
- Tests must import them using: from executor.plugins.<plugin_name> import <plugin_name>

Here is the current plugin code:
{code}

Here are the tests:
{test_code}

Here is the pytest error log:
{error_log}

If a previous patch was attempted, here it is:
{last_patch}

Fix ONLY what is necessary to make the tests pass.
Do not remove working functions or unrelated logic.
Return the FULL corrected plugin code (not a diff).
    """
    response = ask_executor(prompt)
    return response.get("response_text", "")


def iterative_patch(plugin_name, main_file, test_file, ask_executor, max_retries=3):
    """Iteratively patch plugin until tests pass or retries exhausted."""
    backup_path = main_file + ".bak"
    shutil.copy(main_file, backup_path)

    with open(main_file, "r", encoding="utf-8") as f:
        code = f.read()
    test_code = ""
    if os.path.exists(test_file):
        with open(test_file, "r", encoding="utf-8") as f:
            test_code = f.read()

    last_patch = ""
    last_fail_count = float("inf")

    passed, output, fails = run_pytest(test_file) if os.path.exists(test_file) else (True, "No tests", 0)

    retries = 0
    while not passed and retries < max_retries:
        retries += 1
        print(f"[Heartbeat] Retry {retries}/{max_retries} for {plugin_name}, {fails} failures remain.")

        patched_code = request_patch(plugin_name, code, test_code, output, ask_executor, last_patch)
        if not patched_code.strip():
            print("[Heartbeat] No patch returned — stopping.")
            break

        # Save this patch for context
        last_patch = patched_code

        # Write new code
        with open(main_file, "w", encoding="utf-8") as f:
            f.write(patched_code)

        passed, output, new_fails = run_pytest(test_file)

        if new_fails > fails:
            print(f"[Heartbeat] Patch made it worse ({new_fails}>{fails}). Rolling back this attempt.")
            shutil.copy(backup_path, main_file)
        else:
            fails = new_fails
            with open(main_file, "r", encoding="utf-8") as f:
                code = f.read()

    if passed:
        print(f"[Heartbeat] Plugin {plugin_name} fixed and tests passed.")
        return True, output
    else:
        print(f"[Heartbeat] Failed after {max_retries} retries. Restoring backup.")
        shutil.move(backup_path, main_file)
        return False, output
