"""
Extend Plugin with Iterative Patcher + Git Integration + Heartbeats
"""

import os
import subprocess
import shutil
from executor.utils.patcher_utils import iterative_patch

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

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

def extend_plugin(plugin_name: str, new_feature: str, test_code: str = "", max_retries: int = 3):
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

    # Ask GPT-5 to extend
    from executor.connectors import openai_client
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
    """
    response = openai_client.ask_executor(prompt)
    new_code = response.get("response_text", "")

    if not new_code.strip():
        return {"status": "error", "message": "No new code generated, rolled back."}

    with open(main_file, "w", encoding="utf-8") as f:
        f.write(new_code)

    # --- Test + Patch Loop ---
    passed, output = iterative_patch(safe_name, main_file, test_file, max_retries=max_retries)

    if passed:
        success = git_commit_push(safe_name, branch="dev")
        return {
            "status": "ok",
            "message": f"Plugin '{safe_name}' extended and passed tests.",
            "test_output": output,
            "git_pushed": success
        }
    else:
        return {
            "status": "error",
            "message": f"Extension failed after {max_retries} retries. Rolled back.",
            "test_output": output
        }

if __name__ == "__main__":
    print(extend_plugin("calendar_plugin", "Add function to list upcoming events"))
