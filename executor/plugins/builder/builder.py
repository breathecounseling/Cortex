# executor/plugins/builder/builder.py
from __future__ import annotations
import os
import json

def main(plugin_name: str, description: str = "") -> None:
    """
    Scaffold a new plugin under executor/plugins/<plugin_name>/ with:
      - __init__.py
      - <plugin_name>.py (stub)
      - test_<plugin_name>.py (stub test)
      - plugin.json (manifest with description + capabilities)
    """
    base = os.path.join("executor", "plugins", plugin_name)
    os.makedirs(base, exist_ok=True)

    # __init__.py
    init_file = os.path.join(base, "__init__.py")
    if not os.path.exists(init_file):
        open(init_file, "w").close()

    # main plugin file
    plugin_file = os.path.join(base, f"{plugin_name}.py")
    if not os.path.exists(plugin_file):
        with open(plugin_file, "w", encoding="utf-8") as f:
            f.write(f"# {plugin_name}.py — {description}\n\n")
            f.write("def placeholder():\n")
            f.write("    return 'stub'\n")

    # test file
    test_file = os.path.join(base, f"test_{plugin_name}.py")
    if not os.path.exists(test_file):
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(f"from executor.plugins.{plugin_name} import {plugin_name}\n\n")
            f.write("def test_placeholder():\n")
            f.write(f"    assert {plugin_name}.placeholder() == 'stub'\n")

    # manifest
    manifest = {
        "name": plugin_name,
        "description": description or f"Plugin {plugin_name}",
        "capabilities": []
    }
    manifest_file = os.path.join(base, "plugin.json")
    if not os.path.exists(manifest_file):
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    print(f"✅ Created new plugin: {plugin_name}")