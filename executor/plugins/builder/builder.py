import os
import json
from typing import Any, Dict


def _ensure_parent_packages_exist(base_dir: str) -> None:
    """
    Ensure executor/ and executor/plugins/ are proper packages under base_dir.
    This makes sure imports work when scaffolding into a tmp_path during tests.
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


def main(plugin_name: str, manifest: Dict[str, Any]) -> None:
    """
    Scaffolds a new plugin directory with manifest.json and specialist.py.
    """
    base = os.path.join("executor", "plugins", plugin_name)
    os.makedirs(base, exist_ok=True)

    _ensure_parent_packages_exist(os.getcwd())

    # Write manifest.json
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Write specialist.py from template if not present
    template_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "specialist.py.j2")
    )
    spec_file = os.path.join(base, "specialist.py")
    if not os.path.exists(spec_file):
        try:
            with open(template_path, "r", encoding="utf-8") as tf:
                tmpl = tf.read()
            with open(spec_file, "w", encoding="utf-8") as sf:
                sf.write(tmpl.replace("{{ plugin_name }}", plugin_name))
        except Exception as e:
            print(f"[Builder] Warning: specialist template missing: {e}")

    print(f"✅ Created new plugin: {plugin_name}")
