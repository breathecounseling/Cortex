# Plugin: conversation_manager
# Purpose: Store REPL history in a local JSON file with append, list, and clear operations; configurable file path; safe concurrent access via file locks; atomic writes; rotation/retention to prevent unbounded growth.

import os
import sys
import json
import time
import errno
import typing as _t
import datetime as _dt
from contextlib import contextmanager
from collections import deque

# -------------------------
# Environment/config helpers
# -------------------------

_DEFAULT_LOG_PATH = "./logs/repl_history.jsonl"
_configured_log_path: _t.Optional[str] = None  # can be set via set_log_path()


def _parse_bool(value: _t.Optional[str], default: bool) -> bool:
    if value is None:
        return default
    value = value.strip().lower()
    return value in ("1", "true", "yes", "on", "y", "t")


def get_log_enabled() -> bool:
    # Default true unless explicitly disabled
    return _parse_bool(os.environ.get("CONVO_LOG_ENABLED"), True)


def get_log_path() -> str:
    global _configured_log_path
    if _configured_log_path:
        return _configured_log_path
    return os.environ.get("CONVO_LOG_PATH", _DEFAULT_LOG_PATH)


def set_log_path(path: str) -> None:
    global _configured_log_path
    _configured_log_path = path


def _get_max_bytes() -> int:
    # Optional retention limit (bytes). If <= 0, rotation disabled.
    raw = os.environ.get("CONVO_LOG_MAX_BYTES", "").strip()
    if not raw:
        return 10 * 1024 * 1024  # 10 MB default
    try:
        return int(raw)
    except ValueError:
        return 10 * 1024 * 1024


def _get_keep_files() -> int:
    raw = os.environ.get("CONVO_LOG_KEEP", "").strip()
    if not raw:
        return 3
    try:
        v = int(raw)
        return max(0, v)
    except ValueError:
        return 3


def _debug(msg: str) -> None:
    try:
        print(msg, file=sys.stderr)
    except Exception:
        pass


# -------------------------
# Time helper
# -------------------------

def _iso_utc_now() -> str:
    # ISO 8601 UTC with Z suffix, millisecond precision
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    s = now.isoformat(timespec="milliseconds")
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


# -------------------------
# Filesystem helpers
# -------------------------

def _ensure_dir_exists(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if not d:
        return
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        # Do not propagate errors to caller/repl
        pass


@contextmanager
def _file_lock(lock_path: str, timeout: float = 10.0, poll_interval: float = 0.05):
    """
    Cross-platform advisory lock using a companion .lock file.
    Ensures exclusive access for append/rotate/clear operations.
    """
    lockfile_path = lock_path + ".lock"
    start = time.time()
    fh = None
    try:
        _ensure_dir_exists(lockfile_path)
        fh = open(lockfile_path, mode="a+")
        # Acquire platform-specific lock
        if os.name == "nt":
            import msvcrt  # type: ignore
            acquired = False
            while not acquired:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError as e:
                    if e.errno not in (errno.EACCES, errno.EDEADLK):
                        # Unexpected error, avoid blocking REPL
                        break
                    if (time.time() - start) > timeout:
                        break
                    time.sleep(poll_interval)
        else:
            import fcntl  # type: ignore
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        # Release lock
        try:
            if fh is not None:
                if os.name == "nt":
                    try:
                        import msvcrt  # type: ignore
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    try:
                        import fcntl  # type: ignore
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
        finally:
            try:
                if fh is not None:
                    fh.close()
            except Exception:
                pass


def _rotate_if_needed(log_path: str) -> None:
    """
    Rotate the JSONL log if it exceeds max bytes.
    Uses .1, .2, ... suffixes. Oldest files beyond keep count are discarded.
    """
    try:
        max_bytes = _get_max_bytes()
        if max_bytes <= 0:
            return
        if not os.path.exists(log_path):
            return
        try:
            size = os.path.getsize(log_path)
        except OSError:
            return
        if size <= max_bytes:
            return

        keep = _get_keep_files()
        # Shift existing rotations upward
        for idx in range(keep - 1, 0, -1):
            older = f"{log_path}.{idx}"
            newer = f"{log_path}.{idx + 1}"
            if os.path.exists(older):
                try:
                    if os.path.exists(newer):
                        os.remove(newer)
                except Exception:
                    pass
                try:
                    os.replace(older, newer)
                except Exception:
                    pass

        # Move current to .1
        target = f"{log_path}.1"
        try:
            if os.path.exists(target):
                os.remove(target)
        except Exception:
            pass
        try:
            os.replace(log_path, target)
        except Exception:
            # If replace fails, skip rotation to avoid interfering with writes
            return
    except Exception as e:
        _debug(f"[conversation_manager] Rotation error: {e}")


# -------------------------
# Public API
# -------------------------

def log_repl_input(text: _t.Any, session_id: _t.Optional[_t.Any] = None) -> bool:
    """
    Log a REPL input line/event to JSONL.
    Returns True on best-effort success, False if logging was skipped or failed.
    """
    return _log_event("input", text, session_id)


def log_repl_output(text: _t.Any, session_id: _t.Optional[_t.Any] = None) -> bool:
    """
    Log a REPL output line/event to JSONL.
    Returns True on best-effort success, False if logging was skipped or failed.
    """
    return _log_event("output", text, session_id)


def _log_event(event_type: str, text: _t.Any, session_id: _t.Optional[_t.Any]) -> bool:
    if not get_log_enabled():
        return False
    try:
        if event_type not in ("input", "output"):
            # Coerce unknown types to "output" rather than raising
            event_type = "output"
        path = get_log_path()
        _ensure_dir_exists(path)
        with _file_lock(path):
            _rotate_if_needed(path)
            record: dict = {
                "timestamp": _iso_utc_now(),
                "type": event_type,
                "text": "" if text is None else str(text),
            }
            if session_id is not None:
                record["sessionId"] = str(session_id)
            line = json.dumps(record, ensure_ascii=False)
            # Append atomically and durably
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    # Even if fsync fails, don't interrupt caller
                    pass
        return True
    except Exception as e:
        _debug(f"[conversation_manager] Logging error: {e}")
        return False


def append_record(record: dict) -> bool:
    """
    Generic append for already-structured records.
    Will ensure required fields and JSONL formatting.
    """
    if not get_log_enabled():
        return False
    try:
        path = get_log_path()
        _ensure_dir_exists(path)
        with _file_lock(path):
            _rotate_if_needed(path)
            rec = dict(record or {})
            # Ensure required fields
            rec.setdefault("timestamp", _iso_utc_now())
            rec.setdefault("type", "output")
            rec.setdefault("text", "")
            line = json.dumps(rec, ensure_ascii=False)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass
        return True
    except Exception as e:
        _debug(f"[conversation_manager] Append error: {e}")
        return False


def list_history(limit: _t.Optional[int] = None) -> _t.List[dict]:
    """
    Read history records from the JSONL file.
    If limit is provided, returns the most recent N entries.
    Gracefully skips malformed lines.
    """
    path = get_log_path()
    if not os.path.exists(path):
        return []
    items: _t.Deque[dict] = deque(maxlen=limit if (isinstance(limit, int) and limit > 0) else None)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                except Exception:
                    # Skip malformed line
                    continue
    except Exception as e:
        _debug(f"[conversation_manager] List history error: {e}")
        return []
    return list(items)


def clear_history(remove_rotations: bool = True) -> bool:
    """
    Truncate the current JSONL log file. Optionally remove rotated files.
    """
    path = get_log_path()
    try:
        _ensure_dir_exists(path)
        with _file_lock(path):
            # Truncate main file
            with open(path, "w", encoding="utf-8") as f:
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass
            if remove_rotations:
                keep = max(_get_keep_files(), 0)
                # Remove any .1.. .N files; we don't know exact count, search a reasonable range
                for idx in range(1, max(keep, 10) + 10):
                    rp = f"{path}.{idx}"
                    if os.path.exists(rp):
                        try:
                            os.remove(rp)
                        except Exception:
                            pass
        return True
    except Exception as e:
        _debug(f"[conversation_manager] Clear history error: {e}")
        return False


# -------------------------
# Backward-compatible run()
# -------------------------

def run():
    print("[conversation_manager] Running placeholder task.")
    return {
        "status": "ok",
        "plugin": "conversation_manager",
        "purpose": "Store REPL history in a local JSON file with append, list, and clear operations; configurable file path; safe concurrent access via file locks; atomic writes; rotation/retention to prevent unbounded growth.",
    }


__all__ = [
    "run",
    "get_log_enabled",
    "get_log_path",
    "set_log_path",
    "log_repl_input",
    "log_repl_output",
    "append_record",
    "list_history",
    "clear_history",
]