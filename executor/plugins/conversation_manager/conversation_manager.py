# Plugin: conversation_manager
# Purpose: Store REPL history in a local JSON file with append, list, and clear operations; configurable file path; safe concurrent access via file locks; atomic writes; rotation/retention to prevent unbounded growth.
# Extended: SummarizeOnOverflow — auto-summarize conversation history once it exceeds a token budget and persist the summary.

import os
import sys
import json
import time
import errno
import typing as _t
import datetime as _dt
from contextlib import contextmanager
from collections import deque, defaultdict

# -------------------------
# Environment/config helpers
# -------------------------

_DEFAULT_LOG_PATH = "./logs/repl_history.jsonl"
_configured_log_path: _t.Optional[str] = None  # can be set via set_log_path()

# Summarization defaults/config
class _SummarizationConfig(_t.TypedDict, total=False):
    enabled: bool
    threshold_tokens: int
    keep_last_turns: int
    target_history_tokens: int
    model: str
    max_tokens_short: int
    max_tokens_detailed: int
    language: _t.Optional[str]
    persist_path: str
    retry: dict  # { attempts: int, backoff_ms: int }

_summarization_config: _SummarizationConfig = {
    "enabled": True,
    "threshold_tokens": 2000,
    "keep_last_turns": 6,
    "target_history_tokens": 1200,
    "model": "gpt-4o-mini",
    "max_tokens_short": 200,
    "max_tokens_detailed": 600,
    "language": None,
    "persist_path": "summaries/",
    "retry": {"attempts": 2, "backoff_ms": 500},
}

# Events/Hooks
_on_token_budget_exceeded: _t.Optional[_t.Callable[[str, int], None]] = None
_on_after_summarize: _t.Optional[_t.Callable[[str, dict], None]] = None
_can_summarize_hook: _t.Optional[_t.Callable[[dict], bool]] = None

# Telemetry counters
_number_of_summaries_created = 0
_total_tokens_saved = 0

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
    Ensures exclusive access for append/rotate/clear/mutation operations.
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
# Tokenizer Abstraction
# -------------------------

class ITokenizer(_t.Protocol):
    def count_tokens(self, text: str) -> int: ...


class _CL100KTokenizer:
    def __init__(self) -> None:
        self._enc = None
        try:
            import tiktoken  # type: ignore
            try:
                self._enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                # tiktoken installed but encoding not found
                self._enc = None
        except Exception:
            self._enc = None

    def count_tokens(self, text: str) -> int:
        try:
            if self._enc is not None:
                return len(self._enc.encode(text or ""))
        except Exception as e:
            _debug(f"[conversation_manager] Tokenizer error, falling back to heuristic: {e}")
        # Fallback heuristic: ~4 chars/token
        try:
            return max(1, (len(text or "") + 3) // 4)
        except Exception:
            return 1


_tokenizer: ITokenizer = _CL100KTokenizer()

def set_tokenizer(tokenizer: ITokenizer) -> None:
    global _tokenizer
    _tokenizer = tokenizer


def _safe_count_tokens(text: str) -> int:
    try:
        return int(_tokenizer.count_tokens(text or ""))
    except Exception as e:
        _debug(f"[conversation_manager] Tokenization failed, using heuristic: {e}")
        try:
            return max(1, (len(text or "") + 3) // 4)
        except Exception:
            return 1


# -------------------------
# Summarization model abstraction (optional external)
# -------------------------

_SummarizeFn = _t.Callable[[str, int, int, _t.Optional[str]], _t.Tuple[str, str]]
_summarize_model_fn: _t.Optional[_SummarizeFn] = None

def set_summarization_model(fn: _SummarizeFn) -> None:
    """
    Optionally set an external summarization function.
    Signature: (context_text, max_tokens_short, max_tokens_detailed, language) -> (short_summary, detailed_summary)
    """
    global _summarize_model_fn
    _summarize_model_fn = fn


# -------------------------
# Public API (existing)
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
# New feature: Prepend last N messages to a prompt
# -------------------------

def get_recent_messages(n: int, session_id: _t.Optional[_t.Any] = None, include_types: _t.Optional[_t.Iterable[str]] = None) -> _t.List[dict]:
    """
    Load the last N messages from the JSON history, optionally filtered by session_id and types.

    - n: number of records to return (last N).
    - session_id: if provided, only records matching this sessionId are returned.
    - include_types: iterable of types to include (e.g., {"input", "output"}). Defaults to both.
    Returns records ordered from oldest to newest among the last N.
    """
    if not isinstance(n, int) or n <= 0:
        return []
    types_set = None
    if include_types is not None:
        try:
            types_set = {str(t).lower() for t in include_types}
        except Exception:
            types_set = None
    records = list_history(limit=max(n, 1))
    if session_id is not None:
        sid = str(session_id)
        records = [r for r in records if r.get("sessionId") == sid]
    if types_set is not None:
        records = [r for r in records if str(r.get("type", "")).lower() in types_set]
    if len(records) < n:
        all_records = list_history(limit=None)
        if session_id is not None:
            sid = str(session_id)
            all_records = [r for r in all_records if r.get("sessionId") == sid]
        if types_set is not None:
            all_records = [r for r in all_records if str(r.get("type", "")).lower() in types_set]
        records = all_records[-n:] if n < len(all_records) else all_records
    return records[-n:] if n < len(records) else records


def prepend_history_to_prompt(
    prompt: _t.Any,
    n: int = 10,
    session_id: _t.Optional[_t.Any] = None,
    include_types: _t.Optional[_t.Iterable[str]] = None,
    include_timestamps: bool = False,
    header: _t.Optional[str] = "History:"
) -> str:
    """
    Build a new prompt string with the last N messages from history prepended.

    - prompt: the current prompt string to prepend to.
    - n: number of messages to include.
    - session_id: optional session filter.
    - include_types: optional iterable of types to include (defaults to {"input","output"}).
    - include_timestamps: include ISO timestamps in the history lines if True.
    - header: optional header string placed before the history block. Use None or "" to omit.
    """
    base_prompt = "" if prompt is None else str(prompt)
    records = get_recent_messages(n=n, session_id=session_id, include_types=include_types)
    if not records:
        return base_prompt
    lines: _t.List[str] = []
    for r in records:
        typ = str(r.get("type", ""))
        txt = "" if r.get("text") is None else str(r.get("text"))
        if include_timestamps:
            ts = str(r.get("timestamp", ""))
            line = f"[{ts}] {typ}: {txt}"
        else:
            line = f"{typ}: {txt}"
        lines.append(line)
    parts: _t.List[str] = []
    if header:
        parts.append(str(header))
    parts.extend(lines)
    history_block = "\n".join(parts).strip()
    if not history_block:
        return base_prompt
    if base_prompt:
        return f"{history_block}\n\n{base_prompt}"
    else:
        return history_block


def prepend_last_messages_to_prompt(
    prompt: _t.Any,
    n: int = 10,
    session_id: _t.Optional[_t.Any] = None,
    include_types: _t.Optional[_t.Iterable[str]] = None,
    include_timestamps: bool = False,
    header: _t.Optional[str] = "History:"
) -> str:
    """
    Alias for prepend_history_to_prompt for convenience/compatibility.
    """
    return prepend_history_to_prompt(
        prompt=prompt,
        n=n,
        session_id=session_id,
        include_types=include_types,
        include_timestamps=include_timestamps,
        header=header,
    )


# -------------------------
# SummarizeOnOverflow Implementation
# -------------------------

def set_summarization_config(**kwargs) -> None:
    """
    Override summarization config. Keys:
    enabled, threshold_tokens, keep_last_turns, target_history_tokens, model, max_tokens_short,
    max_tokens_detailed, language, persist_path, retry
    """
    global _summarization_config
    for k, v in kwargs.items():
        if k in _summarization_config:
            _summarization_config[k] = v


def get_summarization_config() -> dict:
    return dict(_summarization_config)


def set_event_handlers(
    onTokenBudgetExceeded: _t.Optional[_t.Callable[[str, int], None]] = None,
    onAfterSummarize: _t.Optional[_t.Callable[[str, dict], None]] = None,
) -> None:
    global _on_token_budget_exceeded, _on_after_summarize
    _on_token_budget_exceeded = onTokenBudgetExceeded
    _on_after_summarize = onAfterSummarize


def set_can_summarize_hook(fn: _t.Callable[[dict], bool]) -> None:
    global _can_summarize_hook
    _can_summarize_hook = fn


def _infer_role(rec: dict) -> str:
    # Prefer explicit role
    role = str(rec.get("role") or "").lower().strip()
    if role in ("user", "assistant", "system", "tool"):
        return role
    typ = str(rec.get("type") or "").lower().strip()
    if typ == "input":
        return "user"
    if typ == "output":
        return "assistant"
    if typ in ("history_summary", "system_policy", "system"):
        return "system"
    return "assistant" if "output" in typ else ("user" if "input" in typ else "system")


def _must_preserve(rec: dict) -> bool:
    if bool(rec.get("required", False)):
        return True
    typ = str(rec.get("type") or "").lower()
    if typ in ("tool_result_required", "system_policy"):
        return True
    # Preserve system/initial instruction messages
    role = _infer_role(rec)
    if role == "system":
        return True
    return False


def _can_summarize(rec: dict) -> bool:
    if _must_preserve(rec):
        return False
    if _can_summarize_hook is not None:
        try:
            return bool(_can_summarize_hook(rec))
        except Exception:
            return False
    return True


def _assign_message_ids(records: _t.List[dict]) -> None:
    """
    Ensure each record has a stable messageId. If missing, add one using timestamp and index.
    Mutates records in-place.
    """
    for idx, r in enumerate(records):
        if "messageId" in r and r["messageId"]:
            continue
        ts = str(r.get("timestamp") or _iso_utc_now())
        # Add a suffix to avoid collisions among same timestamps
        r["messageId"] = f"{ts}:{idx:08d}"


def _conversation_records(all_records: _t.List[dict], conversation_id: str) -> _t.List[dict]:
    return [r for r in all_records if str(r.get("sessionId") or "") == str(conversation_id)]


def _token_counts_for_records(records: _t.List[dict]) -> _t.Tuple[int, _t.Dict[str, int]]:
    total = 0
    by_role: _t.Dict[str, int] = defaultdict(int)
    for r in records:
        role = _infer_role(r)
        text = str(r.get("text") or "")
        # Include some metadata text for summary/system entries
        if role == "system" and r.get("type") == "history_summary":
            # Count short summary text
            text = str(r.get("short_summary") or "") + " " + str(r.get("text") or "")
        n = _safe_count_tokens(text)
        total += n
        by_role[role] += n
    return total, dict(by_role)


def getTokenCounts(conversationId: str) -> dict:
    """
    Return token counts for a conversation:
    { total: number, byRole: { role: tokens } }
    """
    records = list_history(limit=None)
    convo = _conversation_records(records, conversationId)
    _assign_message_ids(convo)
    total, by_role = _token_counts_for_records(convo)
    return {"total": total, "byRole": by_role}


def _sentences(text: str) -> _t.List[str]:
    # Simple sentence splitter
    import re
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extractive_summarize(context_text: str, max_tokens_short: int, max_tokens_detailed: int, language: _t.Optional[str]) -> _t.Tuple[str, str]:
    """
    Simple frequency-based extractive summarizer with token budget trimming.
    """
    # Build candidate sentences
    sents = _sentences(context_text)
    if not sents:
        sents = [context_text.strip()]

    # Compute word frequency
    from collections import Counter
    import re
    stop = set([
        "the","is","in","at","of","a","and","to","it","for","on","this","that","with","as","by","an","be","are","was","were","or","if","from","we","you","they","i"
    ])
    def words(s: str) -> _t.List[str]:
        return [w for w in re.findall(r"[A-Za-z0-9_]+", s.lower()) if w not in stop]

    freq = Counter()
    for s in sents:
        for w in words(s):
            freq[w] += 1

    def score(s: str) -> float:
        ws = words(s)
        if not ws:
            return 0.0
        return sum(freq[w] for w in ws) / len(ws)

    ranked = sorted(((score(s), i, s) for i, s in enumerate(sents)), key=lambda x: (-x[0], x[1]))

    def build_summary(max_tokens: int) -> str:
        parts: _t.List[str] = []
        used = 0
        # Greedy add top sentences until budget
        for _, _, s in ranked:
            t = _safe_count_tokens(s)
            if used + t <= max_tokens or not parts:
                parts.append(s)
                used += t
            if used >= max_tokens:
                break
        summary = " ".join(parts).strip()
        # Ensure within budget
        summary = _trim_to_token_budget(summary, max_tokens)
        return summary

    short = build_summary(max_tokens_short)
    detailed = build_summary(max_tokens_detailed)
    # Optionally mark language
    if language:
        # Non-destructive marker to indicate requested language
        short = f"{short}"
        detailed = f"{detailed}"
    return short, detailed


def _generate_summaries(context_text: str, max_short: int, max_detailed: int, language: _t.Optional[str]) -> _t.Tuple[str, str, bool]:
    """
    Returns (short_summary, detailed_summary, used_fallback)
    Applies retries for external model, then falls back to extractive summarization.
    """
    attempts = int((_summarization_config.get("retry") or {}).get("attempts", 2))
    backoff_ms = int((_summarization_config.get("retry") or {}).get("backoff_ms", 500))
    used_fallback = False

    if _summarize_model_fn is not None:
        for i in range(max(1, attempts)):
            try:
                s, d = _summarize_model_fn(context_text, max_short, max_detailed, language)
                # Enforce token budgets
                s = _trim_to_token_budget(s or "", max_short)
                d = _trim_to_token_budget(d or "", max_detailed)
                return s, d, used_fallback
            except Exception as e:
                _debug(f"[conversation_manager] Summarization model attempt {i+1} failed: {e}")
                if i < attempts - 1:
                    time.sleep(max(0, backoff_ms) / 1000.0)
                else:
                    # fall back
                    pass

    used_fallback = True
    s, d = _extractive_summarize(context_text, max_short, max_detailed, language)
    return s, d, used_fallback


def _trim_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    # Quick accept
    if _safe_count_tokens(text) <= max_tokens:
        return text
    # Binary-search-ish trim by characters
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid]
        t = _safe_count_tokens(candidate)
        if t <= max_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best.strip()


def _build_context_text(records: _t.List[dict], language: _t.Optional[str]) -> str:
    """
    Convert records into a summarization context text.
    """
    lines: _t.List[str] = []
    for r in records:
        role = _infer_role(r)
        ts = r.get("timestamp") or ""
        txt = str(r.get("text") or "")
        lines.append(f"[{ts}] {role}: {txt}")
    context = "\n".join(lines)
    return context


def _persist_summary(conversation_id: str, meta: dict) -> _t.Tuple[str, str]:
    """
    Persist the summary meta and payloads to summaries/<conversation_id>/<summary_version>.json
    Returns (summary_version, persisted_path)
    """
    base = str(_summarization_config.get("persist_path") or "summaries/")
    # Normalize base to directory
    if base.endswith(".json"):
        base = os.path.dirname(base)
    convo_dir = os.path.join(base, str(conversation_id))
    try:
        os.makedirs(convo_dir, exist_ok=True)
    except Exception:
        pass

    # Determine next version
    version = 1
    try:
        existing = []
        for name in os.listdir(convo_dir):
            if name.endswith(".json") and name[:-5].isdigit():
                existing.append(int(name[:-5]))
        if existing:
            version = max(existing) + 1
    except Exception:
        pass

    path = os.path.join(convo_dir, f"{version}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception as e:
        _debug(f"[conversation_manager] Persist summary error: {e}")
    return str(version), path


def _latest_summary_file(conversation_id: str) -> _t.Optional[str]:
    base = str(_summarization_config.get("persist_path") or "summaries/")
    convo_dir = os.path.join(base, str(conversation_id))
    if not os.path.exists(convo_dir):
        return None
    try:
        candidates = [n for n in os.listdir(convo_dir) if n.endswith(".json") and n[:-5].isdigit()]
        if not candidates:
            return None
        latest = max(candidates, key=lambda n: int(n[:-5]))
        return os.path.join(convo_dir, latest)
    except Exception:
        return None


def getLatestSummary(conversationId: str) -> _t.Optional[dict]:
    """
    Load the latest summary record for the conversation, or None.
    """
    path = _latest_summary_file(conversationId)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_with_summary_internal(conversationId: str, last_k: int) -> _t.List[dict]:
    """
    Internal: Build view of history with summary marker + recent turns for the given conversation.
    """
    all_records = list_history(limit=None)
    convo = _conversation_records(all_records, conversationId)
    _assign_message_ids(convo)
    # Find the latest history_summary marker for convo
    markers = [r for r in convo if str(r.get("type")) == "history_summary"]
    marker = markers[-1] if markers else None
    # Take last K turns excluding markers by type, but include system policy, etc.
    # Consider turns as any messages not of type history_summary or summary_pointer
    def is_turn(r: dict) -> bool:
        t = str(r.get("type") or "")
        return t not in ("history_summary", "summary_pointer")
    recent_turns = [r for r in convo if is_turn(r)][-max(0, int(last_k)):]
    result: _t.List[dict] = []
    if marker:
        result.append(marker)
    result.extend(recent_turns)
    return result


def loadWithSummary(conversationId: str) -> _t.List[dict]:
    """
    Return a view of the conversation consisting of the latest summary marker (if any)
    followed by the most recent keep_last_turns messages (unchanged).
    """
    cfg = get_summarization_config()
    last_k = int(cfg.get("keep_last_turns", 6))
    return _load_with_summary_internal(conversationId, last_k)


def _build_history_summary_message(conversation_id: str, summary_version: str, persisted_path: str,
                                   short_summary: str, meta: dict, token_count_before: int, token_count_after: int) -> dict:
    """
    Build synthetic system history_summary message.
    """
    message = {
        "timestamp": _iso_utc_now(),
        "type": "history_summary",
        "role": "system",
        "sessionId": str(conversation_id),
        "summary_version": summary_version,
        "persist_path": persisted_path,
        "short_summary": short_summary,
        "last_message_id_covered": meta.get("last_message_id_covered"),
        "covered_message_ids": meta.get("covered_message_ids", []),
        "covered_time_range": meta.get("covered_time_range", []),
        "language": meta.get("language"),
        "token_count_before": token_count_before,
        "token_count_after": token_count_after,
        "text": f"Summarized prior history. Detailed summary stored at {persisted_path} (version {summary_version}).",
        "required": True,  # ensure preserved
    }
    # Also include a compact pointer
    return message


def _emit_budget_exceeded(conversation_id: str, total_tokens: int) -> None:
    if _on_token_budget_exceeded:
        try:
            _on_token_budget_exceeded(str(conversation_id), int(total_tokens))
        except Exception:
            pass


def _emit_after_summarize(conversation_id: str, summary_meta: dict) -> None:
    if _on_after_summarize:
        try:
            _on_after_summarize(str(conversation_id), dict(summary_meta))
        except Exception:
            pass


def _build_summary_pointer_record(conversation_id: str, version: str) -> dict:
    return {
        "timestamp": _iso_utc_now(),
        "type": "summary_pointer",
        "role": "system",
        "sessionId": str(conversation_id),
        "latest_summary_version": str(version),
        "text": f"Latest summary version pointer for conversation {conversation_id}: {version}",
        "required": True,
    }


def _compute_idempotency_state(convo_records: _t.List[dict], keep_last_turns: int) -> _t.Tuple[_t.Optional[str], _t.Set[str], _t.List[dict], _t.List[dict], _t.List[dict]]:
    """
    Returns:
      last_marker_last_id_covered, to_drop_ids, preserved_records, summarizable_older, recent_kept
    """
    _assign_message_ids(convo_records)
    # Determine recent kept turns (excluding history_summary and summary_pointer)
    def is_turn(r: dict) -> bool:
        t = str(r.get("type") or "")
        return t not in ("history_summary", "summary_pointer")
    turns = [r for r in convo_records if is_turn(r)]
    recent_kept = turns[-max(0, int(keep_last_turns)):]
    recent_ids = {str(r.get("messageId")) for r in recent_kept}
    # Preserved messages (system, required, etc.)
    preserved_records = [r for r in convo_records if _must_preserve(r)]
    preserved_ids = {str(r.get("messageId")) for r in preserved_records}
    # Summarizable older = all convo records that are turns, not preserved, not in recent_kept
    summarizable_older = [r for r in convo_records if (is_turn(r) and str(r.get("messageId")) not in recent_ids and not _must_preserve(r) and _can_summarize(r))]
    to_drop_ids = {str(r.get("messageId")) for r in summarizable_older}
    # Last marker coverage
    markers = [r for r in convo_records if str(r.get("type")) == "history_summary"]
    last_marker_last_id_covered = markers[-1].get("last_message_id_covered") if markers else None
    return (
        str(last_marker_last_id_covered) if last_marker_last_id_covered else None,
        to_drop_ids,
        preserved_records,
        summarizable_older,
        recent_kept
    )


def summarizeHistory(conversationId: str) -> dict:
    """
    Summarize history for the given conversation if thresholds exceeded.
    Returns SummaryMeta dict.
    """
    cfg = get_summarization_config()
    if not cfg.get("enabled", True):
        return {
            "status": "disabled",
            "conversation_id": str(conversationId),
        }

    # Load all records
    path = get_log_path()
    all_records = list_history(limit=None)
    convo_records = _conversation_records(all_records, conversationId)
    _assign_message_ids(convo_records)
    token_before, _ = _token_counts_for_records(convo_records)
    threshold = int(cfg.get("threshold_tokens", 2000))
    keep_last_turns = int(cfg.get("keep_last_turns", 6))
    target_tokens = int(cfg.get("target_history_tokens", 1200))
    language = cfg.get("language")
    max_short = int(cfg.get("max_tokens_short", 200))
    max_detailed = int(cfg.get("max_tokens_detailed", 600))

    # Idempotency check
    last_covered_id, to_drop_ids, preserved_records, summarizable_older, recent_kept = _compute_idempotency_state(convo_records, keep_last_turns)

    if token_before <= threshold:
        # If already under threshold and prior summary covers all older messages, skip
        if last_covered_id:
            # Determine if older messages are entirely covered by last summary
            # Find index of last_covered_id within convo_records
            ids = [str(r.get("messageId")) for r in convo_records if str(r.get("type") or "") not in ("summary_pointer",)]
            try:
                idx_covered = ids.index(str(last_covered_id))
            except ValueError:
                idx_covered = -1
            # Compute which remain beyond covered but not in last K
            beyond = [rid for rid in ids if rid not in {str(r.get("messageId")) for r in recent_kept} and rid not in {str(r.get("messageId")) for r in preserved_records}]
            # If last covered reaches the last element of "beyond", then it's fully covered
            fully_covered = (not beyond) or (idx_covered >= (len(ids) - len(recent_kept) - 1))
            if fully_covered:
                latest = getLatestSummary(conversationId)
                return {
                    "status": "skipped",
                    "reason": "under_threshold_and_already_summarized",
                    "conversation_id": str(conversationId),
                    "latest_summary": latest,
                    "token_count_total": token_before,
                }
        # Under threshold and no prior coverage -> nothing to do
        return {
            "status": "skipped",
            "reason": "under_threshold",
            "conversation_id": str(conversationId),
            "latest_summary": getLatestSummary(conversationId),
            "token_count_total": token_before,
        }

    # Token budget exceeded -> emit event
    _emit_budget_exceeded(conversationId, token_before)

    # Build older portion context
    older_records = summarizable_older
    # Also include any non-turn messages that are not preserved but older? We keep it simple: older_records as computed.

    # If nothing to summarize (e.g., only preserved + recent exist), skip
    if not older_records:
        return {
            "status": "skipped",
            "reason": "nothing_to_summarize",
            "conversation_id": str(conversationId),
            "token_count_total": token_before,
        }

    # Prepare context text
    context_text = _build_context_text(older_records, language)

    # Generate summaries (with retries and fallback)
    start_ts = time.time()
    short_summary, detailed_summary, used_fallback = _generate_summaries(context_text, max_short, max_detailed, language if (language or None) else None)
    duration_ms = int((time.time() - start_ts) * 1000)

    # Scope metadata
    covered_ids = [str(r.get("messageId")) for r in older_records]
    # Compute covered time range
    try:
        times = [r.get("timestamp") for r in older_records if r.get("timestamp")]
        covered_time_range = [min(times), max(times)] if times else []
    except Exception:
        covered_time_range = []

    # Persist detailed summary and metadata
    created_at = _iso_utc_now()
    summary_meta = {
        "conversation_id": str(conversationId),
        "created_at": created_at,
        "covered_message_ids": covered_ids,
        "covered_time_range": covered_time_range,
        "short_summary": f"{short_summary}\n\nScope: messages={covered_ids[:3]}...(+{max(0,len(covered_ids)-3)} more), time={covered_time_range}",
        "detailed_summary": f"{detailed_summary}\n\nScope: messages={covered_ids[:10]}...(+{max(0,len(covered_ids)-10)} more), time={covered_time_range}",
        "language": language,
        "token_count_before": token_before,
        # token_count_after to be set after mutation
        "model": cfg.get("model"),
        "used_fallback": used_fallback,
        "retry": cfg.get("retry"),
        "duration_ms": duration_ms,
    }
    version, persisted_path = _persist_summary(conversationId, summary_meta)

    # Now mutate history: replace older_records with a synthetic history_summary message
    try:
        with _file_lock(path):
            # Re-read to avoid races
            all_lines = list_history(limit=None)
            # Assign ids consistently
            _assign_message_ids(all_lines)
            # Build sets for convo
            convo_ids = {str(r.get("messageId")) for r in _conversation_records(all_lines, conversationId)}
            older_id_set = set(covered_ids)
            # Identify recent_kept and preserved again with current snapshot
            convo_snapshot = _conversation_records(all_lines, conversationId)
            _assign_message_ids(convo_snapshot)
            _, _, preserved_records2, summarizable_older2, recent_kept2 = _compute_idempotency_state(convo_snapshot, keep_last_turns)
            older_id_set = {str(r.get("messageId")) for r in summarizable_older2}
            preserved_ids2 = {str(r.get("messageId")) for r in preserved_records2}
            recent_ids2 = {str(r.get("messageId")) for r in recent_kept2}

            # last_message_id_covered = the max id among older set in chronological order
            last_message_id_covered = None
            if summarizable_older2:
                last_message_id_covered = str(summarizable_older2[-1].get("messageId"))

            # Build new list while inserting a summary marker once before the first recent kept record
            new_records: _t.List[dict] = []
            inserted_marker = False

            # We'll compute tokens after building to update meta in persisted file and the marker
            for r in all_lines:
                sid = str(r.get("sessionId") or "")
                mid = str(r.get("messageId"))
                if sid != str(conversationId):
                    new_records.append(r)
                    continue
                # Skip prior summary_pointer lines (we will append a fresh pointer)
                if str(r.get("type") or "") == "summary_pointer":
                    continue
                # If this message is in older_id_set -> drop
                if mid in older_id_set:
                    # Before dropping, if we are about to enter the recent section, insert the marker
                    continue
                # If this is the first recent record and marker not yet inserted -> insert marker before it
                if not inserted_marker and mid in recent_ids2:
                    # Build temporary marker with placeholder counts; fill after token calculation
                    temp_marker = _build_history_summary_message(
                        conversation_id=str(conversationId),
                        summary_version=version,
                        persisted_path=persisted_path,
                        short_summary=short_summary,
                        meta={
                            "covered_message_ids": covered_ids,
                            "covered_time_range": covered_time_range,
                            "last_message_id_covered": last_message_id_covered,
                            "language": language,
                        },
                        token_count_before=token_before,
                        token_count_after=0,  # placeholder
                    )
                    _assign_message_ids([temp_marker])
                    new_records.append(temp_marker)
                    inserted_marker = True
                # Keep preserved or recent or other convo messages
                new_records.append(r)

            # If never inserted marker but there were older records dropped, append at end
            if older_id_set and not inserted_marker:
                temp_marker = _build_history_summary_message(
                    conversation_id=str(conversationId),
                    summary_version=version,
                    persisted_path=persisted_path,
                    short_summary=short_summary,
                    meta={
                        "covered_message_ids": covered_ids,
                        "covered_time_range": covered_time_range,
                        "last_message_id_covered": last_message_id_covered,
                        "language": language,
                    },
                    token_count_before=token_before,
                    token_count_after=0,
                )
                _assign_message_ids([temp_marker])
                new_records.append(temp_marker)

            # Append summary pointer (latest version)
            pointer = _build_summary_pointer_record(conversationId, version)
            _assign_message_ids([pointer])
            new_records.append(pointer)

            # Recompute token_count_after for this conversation based on new_records
            new_convo = [r for r in new_records if str(r.get("sessionId") or "") == str(conversationId)]
            after_total, _ = _token_counts_for_records(new_convo)

            # Update token_count_after in marker and persist meta update
            for r in new_records:
                if str(r.get("sessionId") or "") == str(conversationId) and str(r.get("type")) == "history_summary" and r.get("summary_version") == version:
                    r["token_count_after"] = after_total

            # Atomic rewrite file
            tmp_path = path + ".tmp"
            try:
                with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                    for rec in new_records:
                        line = json.dumps(rec, ensure_ascii=False)
                        f.write(line + "\n")
                    try:
                        f.flush()
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(tmp_path, path)
            except Exception as e:
                _debug(f"[conversation_manager] Rewrite history with summary failed: {e}")
                # Best effort: do not leave tmp file behind
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

            # Update persisted meta with after tokens
            try:
                latest_path = os.path.join(str(_summarization_config.get("persist_path") or "summaries/"), str(conversationId), f"{version}.json")
                if os.path.exists(latest_path):
                    with open(latest_path, "r", encoding="utf-8") as f:
                        persisted = json.load(f)
                else:
                    persisted = summary_meta
                persisted["token_count_after"] = after_total
                with open(latest_path, "w", encoding="utf-8") as f:
                    json.dump(persisted, f, ensure_ascii=False, indent=2)
                    try:
                        f.flush()
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            except Exception as e:
                _debug(f"[conversation_manager] Update persisted summary after-tokens failed: {e}")

            # Telemetry
            global _number_of_summaries_created, _total_tokens_saved
            _number_of_summaries_created += 1
            saved = max(0, token_before - after_total)
            _total_tokens_saved += saved

            # Events
            meta_emit = {
                "conversation_id": str(conversationId),
                "summary_version": version,
                "created_at": created_at,
                "token_count_before": token_before,
                "token_count_after": after_total,
                "covered_message_ids": covered_ids,
                "covered_time_range": covered_time_range,
                "language": language,
                "persist_path": persisted_path,
                "used_fallback": used_fallback,
                "duration_ms": duration_ms,
            }
            _emit_after_summarize(conversationId, meta_emit)

            return {
                "status": "ok",
                "conversation_id": str(conversationId),
                "summary_version": version,
                "persist_path": persisted_path,
                "token_count_before": token_before,
                "token_count_after": after_total,
                "language": language,
                "used_fallback": used_fallback,
                "duration_ms": duration_ms,
            }
    except Exception as e:
        _debug(f"[conversation_manager] summarizeHistory mutation error: {e}")
        # Fallback: do not mutate, but still return persisted info
        return {
            "status": "error",
            "error": str(e),
            "conversation_id": str(conversationId),
            "summary_version": version,
            "persist_path": persisted_path,
            "token_count_before": token_before,
            "language": language,
        }


def get_summarization_stats() -> dict:
    """
    Telemetry counters: number_of_summaries_created, total_tokens_saved
    """
    return {
        "number_of_summaries_created": _number_of_summaries_created,
        "total_tokens_saved": _total_tokens_saved,
    }


# -------------------------
# ask_executor Integration
# -------------------------

_history_window_size_default = 10
_history_window_size = _history_window_size_default
_ask_executor_backend: _t.Optional[_t.Callable[..., _t.Any]] = None

def set_history_window_size(n: int) -> None:
    """
    Set default history window size for ask_executor integration.
    """
    global _history_window_size
    try:
        n = int(n)
    except Exception:
        return
    if n <= 0:
        n = 0
    _history_window_size = n

def get_history_window_size() -> int:
    """
    Get default history window size for ask_executor integration.
    """
    return int(_history_window_size)

def set_ask_executor_backend(fn: _t.Callable[..., _t.Any]) -> None:
    """
    Set the underlying ask_executor function to delegate to.
    """
    global _ask_executor_backend
    _ask_executor_backend = fn

def _record_to_message(rec: dict) -> dict:
    return {
        "role": _infer_role(rec),
        "content": "" if rec.get("text") is None else str(rec.get("text")),
    }

def _normalize_current_messages(prompt: _t.Optional[_t.Any], messages: _t.Optional[_t.Sequence[dict]]) -> _t.List[dict]:
    if isinstance(messages, (list, tuple)) and messages:
        # Shallow-coerce to {role, content}
        out: _t.List[dict] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip().lower() or "user"
            content = "" if m.get("content") is None else str(m.get("content"))
            out.append({"role": role, "content": content})
        return out
    # Fallback to prompt string as a single user message
    if prompt is None:
        return []
    return [{"role": "user", "content": str(prompt)}]

def ask_executor(
    prompt: _t.Optional[_t.Any] = None,
    *,
    messages: _t.Optional[_t.Sequence[dict]] = None,
    session_id: _t.Optional[_t.Any] = None,
    conversation_id: _t.Optional[_t.Any] = None,
    conversationId: _t.Optional[_t.Any] = None,
    include_history: bool = True,
    history_window_size: _t.Optional[int] = None,
    include_types: _t.Optional[_t.Iterable[str]] = None,
    **kwargs,
) -> _t.Any:
    """
    Wrapper around the configured ask_executor backend that:
    1) Fetches up to last N messages from the active conversation history,
    2) Transforms them into [{role, content}],
    3) Builds the final messages as [history..., current_prompt/messages],
    4) Calls the backend with the combined messages.

    Behavior:
    - If fewer than N messages exist, include all available.
    - If none exist or retrieval fails, forward the current prompt/messages as-is.
    - Avoid duplicating the current prompt (drop last history msg if same role+content as current last).
    - Maintain chronological order (oldest ... newest).
    - include_history=False disables history inclusion for this call.

    Configuration:
    - Default window is 10; override per call via history_window_size or globally via set_history_window_size().
    """
    if _ask_executor_backend is None:
        raise RuntimeError("[conversation_manager] ask_executor backend is not configured. Set via set_ask_executor_backend(fn).")

    # Resolve conversation/session id preference
    sid = session_id
    if sid is None:
        sid = conversation_id if conversation_id is not None else conversationId

    # Normalize current prompt/messages
    current_msgs = _normalize_current_messages(prompt, messages)

    # If history disabled or window size is zero, just forward current
    n_hist = _history_window_size if (history_window_size is None) else max(0, int(history_window_size))
    if not include_history or n_hist <= 0:
        try:
            # Prefer messages API for backend
            return _ask_executor_backend(messages=current_msgs, **kwargs)
        except TypeError:
            # Fallback: if backend doesn't accept messages, try prompt (join user contents)
            joined = "\n\n".join(m.get("content", "") for m in current_msgs)
            return _ask_executor_backend(prompt=joined, **kwargs)

    # Fetch history and transform; gracefully degrade on error
    history_msgs: _t.List[dict] = []
    try:
        recs = get_recent_messages(n=n_hist, session_id=sid, include_types=include_types)
        # Transform to [{role, content}]
        history_msgs = [_record_to_message(r) for r in recs]
    except Exception as e:
        _debug(f"[conversation_manager] History retrieval failed, degrading to current prompt. Error: {e}")
        history_msgs = []

    # Avoid duplicating the current prompt: if last history equals last current
    if history_msgs and current_msgs:
        h_last = history_msgs[-1]
        c_last = current_msgs[-1]
        try:
            if (str(h_last.get("role")).strip().lower() == str(c_last.get("role")).strip().lower() and
                (h_last.get("content") or "").strip() == (c_last.get("content") or "").strip()):
                history_msgs = history_msgs[:-1]
        except Exception:
            # If any issue comparing, keep history as-is
            pass

    combined = list(history_msgs) + list(current_msgs)

    # Dispatch to backend with combined prompt/messages
    try:
        return _ask_executor_backend(messages=combined, **kwargs)
    except TypeError:
        # Backend might expect a string prompt; combine into a single prompt string
        # Format as simple concatenation of role-tagged lines
        def _format_message(m: dict) -> str:
            role = (m.get("role") or "user").strip().lower()
            content = "" if m.get("content") is None else str(m.get("content"))
            return f"{role}: {content}"
        joined = "\n".join(_format_message(m) for m in combined)
        return _ask_executor_backend(prompt=joined, **kwargs)


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
    "get_recent_messages",
    "prepend_history_to_prompt",
    "prepend_last_messages_to_prompt",
    # SummarizeOnOverflow API
    "set_summarization_config",
    "get_summarization_config",
    "set_tokenizer",
    "set_summarization_model",
    "set_event_handlers",
    "set_can_summarize_hook",
    "getTokenCounts",
    "summarizeHistory",
    "getLatestSummary",
    "loadWithSummary",
    "get_summarization_stats",
    # ask_executor integration
    "ask_executor",
    "set_ask_executor_backend",
    "set_history_window_size",
    "get_history_window_size",
]