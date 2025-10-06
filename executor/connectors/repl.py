from __future__ import annotations
from pathlib import Path
import sys
import json

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed
from executor.core import router
# expose for tests to monkeypatch
from executor.connectors.openai_client import OpenAIClient  # noqa: F401

logger = get_logger(__name__)

# compatibility: tests monkeypatch this path
_MEM_DIR = str(Path(".executor") / "memory")

def _mem_path(name: str) -> Path:
    p = Path(_MEM_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p / name

def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

def main() -> None:
    initialize_logging()
    init_db_if_needed()
    print("Executor — chat naturally. Type 'quit' to exit.")
    for line in sys.stdin:
        user_text = (line or "").strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            return

        data = router.route(user_text)
        msg = data.get("assistant_message") or ""
        if msg:
            print(msg)  # tests expect visible output
        _write_json(_mem_path("repl_actions.json"), data.get("actions", []))