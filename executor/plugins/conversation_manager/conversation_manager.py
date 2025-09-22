"""
Conversation Manager for Cortex Executor
- Stores turns in JSONL files
- Summarizes/prunes long history
- Provides handle_repl_turn() that formats prior context
- Stores user facts as structured JSON objects with a timestamp, key, and value
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
import time

BASE_PATH = Path(os.environ.get("CONV_MGR_MEMORY_PATH", ".executor/memory"))
BASE_PATH.mkdir(parents=True, exist_ok=True)

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _session_path(session: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session)
    return BASE_PATH / f"{safe}.jsonl"

@contextmanager
def _file_lock(path: Path, timeout: float = 5.0):
    lockfile = str(path) + ".lock"
    start = time.time()
    while True:
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if (time.time() - start) >= timeout:
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.remove(lockfile)
        except FileNotFoundError:
            pass

def save_turn(session: str, role: str, content: str) -> None:
    path = _session_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "timestamp": _utc_now(),
        "role": role,
        "content": content,
    }
    with _file_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def load_turns(session: str) -> list[dict]:
    path = _session_path(session)
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

def clear_turns(session: str) -> None:
    path = _session_path(session)
    if path.exists():
        with _file_lock(path):
            open(path, "w").close()

# --- Fact management ---

def save_fact(session: str, key: str, value: str) -> None:
    fact_record = {
        "timestamp": _utc_now(),
        "key": key,
        "value": value
    }
    save_turn(session, "user_fact", json.dumps(fact_record))

def load_facts(session: str) -> dict:
    facts = {}
    turns = load_turns(session)
    for turn in turns:
        if turn["role"] == "user_fact":
            try:
                fact = json.loads(turn["content"])
                facts[fact["key"]] = fact["value"]
            except Exception:
                continue
    return facts

# --- REPL turn integration ---

def handle_repl_turn(
    current_input: str,
    history: list[dict] | None = None,
    session: str = "cortex",
    limit: int = 10,
) -> dict:
    # Load existing history if not provided
    hist = history if history is not None else load_turns(session)

    # Clip to the last N messages
    trimmed = hist[-limit:] if limit else hist

    # Build new user message
    user_msg = {"role": "user", "content": current_input}

    # Save turn to memory
    save_turn(session, "user", current_input)

    # Simple fact extraction demo
    low = current_input.lower()
    if "favorite color is" in low:
        color = current_input.split("favorite color is")[-1].strip()
        save_fact(session, "favorite_color", color)
    if "favorite food is" in low:
        food = current_input.split("favorite food is")[-1].strip()
        save_fact(session, "favorite_food", food)

    # Return messages including history + new turn
    messages = trimmed + [user_msg]
    return {"messages": messages}

def record_assistant(session: str, content: str) -> None:
    save_turn(session, "assistant", content)

def get_history(session: str) -> list[dict]:
    return load_turns(session)

__all__ = [
    "handle_repl_turn",
    "record_assistant",
    "get_history",
    "clear_turns",
    "save_fact",
    "load_facts",
]
