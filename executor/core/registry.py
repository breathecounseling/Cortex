import os
import sys
import json
import importlib
from typing import Dict, Any


class SpecialistRegistry:
    def __init__(self, base: str = os.path.join("executor", "plugins")) -> None:
        self.base = base
        self.plugins: Dict[str, Any] = {}
        # Auto-load plugins on construction
        self.refresh()

    def refresh(self) -> None:
        """Reload all specialists from plugin manifests in self.base."""
        self.plugins.clear()

        # Ensure parent of executor is importable (repo root or pytest tmp dir)
        abs_executor_parent = os.path.abspath(os.path.join(self.base, "..", ".."))
        if abs_executor_parent not in sys.path:
            sys.path.insert(0, abs_executor_parent)

        # ✅ Clear caches and drop all executor-related modules
        importlib.invalidate_caches()
        for mod in list(sys.modules.keys()):
            if mod == "executor" or mod.startswith("executor."):
                sys.modules.pop(mod)

        if not os.path.isdir(self.base):
            return

        for entry in os.listdir(self.base):
            plugin_dir = os.path.join(self.base, entry)
            if not os.path.isdir(plugin_dir):
                continue

            # Prefer plugin.json (tests & extend_plugin write this),
            # fall back to manifest.json for compatibility.
            manifest_path = os.path.join(plugin_dir, "plugin.json")
            if not os.path.exists(manifest_path):
                alt = os.path.join(plugin_dir, "manifest.json")
                manifest_path = alt if os.path.exists(alt) else None

            if not manifest_path:
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception as e:
                print(f"[Registry] Failed to read manifest for {entry}: {e}")
                continue

            # Resolve specialist module path
            modname = manifest.get("specialist") or f"executor.plugins.{entry}.specialist"

            try:
                module = importlib.import_module(modname)
                self.plugins[entry] = module
            except Exception as e:
                print(f"[Registry] Failed to import {modname}: {e}")

    def get(self, name: str):
        """Return the specialist module for a given plugin name."""
        return self.plugins.get(name)

    def get_specialist(self, name: str):
        """Alias for get(): return the specialist module for a given plugin name."""
        return self.plugins.get(name)

    def all(self):
        """Return a list of all loaded specialist modules."""
        return list(self.plugins.values())

    def has_plugin(self, name: str) -> bool:
        """Return True if the registry has a specialist loaded for this name."""
        return name in self.plugins
