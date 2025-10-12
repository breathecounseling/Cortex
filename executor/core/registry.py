from __future__ import annotations
# PATCH START: deterministic plugin manifest support
import json
from pathlib import Path

def _load_manifest_plugins() -> list[str]:
    manifest_path = Path(__file__).parent.parent / "plugins" / "plugins_manifest.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text())
            plugins = data.get("plugins", [])
            if plugins:
                return plugins
        except Exception:
            pass
    return []

# integrate into existing discovery logic
manifest_plugins = _load_manifest_plugins()
if manifest_plugins:
    discovered_plugins = manifest_plugins
else:
    # existing directory scanning logic follows unchanged
    discovered_plugins = _scan_plugins_directory()
# PATCH END

from importlib import import_module
from pathlib import Path
import json, sys, importlib
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
        self.plugins_dir = (
            self.root / "executor" / "plugins"
            if (self.root / "executor" / "plugins").exists()
            else self.root
        )
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

    def _extend_plugin_paths(self, base: Path) -> None:
        """Ensure both executor and executor.plugins know about tmp plugin dir."""
        pkg_exec = base / "executor"
        pkg_plugins = pkg_exec / "plugins"
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        try:
            import executor as _exec
            if hasattr(_exec, "__path__"):
                p = str(pkg_exec)
                if p not in _exec.__path__:
                    _exec.__path__.append(p)
            import executor.plugins as _plugs
            if hasattr(_plugs, "__path__"):
                q = str(pkg_plugins)
                if q not in _plugs.__path__:
                    _plugs.__path__.append(q)
        except Exception:
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
                base = self.plugins_dir.parent.parent
                self._extend_plugin_paths(base)
                self._specialists[mod_path] = import_module(mod_path)
        return self._specialists[mod_path]

    def has_plugin(self, name: str) -> bool:
        return (name in self._plugin_names) or (name in self._capabilities)

    def get_specialist(self, name: str):
        return self.get_specialist_for(name)

SpecialistRegistry = Registry
