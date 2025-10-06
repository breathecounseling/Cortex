from __future__ import annotations
from importlib import import_module
from pathlib import Path
import json
from typing import Dict, Optional

from executor.audit.logger import get_logger
from executor.utils.config import ensure_dirs
from executor.utils.memory import init_db_if_needed

logger = get_logger(__name__)

class Registry:
    """
    Discovers and loads plugin specialists from 'executor/plugins/**/plugin.json'.
    Maintains capability -> specialist module mapping.
    """

    def __init__(self, root: Optional[Path] = None, base: Optional[str] = None):
        # compatibility: tests may pass base= instead of root=
        ensure_dirs()
        init_db_if_needed()
        self.root = Path(base) if base else (root or Path.cwd())
        self._capabilities: Dict[str, str] = {}
        self._specialists: Dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self._capabilities.clear()
        self._specialists.clear()
        plugins_dir = self.root / "executor" / "plugins"
        if not plugins_dir.exists():
            logger.debug("No plugins directory found; skipping registry refresh")
            return
        for manifest_path in plugins_dir.rglob("plugin.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                caps = data.get("capabilities", [])
                spec_path = data.get("specialist")
                if caps and spec_path:
                    for cap in caps:
                        self._capabilities[cap] = spec_path
            except Exception as e:
                logger.error(f"Failed to read manifest {manifest_path}: {e}")

    def get_specialist_for(self, capability: str):
        mod_path = self._capabilities.get(capability)
        if not mod_path:
            return None
        if mod_path not in self._specialists:
            self._specialists[mod_path] = import_module(mod_path)
        return self._specialists[mod_path]

    def capabilities(self):
        return sorted(self._capabilities.keys())

# compatibility alias for older tests
SpecialistRegistry = Registry
