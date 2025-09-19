"""
Extend Plugin
Allows Executor to modify or expand existing plugins with new features.
Runs pytest before auto-committing to dev branch.
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
            ["pytest", "-q", test_file],
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

def extend_plugin(plugin_name: str, new_feature: str, test_code: str = ""):
    """
    Ask GPT-5 to extend an existing plugin with a new feature.
    Runs pytest on existing or provided tests.
    Auto-commits to dev branch only if tests pass.
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
        code = f.read()

    prompt = f"""
A plugin named {safe_name} needs to be extended with this feature:
{new_feature}

Here is the current plugin code:
{code}

If tests are provided, ensure the code satisfies them:
{test_code}

Provide ONLY the full corrected plugin code for {safe_name}.
Do not remove existing working functions unless they must change.
    """

    response = openai_client.ask_executor(prompt)
    new_code = response.get("response_text", "")

    if not new_code.strip():
        return {
            "status": "error",
            "message": f"No new code generated for plugin '{safe_name}'. Rolled back."
        }

    # Write new code
    with open(main_file, "w", encoding="utf-8") as f:
        f.write(new_code)

    # --- Run pytest ---
    if os.path.exists(test_file):
        passed, output = run_pytest(test_file)
    else:
        passed, output = True, "No tests found, skipping pytest."

    if passed:
        success = git_commit_push(safe_name, branch="dev")
        return {
            "status": "ok",
            "message": f"Plugin '{safe_name}' extended with feature: {new_feature}",
            "test_output": output,
            "git_pushed": success
        }
    else:
        # Roll back if tests fail
        shutil.move(backup_path, main_file)
        return {
            "status": "error",
            "message": f"Extension failed tests for plugin '{safe_name}'. Rolled back.",
            "test_output": output
        }

if __name__ == "__main__":
    print(extend_plugin("calendar", "Add function to list upcoming events"))
