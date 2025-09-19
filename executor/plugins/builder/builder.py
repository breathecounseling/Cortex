import os
import subprocess

PLUGIN_BASE = os.path.join(os.path.dirname(__file__), "..")

def build_plugin(plugin_name: str, purpose: str):
    safe_name = plugin_name.lower().replace(" ", "_")
    plugin_dir = os.path.join(PLUGIN_BASE, safe_name)

    if os.path.exists(plugin_dir):
        return {"status": "error", "message": f"Plugin '{safe_name}' already exists."}

    # Create directory + files
    os.makedirs(plugin_dir, exist_ok=True)
    with open(os.path.join(plugin_dir, "__init__.py"), "w") as f:
        f.write(f'""" {safe_name} plugin """\n')

    main_file = os.path.join(plugin_dir, f"{safe_name}.py")
    with open(main_file, "w") as f:
        f.write(f'''"""
Plugin: {safe_name}
Purpose: {purpose}
"""

def run():
    print("[{safe_name}] Running placeholder task.")
    return {{"status": "ok", "plugin": "{safe_name}", "purpose": "{purpose}"}}
''')

    test_file = os.path.join(plugin_dir, f"test_{safe_name}.py")
    with open(test_file, "w") as f:
        f.write(f'''import {safe_name}

def test_run():
    result = {safe_name}.run()
    assert result["status"] == "ok"
''')

    # ✅ Run pytest on the new plugin
    try:
        result = subprocess.run(
            ["pytest", "-q", test_file],
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "status": "ok",
            "message": f"Plugin '{safe_name}' created and passed tests.",
            "path": plugin_dir,
            "test_output": result.stdout
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Plugin '{safe_name}' created but tests failed.",
            "path": plugin_dir,
            "test_output": e.stdout + e.stderr
        }
