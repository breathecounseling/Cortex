from __future__ import annotations
from pathlib import Path
import json
import sys
import importlib
from typing import Optional

from executor.audit.logger import get_logger
from executor.utils.config import ensure_dirs
from executor.utils.memory import remember, init_db_if_needed

logger = get_logger(__name__)

TEMPLATE_SPECIALIST = """from __future__ import annotations

def can_handle(intent: str) -> bool:
    return True

def describe_capabilities() -> str:
    return "{description}"

def handle(payload: dict) -> dict:
    return {{"status": "ok", "message": "Handled by {name}", "data": payload}}
"""

def _write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _ensure_packages(base: Path) -> None:
    for rel in ("executor", "executor/plugins"):
        pkg = base / rel
        pkg.mkdir(parents=True, exist_ok=True)
        init_file = pkg / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

def main(name: str, description: str, base_dir: Optional[Path] = None) -> Path:
    """
    Scaffold a new plugin with manifest + specialist and make it importable immediately.
    """
    init_db_if_needed()
    ensure_dirs()

    base = base_dir or Path.cwd()
    _ensure_packages(base)

    plugin_dir = base / "executor" / "plugins" / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py everywhere
    for pkg in (plugin_dir.parent.parent.parent, plugin_dir.parent, plugin_dir):
        init_py = pkg / "__init__.py"
        if not init_py.exists():
            init_py.write_text("", encoding="utf-8")

    # Make temp plugin importable
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    importlib.invalidate_caches()

    specialist_path = plugin_dir / "specialist.py"
    manifest_path = plugin_dir / "plugin.json"

    _write_text(specialist_path, TEMPLATE_SPECIALIST.format(name=name, description=description))
    manifest = {
        "name": name,
        "description": description,
        "capabilities": [name],
        "specialist": f"executor.plugins.{name}.specialist",
    }
    _write_json(manifest_path, manifest)

    try:
        remember("system", "plugin_created", name, source="builder", confidence=1.0)
    except Exception as e:
        logger.error(f"Failed to remember plugin creation: {e}")

    logger.info(f"✅ Created new plugin: {name}\n📂 Plugin dir: {plugin_dir}")
    return plugin_dir