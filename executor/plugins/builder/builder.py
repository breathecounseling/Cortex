"""
Plugin Builder with Iterative Patcher + Git Integration + Verbose Errors
"""

import os
import subprocess
import shutil
import traceback
from executor.utils.patcher_utils import iterative_patch
from executor.connectors import openai_client  # ✅ imported only here

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

def git_commit_push(plugin_name: str, branch: str = "dev"):
    """Commit and push changes to a safe branch."""
    try:
        subprocess.run(["git", "checkout", "-B", branch], check=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Add/patch plugin {plugin_name}"],
            check=True
        )
        subprocess.run(["git", "push", "origin", branch], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[GIT ERROR] {e}")
        return False

def build_plugin(plugin_name: str, purpose: str, test_code: str = "", max_retries: int = 3):
    safe_name = plugin_name.lower().replace(" ", "_")
    plugin_dir = os.path.join(PLUGIN_BASE, safe_name)
    main_file = os.path.join(plugin_dir, f"{safe_name}.py")
    test_file = os.path.join(plugin_dir, f"test_{safe_name}.py")

    os.makedirs(plugin_dir, exist_ok=True)

    # Backup if plugin already exists
    if os.path.exists(main_file):
        shutil.copy(main_file, main_file + ".bak")

    # Ask GPT-5 to generate plugin
    prompt = f"""
Create a new plugin named {safe_name} for this purpose:
{purpose}

It should live at executor/plugins/{safe_name}/{safe_name}.py

Also create a test file at executor/plugins/{safe_name}/test_{safe_name}.py that validates core functionality.

Important: Plugins must be importable as:
from executor.plugins.{safe_name} import {safe_name}

Return ONLY the full plugin code for {safe_name}.py.
    """

    try:
        response = openai_client.ask_executor(prompt)
        new_code = response.get("response_text", "")
    except Exception as e:
        tb = traceback.format_exc()
        return {"status": "error", "message": f"ask_executor failed: {e}", "traceback": tb}

    if not new_code.strip():
        return {
            "status": "error",
            "message": "No new code generated. Model may not have understood the request.",
            "debug": response
        }

    try:
        with open(main_file, "w", encoding="utf-8") as f:
            f.write(new_code)
    except Exception as e:
        return {"status": "error", "message": f"Failed to write plugin file: {e}"}

    # Write test file if test_code provided
    if test_code.strip():
        try:
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(test_code)
        except Exception as e:
            return {"status": "error", "message": f"Failed to write test file: {e}"}

    # --- Test + Patch Loop ---
    try:
        passed, output = iterative_patch(
            safe_name,
            main_file,
            test_file,
            openai_client.ask_executor,   # ✅ inject ask_executor
            max_retries=max_retries
        )
    except Exception as e:
        tb = traceback.format_exc()
        return {"status": "error", "message": f"iterative_patch crashed: {e}", "traceback": tb}

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
            "message": f"Build failed after {max_retries} retries. Rolled back.",
            "test_output": output,
            "last_code": new_code[:500]
        }

if __name__ == "__main__":
    print(build_plugin("demo_plugin", "Return {'hello': 'world'}"))
