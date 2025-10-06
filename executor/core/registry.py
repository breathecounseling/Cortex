from __future__ import annotations
from importlib import import_module
from pathlib import Path
import json
import sys
import importlib
from typing import Dict, Optional, Set

from executor.audit.logger import get_logger
from executor.utils.config import ensure_dirs
from executor.utils.memory import init_db_if_needed

logger = get_logger(__name__)

class Registry:
    def __init__(self, root: Optional[Path] = None, base: Optional[str] = None):
        ensure_dirs()
        init_db_if_needed()
        self.root = Path(base) if base else (root or Path.cwd())
        # If a project root was provided, look in executor/plugins under it; else treat provided base as plugins dir.
        self.plugins_dir = self.root / "executor" / "plugins" if (self.root / "executor" / "plugins").exists() else self.root
        self._capabilities: Dict[str, str] = {}
        self._plugin_names: Set[str] = set()
        self._specialists: Dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self._capabilities.clear()
        self._plugin_names.clear()
        self._specialists.clear()
        if not self.plugins_dir.exists():
            return
        for manifest_path in self.plugins_dir.rglob("plugin.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                name = data.get("name", "")
                caps = data.get("capabilities", []) or []
                spec = data.get("specialist")
                if name:
                    self._plugin_names.add(name)
                if caps and spec:
                    for cap in caps:
                        self._capabilities[cap] = spec
            except Exception:
                continue

    def _ensure_tmp_import_visibility(self) -> None:
        """
        Ensure that the dynamic tmp plugins dir is importable as 'executor.plugins.*':
        - sys.path contains the tmp base (plugins_dir/../../)
        - executor.__path__ includes that base's 'executor' folder
        - import caches are invalidated
        """
        base = self.plugins_dir.parent.parent  # .../executor/plugins -> tmp base
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        try:
            import executor as _exec  # if executor already imported, extend its search path
            pkg_path = str(base / "executor")
            if hasattr(_exec, "__path__") and pkg_path not in _exec.__path__:
                _exec.__path__.append(pkg_path)
        except Exception:
            # If executor not imported yet, normal import will find it via sys.path
            pass
        importlib.invalidate_caches()

    def get_specialist_for(self, capability: str):
        mod_path = self._capabilities.get(capability)
        if not mod_path:
            return None
        if mod_path not in self._specialists:
            try:
                self._specialists[mod_path] = import_module(mod_path)
            except ModuleNotFoundError:
                # Fallback: make the tmp-scaffolded package visible and retry
                self._ensure_tmp_import_visibility()
                self._specialists[mod_path] = import_module(mod_path)
        return self._specialists[mod_path]

    def capabilities(self):
        return sorted(self._capabilities.keys())

    # compatibility expected by tests
    def has_plugin(self, name: str) -> bool:
        return (name in self._plugin_names) or (name in self._capabilities)

    # compatibility helper used by tests
    def get_specialist(self, name: str):
        return self.get_specialist_for(name)

# compatibility alias
SpecialistRegistry = Registry
