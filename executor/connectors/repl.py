from __future__ import annotations
from pathlib import Path
import sys
import json

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed
from executor.core import router
from executor.connectors.openai_client import OpenAIClient  # exposed for tests

logger = get_logger(__name__)

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
            print(msg)

        # compatibility: tests stub OpenAIClient.chat() returning JSON string
        try:
            client = OpenAIClient()
            raw = client.chat([{"role": "user", "content": user_text}])
            if isinstance(raw, str) and raw.strip():
                print(raw)
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        # Save assistant message if present
                        if parsed.get("assistant_message"):
                            print(parsed["assistant_message"])
                        # Facts
                        facts_json = _mem_path("repl_facts.json")
                        current = _read_json(facts_json, {})
                        sess = current.setdefault("repl", {})
                        for f in parsed.get("facts_to_save", []):
                            k, v = f.get("key"), f.get("value")
                            if k and v:
                                sess[k] = v
                        _write_json(facts_json, current)
                        # Tasks
                        tasks_json = _mem_path("repl_tasks.json")
                        current_tasks = _read_json(tasks_json, [])
                        for t in parsed.get("tasks_to_add", []):
                            title = t.get("title")
                            if title:
                                current_tasks.append({"title": title, "priority": t.get("priority", "normal")})
                        _write_json(tasks_json, current_tasks)
                except Exception:
                    pass
        except Exception:
            pass

        # always persist minimal actions
        _write_json(_mem_path("repl_actions.json"), data.get("actions", []))