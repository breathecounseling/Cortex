"""
Builder Plugin with Autotester + Iterative Patcher + Git Integration + Heartbeats
"""

import os
import subprocess
from executor.utils.patcher_utils import iterative_patch
from executor.connectors import openai_client  # ✅ imported only here

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

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

    # --- Scaffold ---
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
        f.write(f'''from executor.plugins.{safe_name} import {safe_name}

def test_run():
    result = {safe_name}.run()
    assert result["status"] == "ok"
''')

    # --- Test + Patch Loop ---
    from executor.connectors import openai_client
    
    ...
    
    passed, output = iterative_patch(
        safe_name,
        main_file,
        test_file,
        openai_client.ask_executor,   # ✅ inject ask_executor
        max_retries=max_retries
    )

    )

    # --- Commit ---
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
    print(build_plugin("calendar_plugin", "Sync with Google Calendar"))
