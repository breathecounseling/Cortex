import os
import json

TEMPLATE = os.path.join("executor", "templates", "specialist.py.j2")
PLUGINS_DIR = os.path.join("executor", "plugins")


def _load_template() -> str:
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        return f.read()


def _render_template(template: str, plugin_name: str) -> str:
    return template.replace("{{ plugin_name }}", plugin_name)


def ensure_specialist(plugin_dir: str, plugin_name: str):
    """Ensure specialist.py and manifest entry exist for a plugin."""
    specialist_file = os.path.join(plugin_dir, "specialist.py")
    manifest_file = os.path.join(plugin_dir, "plugin.json")

    # Create specialist.py if missing
    if not os.path.exists(specialist_file):
        template = _load_template()
        content = _render_template(template, plugin_name)
        with open(specialist_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[add_specialists] Created specialist.py for {plugin_name}")

    # Ensure manifest has specialist entry
    if os.path.exists(manifest_file):
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"name": plugin_name, "description": f"Plugin {plugin_name}", "capabilities": []}

    expected_path = f"executor.plugins.{plugin_name}.specialist"
    if manifest.get("specialist") != expected_path:
        manifest["specialist"] = expected_path
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[add_specialists] Updated manifest for {plugin_name}")


def main():
    for entry in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, entry)
        if not os.path.isdir(plugin_dir) or entry == "__pycache__":
            continue
        ensure_specialist(plugin_dir, entry)


if __name__ == "__main__":
    main()