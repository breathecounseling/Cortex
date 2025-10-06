from __future__ import annotations
from pathlib import Path
import json
from typing import Optional

from executor.audit.logger import get_logger
from executor.utils.config import ensure_dirs
from executor.utils.memory import remember, record_repair, init_db_if_needed

logger = get_logger(__name__)

TEMPLATE_SPECIALIST = """from __future__ import annotations

# Auto-generated specialist
def can_handle(intent: str) -> bool:
    # TODO: refine matching for this specialist
    return intent.lower().strip() == "{name}"

def describe_capabilities() -> str:
    return "{description}"

def handle(payload: dict) -> dict:
    # Return a standard result envelope
    return {{"status": "ok", "message": "Handled by {name}", "data": payload}}
"""

TEMPLATE_PLUGIN_JSON = {
    "name": "",
    "description": "",
    "capabilities": [],
    "specialist": ""
}

def _write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

def main(name: str, description: str, base_dir: Optional[Path] = None) -> Path:
    """
    Scaffolds a new plugin with a manifest and a specialist.
    Preserves current CLI signature used by tests.
    Returns the created plugin directory.
    """
    init_db_if_needed()
    ensure_dirs()

    base = base_dir or Path.cwd()
    plugin_dir = base / "executor" / "plugins" / name
    specialist_path = plugin_dir / "specialist.py"
    manifest_path = plugin_dir / "plugin.json"

    if manifest_path.exists() or specialist_path.exists():
        logger.warning(f"Plugin '{name}' already exists; files will be overwritten")

    # specialist.py
    _write_text(specialist_path, TEMPLATE_SPECIALIST.format(name=name, description=description))

    # plugin.json
    manifest = dict(TEMPLATE_PLUGIN_JSON)
    manifest["name"] = name
    manifest["description"] = description
    manifest["specialist"] = f"executor.plugins.{name}.specialist"
    manifest["capabilities"] = [name]

    _write_json(manifest_path, manifest)

    # Persist metadata into memory for discoverability
    try:
        remember("system", "plugin_created", name, source="builder", confidence=1.0)
    except Exception as e:
        logger.error(f"Failed to remember plugin creation: {e}")

    logger.info(f"✅ Created new plugin: {name}\n📂 Plugin dir: {plugin_dir}")
    return plugin_dir