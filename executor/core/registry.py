from __future__ import annotations
from importlib import import_module
from pathlib import Path
import json
from typing import Dict, Callable, Optional

from executor.audit.logger import get_logger
from executor.utils.config import ensure_dirs
from executor.utils.memory import init_db_if_needed

logger = get_logger(__name__)

class Registry:
    """
    Discovers and loads plugin specialists from 'executor/plugins/**/plugin.json'.
    Maintains a mapping of capability -> specialist module path.
    """
    def __init__(self, root: Optional[Path] = None):
        ensure_dirs()
        init_db_if_needed()
        self.root = root or Path.cwd()
        self._capabilities: Dict[str, str] = {}
        self._specialists: Dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self._capabilities.clear()
        self._specialists.clear()
        plugins_dir = self.root / "executor" / "plugins"
        if not plugins_dir.exists():
            logger.info("No plugins directory found; skipping registry refresh")
            return
        for manifest_path in plugins_dir.rglob("plugin.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                caps = data.get("capabilities", [])
                spec_path = data.get("specialist")
                if caps and spec_path:
                    for cap in caps:
                        self._capabilities[cap] = spec_path
                else:
                    logger.warning(f"Manifest missing fields: {manifest_path}")
            except Exception as e:
                logger.error(f"Failed to read manifest {manifest_path}: {e}")

        logger.debug(f"Registry loaded {len(self._capabilities)} capabilities")

    def get_specialist_for(self, capability: str):
        mod_path = self._capabilities.get(capability)
        if not mod_path:
            return None
        if mod_path not in self._specialists:
            self._specialists[mod_path] = import_module(mod_path)
        return self._specialists[mod_path]

    def capabilities(self):
        return sorted(self._capabilities.keys())

SpecialistRegistry = Registry
