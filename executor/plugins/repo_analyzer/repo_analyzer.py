from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed, remember

logger = get_logger(__name__)

def scan_repo(root: Path | None = None) -> List[str]:
    initialize_logging()
    init_db_if_needed()
    r = root or Path.cwd()
    files = [str(p) for p in r.rglob("*.py")]
    remember("system", "repo_scan", f"{len(files)} files", source="repo_analyzer", confidence=1.0)
    logger.info(f"Repo scan: {len(files)} python files")
    return files

def can_handle(intent: str) -> bool:
    return intent.lower().strip() in {"repo_analyzer", "repo"}

def describe_capabilities() -> str:
    return "Analyzes repository files for inventory or quick heuristics."

def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    files = scan_repo()
    return {"status": "ok", "message": f"Found {len(files)} python files", "data": {"files": files[:50]}}