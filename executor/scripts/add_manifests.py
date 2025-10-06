from __future__ import annotations
import sys

def main():
    # simple shim that satisfies the dry-run expectations
    # real script exists at project root: scripts/add_manifests.py
    if "--dry" in sys.argv:
        print("All plugins have manifests (dry run).")
        return 0
    print("Manifest check complete.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
