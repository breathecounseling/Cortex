#!/usr/bin/env python
"""
Scan executor/plugins/ and create plugin.json in any folder missing one.
"""

import os, json

PLUGINS_DIR = os.path.join("executor", "plugins")

def main():
    if not os.path.isdir(PLUGINS_DIR):
        print(f"❌ Plugins dir not found: {PLUGINS_DIR}")
        return

    for entry in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, entry)
        if not os.path.isdir(plugin_dir):
            continue

        manifest_path = os.path.join(plugin_dir, "plugin.json")
        if os.path.exists(manifest_path):
            continue

        manifest = {
            "name": entry,
            "description": f"{entry} plugin — description to be updated.",
            "capabilities": []
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"✅ Created manifest: {manifest_path}")

    print("🎉 Done scanning for missing manifests.")

if __name__ == "__main__":
    main()
