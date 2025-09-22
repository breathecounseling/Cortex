#!/usr/bin/env python
"""
Scan executor/plugins/ and create plugin.json in any folder missing one.

Usage:
    python scripts/add_manifests.py          # creates manifests if missing
    python scripts/add_manifests.py --dry    # checks only, no writes
"""

import os, json, sys

PLUGINS_DIR = os.path.join("executor", "plugins")

def scan_plugins(dry_run: bool = False) -> int:
    """Return number of missing manifests (and create them unless dry_run=True)."""
    missing = 0
    if not os.path.isdir(PLUGINS_DIR):
        print(f"❌ Plugins dir not found: {PLUGINS_DIR}")
        return -1

    for entry in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, entry)
        if not os.path.isdir(plugin_dir):
            continue

        manifest_path = os.path.join(plugin_dir, "plugin.json")
        if os.path.exists(manifest_path):
            continue

        missing += 1
        if dry_run:
            print(f"⚠️ Missing manifest: {manifest_path}")
            continue

        manifest = {
            "name": entry,
            "description": f"{entry} plugin — description to be updated.",
            "capabilities": []
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"✅ Created manifest: {manifest_path}")

    if missing == 0:
        print("🎉 All plugins have manifests.")
    else:
        print(f"⚠️ {missing} plugin(s) missing manifests.")
    return missing

def main():
    dry = "--dry" in sys.argv
    scan_plugins(dry_run=dry)

if __name__ == "__main__":
    main()
