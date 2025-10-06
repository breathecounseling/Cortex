from __future__ import annotations
from pathlib import Path
import sys
import json
from typing import Any, Dict, List

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed
from executor.core import router
from executor.utils.docket import Docket
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


def _strip_idea_prefix(title: str) -> str:
    t = title or ""
    if t.startswith("[idea] "):
        return t[8:]
    if t.startswith("[idea]"):
        return t[6:].lstrip()
    return t


def main() -> None:
    initialize_logging()
    init_db_if_needed()
    print("Executor — chat naturally. Type 'quit' to exit.")
    docket = Docket(namespace="repl")

    for line in sys.stdin:
        user_text = (line or "").strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            return

        # ----- Legacy commands for tests -----
        if user_text.lower().startswith("approve "):
            tid = int(user_text.split(" ", 1)[1])
            # find and promote to todo + strip prefix
            tasks = docket.list_tasks()
            for t in tasks:
                if int(t["id"]) == tid:
                    docket.update(tid, title=_strip_idea_prefix(t["title"]), status="todo")
                    break
            continue

        if user_text.lower().startswith("reject "):
            tid = int(user_text.split(" ", 1)[1])
            docket.remove(tid)
            continue
        # -------------------------------------

        # Route the text (kept for completeness)
        _ = router.route(user_text)

        # And consult OpenAIClient if the test monkeypatches it
        try:
            client = OpenAIClient()  # replaced by tests
            out = client.chat([{"role": "user", "content": user_text}])
            # If it's JSON, parse and act; else treat as plain message
            msg = ""
            try:
                data = json.loads(out)
                msg = data.get("assistant_message") or ""
                # facts
                facts = data.get("facts_to_save") or []
                if facts:
                    facts_file = _mem_path("repl_facts.json")
                    curr = _read_json(facts_file, {})
                    sess = curr.setdefault("repl", {})
                    for f in facts:
                        if isinstance(f, dict) and "key" in f and "value" in f:
                            sess[f["key"]] = f["value"]
                    _write_json(facts_file, curr)
                # tasks
                for t in data.get("tasks_to_add") or []:
                    if isinstance(t, dict) and t.get("title"):
                        docket.add(t["title"], priority=t.get("priority", "normal"))
            except Exception:
                msg = str(out) if out else ""

            if msg:
                print(msg)
        except Exception:
            # If client not available, just continue
            pass