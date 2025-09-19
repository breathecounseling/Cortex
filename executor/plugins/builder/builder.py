"""
Builder Plugin with Autotester + Patcher + Git Integration
"""

import os
import subprocess
import json
import shutil
from executor.connectors import openai_client  # to call GPT-5 for patching

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

def run_pytest(test_file: str):
    """Run pytest on a single file, return (passed, output)."""
    try:
        result = subprocess.run(
            ["pytest", "-q", test_file],
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stdout + "\n" + e.stderr

def request_patch(plugin_name: str, code: str, test_code: str, error_log: str):
    """Ask GPT-5 (Responses API) to patch code based on failing tests."""
    prompt = f"""
You are an AI code patcher. A plugin named {plugin_name} failed its tests.
Here is the full plugin code:
{code}

Here is the test code:
{test_code}

Here is the pytest error log:
{error_log}

Provide ONLY the corrected full plugin code for {plugin_name}. 
Do not remove working functions or unrelated logic.
    """
    response = openai_client.ask_executor(prompt)
    return response.get("response_text", "")

def apply_patch(file_path: str, new_code: str):
    """Backup old file and write new code safely."""
    backup_path = file_path + ".bak"
    shutil.copy(file_path, backup_path)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_code)
    return backup_path

def git_commit_push(plugin_name: str, branch: str = "dev"):
    """Commit and push changes to a safe branch."""
    try:
        subprocess.run(["git", "checkout", "-B", branch], check=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"Add/patch plugin {plugin_name}"], check=True)
        subprocess.run(["git", "push", "origin", branch], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def build_plugin(plugin_name: str, purpose: str, max_retries: int = 3):
    safe_name = plugin_name.lower().replace(" ", "_")
    plugin_dir = os.path.join(PLUGIN_BASE, safe_name)

    if os.path.exists(plugin_dir):
        return {"status": "error", "message": f"Plugin '{safe_name}' already exists."}

    # --- Step 1: Scaffold ---
    os.makedirs(plugin_dir, exist_ok=True)
    with open(os.path.join(plugin_dir, "__init__.py"), "w") as f:
        f.write(f'""" {safe_name} plugin """\n')

    main_file = os.path.join(plugin_dir, f"{safe_name}.py")
    test_file = os.path.join(plugin_dir, f"test_{safe_name}.py")

    with open(main_file, "w") as f:
        f.write(f'''"""
Plugin: {safe_name}
Purpose: {purpose}
"""

def run():
    print("[{safe_name}] Running placeholder task.")
    return {{"status": "ok", "plugin": "{safe_name}", "purpose": "{purpose}"}}
''')

    with open(test_file, "w") as f:
        f.write(f'''import {safe_name}

def test_run():
    result = {safe_name}.run()
    assert result["status"] == "ok"
''')

    # --- Step 2: Test ---
    passed, output = run_pytest(test_file)
    retries = 0

    while not passed and retries < max_retries:
        retries += 1
        with open(main_file, "r", encoding="utf-8") as f: code = f.read()
        with open(test_file, "r", encoding="utf-8") as f: test_code = f.read()
        patched_code = request_patch(safe_name, code, test_code, output)

        if patched_code.strip():
            backup = apply_patch(main_file, patched_code)
            passed, output = run_pytest(test_file)
            if not passed:  # rollback if patch failed
                shutil.move(backup, main_file)
        else:
            break

    # --- Step 3: Git Commit ---
    if passed:
        success = git_commit_push(safe_name, branch="dev")
        return {
            "status": "ok",
            "message": f"Plugin '{safe_name}' created and passed tests.",
            "test_output": output,
            "git_pushed": success
        }
    else:
        return {
            "status": "error",
            "message": f"Plugin '{safe_name}' failed after {max_retries} retries.",
            "test_output": output
        }

if __name__ == "__main__":
    print(build_plugin("calendar", "Sync with Google Calendar"))
