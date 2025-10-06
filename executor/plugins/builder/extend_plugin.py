from __future__ import annotations
from pathlib import Path
import json
from typing import Optional

from executor.audit.logger import get_logger
from executor.utils.memory import remember, init_db_if_needed
from . import builder as _builder

logger = get_logger(__name__)

def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))

def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

def extend_plugin(plugin_name: str, instruction: str, base_dir: Optional[Path] = None) -> dict:
    """
    Ensure plugin exists, manifest has specialist, and record the extension.
    Returns a dict with at least {"status": "ok", "manifest": {…}} for tests.
    """
    init_db_if_needed()
    base = base_dir or Path.cwd()
    plugin_dir = base / "executor" / "plugins" / plugin_name
    manifest_path = plugin_dir / "plugin.json"

    if not manifest_path.exists():
        # scaffold missing plugin minimally
        _builder.main(plugin_name, f"Specialist for {plugin_name}", base_dir=base)

    data = _read_json(manifest_path)
    if not data.get("specialist"):
        data["specialist"] = f"executor.plugins.{plugin_name}.specialist"
        _write_json(manifest_path, data)

    try:
        remember("system", "plugin_extended", f"{plugin_name}:{instruction}", source="builder")
    except Exception as e:
        logger.warning(f"Failed to remember extension: {e}")

    logger.info(f"🔧 Extended plugin '{plugin_name}' with instruction: {instruction}")
    return {"status": "ok", "manifest": data}
