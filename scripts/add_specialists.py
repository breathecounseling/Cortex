import os
import json

BASE = os.path.join("executor", "plugins")
TEMPLATE = os.path.join("executor", "templates", "specialist.py.j2")


def main():
    if not os.path.isdir(BASE):
        print(f"[add_specialists] Skipping: {BASE} not found.")
        return

    try:
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            template_src = f.read()
    except Exception as e:
        print(f"[add_specialists] ERROR: Could not read template {TEMPLATE}: {e}")
        return

    for entry in os.listdir(BASE):
        plugin_dir = os.path.join(BASE, entry)
        # ✅ Skip __pycache__ or hidden dirs
        if not os.path.isdir(plugin_dir):
            continue
        if entry.startswith("__") or entry.endswith("__"):
            continue

        manifest_file = os.path.join(plugin_dir, "plugin.json")
        specialist_file = os.path.join(plugin_dir, "specialist.py")

        updated = False
        manifest = {}

        if os.path.exists(manifest_file):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception as e:
                print(f"[add_specialists] WARNING: Could not parse {manifest_file}: {e}")
                continue
        else:
            manifest = {"name": entry, "description": f"{entry} plugin", "capabilities": []}
            updated = True

        expected = f"executor.plugins.{entry}.specialist"
        if manifest.get("specialist") != expected:
            manifest["specialist"] = expected
            updated = True

        if updated:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            print(f"✅ Updated manifest for {entry}")

        if not os.path.exists(specialist_file):
            try:
                code = template_src.replace("{{ plugin_name }}", entry)
                with open(specialist_file, "w", encoding="utf-8") as sf:
                    sf.write(code)
                print(f"✅ Created specialist.py for {entry}")
            except Exception as e:
                print(f"[add_specialists] ERROR: Could not create specialist for {entry}: {e}")


if __name__ == "__main__":
    main()
