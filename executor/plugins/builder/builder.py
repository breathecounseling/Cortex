import os
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


def _write_specialist_from_template(plugin_name: str, plugin_dir: str) -> None:
    """
    Create specialist.py from templates/specialist.py.j2 if it doesn't exist.
    """
    spec_file = os.path.join(plugin_dir, "specialist.py")
    if os.path.exists(spec_file):
        return

    template_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "specialist.py.j2")
    )
    try:
        with open(template_path, "r", encoding="utf-8") as tf:
            tmpl = tf.read()
        with open(spec_file, "w", encoding="utf-8") as sf:
            sf.write(tmpl.replace("{{ plugin_name }}", plugin_name))
    except Exception as e:
        # Do not crash scaffolding if the template is missing — warn and continue.
        print(f"[Builder] Warning: specialist template missing: {e}")


def main(plugin_name: str, manifest: Dict[str, Any]) -> None:
    """
    Scaffolds a plugin package under executor/plugins/<plugin_name>/ with:
      - plugin.json (primary contract; tests & extend_plugin rely on this)
      - manifest.json (optional alias; harmless to keep parity with old code)
      - specialist.py (from template, if missing)
      - __init__.py (package marker for the plugin dir)
    """
    # Make sure package inits exist under current working directory
    _ensure_parent_packages_exist(os.getcwd())

    plugin_dir = os.path.join("executor", "plugins", plugin_name)
    os.makedirs(plugin_dir, exist_ok=True)

    # Ensure plugin package exists
    init_file = os.path.join(plugin_dir, "__init__.py")
    if not os.path.exists(init_file):
        open(init_file, "w").close()

    # Normalize manifest and write files expected by tests
    manifest = dict(manifest or {})
    manifest.setdefault("name", plugin_name)
    manifest.setdefault("description", "")
    manifest.setdefault("capabilities", [])
    # Prefer explicit specialist dotted path if present; else default convention.
    manifest.setdefault("specialist", f"executor.plugins.{plugin_name}.specialist")

    # Primary contract used by tests and extend flow
    _write_json(os.path.join(plugin_dir, "plugin.json"), manifest)
    # Optional alias (kept to avoid breaking any existing code that read manifest.json)
    _write_json(os.path.join(plugin_dir, "manifest.json"), manifest)

    # Create specialist.py from template (no overwrite)
    _write_specialist_from_template(plugin_name, plugin_dir)

    print(f"✅ Created new plugin: {plugin_name}")
