import os
import sys
import json
from typing import Any, Dict


def _ensure_parent_packages_exist(base_dir: str) -> None:
    """
    Ensure executor/ and executor/plugins/ are proper packages under base_dir.
    This is needed when tests scaffold inside a pytest tmp_path.
    """
    exec_dir = os.path.join(base_dir, "executor")
    plugins_dir = os.path.join(exec_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    for path in (
        os.path.join(exec_dir, "__init__.py"),
        os.path.join(plugins_dir, "__init__.py"),
    ):
        if not os.path.exists(path):
            open(path, "w").close()


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _write_specialist_from_template_or_fallback(plugin_name: str, plugin_dir: str) -> None:
    """
    Create specialist.py from templates/specialist.py.j2 if present,
    otherwise write a minimal fallback specialist that satisfies the tests.
    """
    spec_file = os.path.join(plugin_dir, "specialist.py")
    if os.path.exists(spec_file):
        return

    # Template path (corrected to executor/templates/)
    template_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "specialist.py.j2")
    )
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as tf:
            tmpl = tf.read()
        with open(spec_file, "w", encoding="utf-8") as sf:
            sf.write(tmpl.replace("{{ plugin_name }}", plugin_name))
        return

    # Fallback: minimal working specialist
    fallback = f'''"""
Auto-generated specialist for {plugin_name}.
"""
from typing import Dict, Any

def describe_capabilities():
    return ["scaffolded"]

def can_handle(goal: str) -> bool:
    return isinstance(goal, str) and len(goal) > 0

def handle(intent: Dict[str, Any]) -> Dict[str, Any]:
    goal = intent.get("goal", "")
    return {{"status": "ok", "message": f"{plugin_name} handled: " + str(goal)}}
'''
    with open(spec_file, "w", encoding="utf-8") as sf:
        sf.write(fallback)


def main(plugin_name: str, description: str | None = None) -> None:
    """
    Scaffolds a plugin package under executor/plugins/<plugin_name>/ with:
      - plugin.json (tests & extend_plugin rely on this)
      - manifest.json (compatibility alias)
      - specialist.py (from template or fallback)
      - __init__.py (package markers at all levels)
    """
    cwd = os.getcwd()
    _ensure_parent_packages_exist(cwd)

    plugin_dir = os.path.join("executor", "plugins", plugin_name)
    os.makedirs(plugin_dir, exist_ok=True)

    # Ensure plugin package marker
    init_file = os.path.join(plugin_dir, "__init__.py")
    if not os.path.exists(init_file):
        open(init_file, "w").close()

    # Ensure cwd is importable (needed for test_specialist_contract)
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Build manifest dict explicitly
    manifest = {
        "name": plugin_name,
        "description": description or f"Plugin {plugin_name}",
        "capabilities": [],
        "specialist": f"executor.plugins.{plugin_name}.specialist",
    }

    # Write plugin.json and manifest.json
    _write_json(os.path.join(plugin_dir, "plugin.json"), manifest)
    _write_json(os.path.join(plugin_dir, "manifest.json"), manifest)

    # Write specialist.py
    _write_specialist_from_template_or_fallback(plugin_name, plugin_dir)

    # ✅ Debug output
    print(f"✅ Created new plugin: {plugin_name}")
    print(f"📂 Plugin dir: {os.path.abspath(plugin_dir)}")

    # Print the sys.path head (to confirm tmp_path is there)
    print("🔍 sys.path[0:3] =", sys.path[0:3])

    # Explicitly check package markers
    markers = [
        os.path.join("executor", "__init__.py"),
        os.path.join("executor", "plugins", "__init__.py"),
        os.path.join("executor", "plugins", plugin_name, "__init__.py"),
    ]
    for marker in markers:
        print(f"   exists? {marker} -> {os.path.exists(marker)}")

    # List actual files under plugin dir
    for root, dirs, files in os.walk(plugin_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), start=cwd)
            print(f"   - {rel}")