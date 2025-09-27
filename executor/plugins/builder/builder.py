from __future__ import annotations
import os
import json


def main(plugin_name: str, description: str = "") -> None:
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

    # manifest with specialist
    manifest = {
        "name": plugin_name,
        "description": description or f"Plugin {plugin_name}",
        "capabilities": [],
        "specialist": f"executor.plugins.{plugin_name}.specialist",
    }
    manifest_file = os.path.join(base, "plugin.json")
    if not os.path.exists(manifest_file):
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    # specialist.py from template (absolute path resolution)
    template_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "specialist.py.j2")
    )
    try:
        with open(template_path, "r", encoding="utf-8") as tf:
            tmpl = tf.read()
        spec_file = os.path.join(base, "specialist.py")
        if not os.path.exists(spec_file):
            with open(spec_file, "w", encoding="utf-8") as sf:
                sf.write(tmpl.replace("{{ plugin_name }}", plugin_name))
    except Exception as e:
        print(f"[Builder] Warning: specialist template missing: {e}")

    print(f"✅ Created new plugin: {plugin_name}")
