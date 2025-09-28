import importlib
import json
import os
import sys
from typing import Dict, Any


class SpecialistRegistry:
    """
    Dynamically discovers plugins and loads their specialists.

    Contract:
      - Works for the repo tree (executor/plugins) and pytest tmp trees (…/tmp/.../executor/plugins).
      - Loads plugin.json and imports the module path in "specialist".
      - Exposes has_plugin(), get_specialist(), list_plugins().
    """
    def __init__(self, base: str = "executor/plugins"):
        self.base = base
        self.plugins: Dict[str, Dict[str, Any]] = {}
        self.specialists: Dict[str, Any] = {}
        self.refresh()

    def _ensure_importable(self) -> None:
        """
        Ensure the directory that *contains* the 'executor' package is on sys.path.
        If base is .../<root>/executor/plugins, we need to add .../<root> to sys.path.
        """
        if not self.base:
            return
        # parent of executor (…/tmproot OR repo root)
        abs_executor_parent = os.path.abspath(os.path.join(self.base, "..", ".."))
        if abs_executor_parent not in sys.path:
            sys.path.insert(0, abs_executor_parent)

    def refresh(self) -> None:
        """Re-scan plugin directories for manifests + specialists."""
        self.plugins.clear()
        self.specialists.clear()
        if not os.path.isdir(self.base):
            return

        self._ensure_importable()

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