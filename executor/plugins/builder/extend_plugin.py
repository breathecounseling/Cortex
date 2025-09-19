"""
Extend Plugin with Autotester + Patcher + Git Integration + Heartbeats
"""

import os
import shutil
import subprocess
from executor.connectors import openai_client

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

def run_pytest(test_file: str):
    """Run pytest on a single file, return (passed, output)."""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q", test_file],
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stdout + "\n" + e.stderr

def git_commit_push(plugin_name: str, branch: str = "dev"):
    """Commit and push changes to a safe branch."""
    try:
        subprocess.run(["git", "checkout", "-B", branch], check=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Extend plugin {plugin_name} with new feature"],
            check=True
        )
        subprocess.run(["git", "push", "origin", branch], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def request_patch(plugin_name: str, code: str, test_code: str, error_log: str):
    """Ask GPT-5 to patch code based on failing tests."""
    prompt = f"""
You are an AI code patcher. A plugin named {plugin_name} was extended but failed its tests.

Important: Plugins live in executor/plugins/<plugin_name>/ 
and tests must import them using:
from executor.plugins.<plugin_name> import <plugin_name>

Here is the full plugin code:
{code}

Here is the test code:
{test_code}

Here is the pytest error log:
{error_log}

Fix ONLY what is necessary to make the tests pass.
Do not remove working functions or unrelated logic.
Return the FULL corrected plugin code.
    """
    response = openai_client.ask_executor(prompt)
    return response.get("response_text", "")

def extend_plugin(plugin_name: str, new_feature: str, test_code: str = "", max_retries: int = 3):
    """
    Ask GPT-5 to extend an existing plugin with a new feature.
    Run pytest and patch automatically until tests pass or retries exhausted.
    """
    safe_name = plugin_name.lower().replace(" ", "_")
    plugin_dir = os.path.join(PLUGIN_BASE, safe_name)
    main_file = os.path.join(plugin_dir, f"{safe_name}.py")
    test_file = os.path.join(plugin_dir, f"test_{safe_name}.py")

    if not os.path.exists(main_file):
        return {"status": "error", "message": f"Plugin '{safe_name}' does not exist."}

    # Backup before editing
    backup_path = main_file + ".bak"
    shutil.copy(main_file, backup_path)

    with open(main_file, "r", encoding="utf-8") as f:
        old_code = f.read()

    prompt = f"""
Extend the plugin named {safe_name} with this feature:
{new_feature}

Here is the current plugin code:
{old_code}

If tests are provided, ensure the code satisfies them:
{test_code}

Important: Plugins live in executor/plugins/<plugin_name>/ 
and tests must import them using:
from executor.plugins.<plugin_name> import <plugin_name>

Return ONLY the full corrected plugin code.
Do not remove existing working functions unless necessary.
    """

    response = openai_client.ask_executor(prompt)
    new_code = response.get("response_text", "")

    if not new_code.strip():
        print(f"[Heartbeat] No new code generated for plugin '{safe_name}'. Rolled back.")
        return {"status": "error", "message": "No new code generated, rolled back."}

    # Write new code
    with open(main_file, "w", encoding="utf-8") as f:
        f.write(new_code)

    # --- Run pytest + patch loop ---
    retries = 0
    passed, output = run_pytest(test_file) if os.path.exists(test_file) else (True, "No tests found, skipping pytest.")

    while not passed and retries < max_retries:
        retries += 1
        print(f"[Heartbeat] Retry {retries}/{max_retries} for plugin '{safe_name}'... still running.")

        with open(main_file, "r", encoding="utf-8") as f:
            code = f.read()
        test_code_content = ""
        if os.path.exists(test_file):
            with open(test_file, "r", encoding="utf-8") as f:
                test_code_content = f.read()

        patched_code = request_patch(safe_name, code, test_code_content, output)

        if patched_code.strip():
            with open(main_file, "w", encoding="utf-8") as f:
                f.write(patched_code)
            passed, output = run_pytest(test_file)
            if not passed:
                print(f"[Heartbeat] Patch attempt {retries} failed — retrying.")
        else:
            print(f"[Heartbeat] GPT-5 returned no patch on attempt {retries}. Stopping.")
            break

    if passed:
        success = git_commit_push(safe_name, branch="dev")
        print(f"[Heartbeat] Plugin '{safe_name}' extended successfully and pushed to dev.")
        return {
            "status": "ok",
            "message": f"Plugin '{safe_name}' extended and passed tests.",
            "test_output": output,
            "git_pushed": success
        }
    else:
        shutil.move(backup_path, main_file)
        print(f"[Heartbeat] Extension failed after {max_retries} retries. Rolled back.")
        return {
            "status": "error",
            "message": f"Extension failed after {max_retries} retries. Rolled back.",
            "test_output": output
        }

if __name__ == "__main__":
    print(extend_plugin("calendar_plugin", "Add function to list upcoming events"))
