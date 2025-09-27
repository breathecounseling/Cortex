import os, json

BASE = os.path.join("executor", "plugins")

def main():
    if not os.path.isdir(BASE):
        print(f"[add_specialists] Skipping: {BASE} not found.")
        return

    for entry in os.listdir(BASE):
        plugin_dir = os.path.join(BASE, entry)
        if not os.path.isdir(plugin_dir) or entry == "__pycache__":
            continue

        manifest_file = os.path.join(plugin_dir, "plugin.json")
        if not os.path.exists(manifest_file):
            continue

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        expected = f"executor.plugins.{entry}.specialist"
        updated = False

        if data.get("specialist") != expected:
            data["specialist"] = expected
            updated = True

        specialist_file = os.path.join(plugin_dir, "specialist.py")
        if not os.path.exists(specialist_file):
            try:
                tmpl_path = os.path.join("executor", "templates", "specialist.py.j2")
                with open(tmpl_path, "r", encoding="utf-8") as tf:
                    tmpl = tf.read()
                with open(specialist_file, "w", encoding="utf-8") as sf:
                    sf.write(tmpl.replace("{{ plugin_name }}", entry))
                updated = True
            except Exception as e:
                print(f"[add_specialists] Could not create specialist for {entry}: {e}")

        if updated:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"✅ Updated {entry}")

if __name__ == "__main__":
    main()
