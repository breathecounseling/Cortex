import importlib
import json
import os
import sys
from typing import Dict, Any


class SpecialistRegistry:
    def __init__(self, base: str = "executor/plugins"):
        self.base = base
        self.plugins: Dict[str, Dict[str, Any]] = {}
        self.specialists: Dict[str, Any] = {}
        self.refresh()

    def refresh(self) -> None:
        """Re-scan plugin directories for manifests + specialists."""
        self.plugins.clear()
        self.specialists.clear()

        # Add the directory containing "executor" to sys.path
        abs_root = os.path.abspath(os.path.join(self.base, "..", ".."))
        if abs_root not in sys.path:
            sys.path.insert(0, abs_root)

        for entry in os.listdir(self.base):
            pdir = os.path.join(self.base, entry)
            if not os.path.isdir(pdir):
                continue
            manifest_file = os.path.join(pdir, "plugin.json")
            if not os.path.exists(manifest_file):
                continue
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                self.plugins[entry] = manifest
                specialist_path = manifest.get("specialist")
                if specialist_path:
                    mod = importlib.import_module(specialist_path)
                    self.specialists[entry] = mod
            except Exception as e:
                print(f"[Registry] Failed to load {entry}: {e}")

    def has_plugin(self, name: str) -> bool:
        return name in self.plugins

    def get_specialist(self, name: str):
        return self.specialists.get(name)

    def list_plugins(self) -> Dict[str, Any]:
        return self.plugins
