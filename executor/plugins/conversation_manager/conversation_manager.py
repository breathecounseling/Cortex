"""
Conversation Manager for Cortex Executor
- Stores turns in JSONL files
- Summarizes/prunes long history
- Provides handle_repl_turn() that formats prior context as a factual system message
"""

import os
import json
import time
import typing as t
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

# -------------------------
# Utilities
# -------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

def _safe_token_count(text: str) -> int:
    try:
        return max(1, (len(text or "") + 3) // 4)
    except Exception:
        return 1

# -------------------------
# Storage
# -------------------------

BASE_PATH = Path(os.environ.get("CONV_MGR_MEMORY_PATH", ".executor/memory"))
BASE_PATH.mkdir(parents=True, exist_ok=True)

def _session_path(session: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session)
    return BASE_PATH / f"{safe}.jsonl"

@contextmanager
def _file_lock(path: Path):
    lockfile = path.with_suffix(".lock")
    fh = open(lockfile, "w")
    try:
        if os.name == "posix":
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fh.close()
        try: lockfile.unlink()
        except Exception: pass

def save_turn(session: str, role: str, content: str, metadata: dict | None = None) -> None:
    path = _session_path(session)
    _ensure_dir(str(path))
    rec = {
        "timestamp": _utc_now(),
        "role": role,
        "content": content,
        "metadata": metadata or {},
    }
    with _file_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def load_turns(session: str) -> list[dict]:
    path = _session_path(session)
    if not path.exists():
        return []
    out: list[dict] = []
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

# -------------------------
# Fact formatting
# -------------------------

def _normalize(history: list[dict]) -> list[dict]:
    out = []
    for m in history:
        r = str(m.get("role") or "").lower()
        if r in ("user", "assistant"):
            out.append({"role": r, "content": str(m.get("content") or "")})
    return out

def _facts_from_pairs(history: list[dict], limit: int = 10) -> str:
    """
    Convert user/assistant turns into bullet-point factual system message.
    """
    msgs = _normalize(history)
    pairs = []
    i = 0
    while i + 1 < len(msgs):
        u, a = msgs[i], msgs[i+1]
        if u["role"] == "user" and a["role"] == "assistant":
            pairs.append((u["content"], a["content"]))
            i += 2
        else:
            i += 1
    if limit > 0 and len(pairs) > limit:
        pairs = pairs[-limit:]
    lines = ["- User: " + u for u, _ in pairs] + ["- Assistant: " + a for _, a in pairs]
    header = "Conversation history (facts to remember):"
    return header + ("\n" + "\n".join(lines) if lines else "")

# -------------------------
# Public: handle_repl_turn
# -------------------------

def handle_repl_turn(
    current_input: str,
    history: list[dict] | None = None,
    session: str = "cortex",
    limit: int = 10
) -> dict:
    """
    Build GPT-5 input with:
      - system message of factual bullets from prior history
      - user message of current input
    Persists only user/assistant turns.
    """
    hist = history if history is not None else load_turns(session)
    system_msg = {"role": "system", "content": _facts_from_pairs(hist, limit)}
    user_msg = {"role": "user", "content": current_input}

    # Save user turn
    save_turn(session, "user", current_input)

    return {
        "messages": [system_msg, user_msg],
        "updatedHistory": hist + [user_msg],
    }

def record_assistant(session: str, content: str) -> None:
    save_turn(session, "assistant", content)

def get_history(session: str) -> list[dict]:
    return load_turns(session)

__all__ = [
    "handle_repl_turn",
    "record_assistant",
    "get_history",
    "clear_turns",
]
