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
        except Exception as e:
            print(f"[add_specialists] Could not read {manifest_file}: {e}")
            continue

        expected = f"executor.plugins.{entry}.specialist"
        if data.get("specialist") != expected:
            data["specialist"] = expected
            try:
                with open(manifest_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                print(f"✅ Updated manifest for {entry}")
            except Exception as e:
                print(f"[add_specialists] Could not write {manifest_file}: {e}")

if __name__ == "__main__":
    main()
