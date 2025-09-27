import os, json

BASE = os.path.join("executor", "plugins")


def main():
    for entry in os.listdir(BASE):
        plugin_dir = os.path.join(BASE, entry)
        if not os.path.isdir(plugin_dir):
            continue
        manifest_file = os.path.join(plugin_dir, "plugin.json")
        if not os.path.exists(manifest_file):
            continue
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = False
        if "specialist" not in data:
            data["specialist"] = f"executor.plugins.{entry}.specialist"
            updated = True
        if updated:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[add_specialists] Updated {entry}/plugin.json")


if __name__ == "__main__":
    main()
