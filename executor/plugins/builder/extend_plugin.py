"""
Extend Plugin
Allows Executor to modify or expand existing plugins with new features.
"""

import os
import shutil
from executor.connectors import openai_client

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

def extend_plugin(plugin_name: str, new_feature: str, test_code: str = ""):
    """
    Ask GPT-5 to extend an existing plugin with a new feature.
    Optionally include new tests.
    """
    safe_name = plugin_name.lower().replace(" ", "_")
    plugin_dir = os.path.join(PLUGIN_BASE, safe_name)
    main_file = os.path.join(plugin_dir, f"{safe_name}.py")

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

    if new_code.strip():
        with open(main_file, "w", encoding="utf-8") as f:
            f.write(new_code)
        return {
            "status": "ok",
            "message": f"Plugin '{safe_name}' extended with feature: {new_feature}",
            "file": main_file
        }
    else:
        # Restore if nothing returned
        shutil.move(backup_path, main_file)
        return {
            "status": "error",
            "message": f"Failed to extend plugin '{safe_name}'. Rolled back."
        }

if __name__ == "__main__":
    print(extend_plugin("calendar", "Add function to list upcoming events"))
