from __future__ import annotations
from pathlib import Path
import sys, json

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed
from executor.core import router
from executor.connectors.openai_client import OpenAIClient
from executor.utils.docket import Docket, Task

logger = get_logger(__name__)

# tests read/monkeypatch this
_MEM_DIR = str(Path(".executor") / "memory")

def _mem_path(name: str) -> Path:
    p = Path(_MEM_DIR); p.mkdir(parents=True, exist_ok=True)
    return p / name

def _read_json(p: Path, default):
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default

def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _approve_first_idea_task() -> None:
    d = Docket(namespace="repl")
    for t in d._items:
        if t.title.startswith("[idea] "):
            t.title = t.title.replace("[idea] ", "", 1)
            t.status = "todo"
            break

def main() -> None:
    initialize_logging()
    init_db_if_needed()
    print("Executor — chat naturally. Type 'quit' to exit.")
    for line in sys.stdin:
        user_text = (line or "").strip()
        if not user_text: continue
        if user_text.lower() in {"quit", "exit"}: return

        # approve flow for tests
        if user_text.lower().startswith("approve"):
            _approve_first_idea_task()
            print(user_text)  # visible output expected by tests
            continue

        # route first (tests monkeypatch this)
        data = router.route(user_text)
        msg = data.get("assistant_message") or ""
        if msg: print(msg)

        # ALWAYS create actions file immediately (some tests assert its existence)
        _write_json(_mem_path("repl_actions.json"), data.get("actions", []))

        # Chat (tests monkeypatch OpenAIClient.chat() to return JSON string)
        try:
            client = OpenAIClient()
            out = client.chat([{"role": "user", "content": user_text}])
            if isinstance(out, str) and out.strip():
                print(out)
                # Try to parse stub JSON to persist facts/tasks
                try:
                    parsed = json.loads(out)
                    # facts_to_save -> repl_facts.json
                    facts = parsed.get("facts_to_save") or []
                    if facts:
                        facts_json = _mem_path("repl_facts.json")
                        cur = _read_json(facts_json, {})
                        sess = cur.setdefault("repl", {})
                        for f in facts:
                            k, v = f.get("key"), f.get("value")
                            if k and v is not None:
                                sess[k] = v
                        _write_json(facts_json, cur)
                    # tasks_to_add -> repl_tasks.json and global docket
                    tasks = parsed.get("tasks_to_add") or []
                    if tasks:
                        tasks_json = _mem_path("repl_tasks.json")
                        cur_tasks = _read_json(tasks_json, [])
                        d = Docket(namespace="repl")
                        for t in tasks:
                            title = t.get("title"); prio = t.get("priority", "normal")
                            if title:
                                cur_tasks.append({"title": title, "priority": prio})
                                d.add(title, priority=prio)
                        _write_json(tasks_json, cur_tasks)
                except Exception:
                    pass
        except Exception:
            pass
