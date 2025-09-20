"""
Self-repair loop for Cortex Executor

- Detects failing tests / runtime errors
- Locates the most likely file(s) to patch via repo_analyzer
- Requests a patch from the model (direct API call to avoid recursion)
- Applies the patch atomically and re-runs tests
"""

from __future__ import annotations
import os
import re
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from executor.plugins.repo_analyzer import repo_analyzer

# Load .env for API key if needed
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# ---------------------------
# Pytest helpers
# ---------------------------

def run_pytest(target: Optional[str] = None) -> Tuple[bool, str]:
    """
    Run pytest; if target is provided, run just that path.
    Returns (passed, combined_output).
    """
    import subprocess

    args = ["python", "-m", "pytest", "-q"]
    if target:
        args.append(target)
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
        return True, proc.stdout
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + "\n" + (e.stderr or "")


# ---------------------------
# Error parsing helpers
# ---------------------------

_FILE_LINE_RE = re.compile(r"^\s*File\s+\"([^\"]+)\",\s+line\s+(\d+)", re.MULTILINE)
_IMPORT_ERR_RE = re.compile(r"(ImportError|ModuleNotFoundError|AttributeError):[^\n]*", re.IGNORECASE)
_TRACE_FILE_RE = re.compile(r"(?m)^(.*?)(executor[\\/].*?\.py):(\d+):")

def guess_failing_file(error_log: str) -> Optional[str]:
    """
    Inspect error_log and try to locate the most likely user file that failed.
    Preference order:
    - explicit 'executor/...' paths in stack trace
    - first 'File "executor/...py", line N' match
    """
    # direct "executor/.." pattern
    for m in _TRACE_FILE_RE.finditer(error_log or ""):
        path = m.group(2)
        if path and Path(path).exists():
            return path

    # classic "File "...", line N" pattern
    for m in _FILE_LINE_RE.finditer(error_log or ""):
        path = m.group(1)
        if path and "executor" in path and Path(path).exists():
            return path

    return None


# ---------------------------
# Repo analyzer context
# ---------------------------

def gather_related_context(error_log: str, max_files: int = 6, max_chars_per_file: int = 20000) -> Dict[str, str]:
    """
    Ask repo_analyzer for a map; include files whose symbols appear in the error log.
    Limit total size to keep prompts manageable.
    """
    analysis = repo_analyzer.analyze_repo("executor")
    related: Dict[str, str] = {}
    mentions = set()

    # naive symbol scrape from the error log
    for path, info in analysis.items():
        for sym in (info.get("functions", []) or []) + (info.get("classes", []) or []):
            if sym and sym in (error_log or ""):
                mentions.add(path)

    # If nothing matched, include top-level changed or key files heuristically
    candidates = list(mentions) or [
        p for p in analysis.keys()
        if ("openai_client.py" in p or "conversation_manager.py" in p or "builder.py" in p or "extend_plugin.py" in p)
    ][:max_files]

    for p in candidates[:max_files]:
        try:
            text = Path(p).read_text(encoding="utf-8")
            related[p] = text[:max_chars_per_file]
        except Exception:
            continue

    return related


# ---------------------------
# Patch request
# ---------------------------

def request_general_patch(
    failing_file_path: str,
    failing_file_code: str,
    error_log: str,
    related_files: Dict[str, str],
    system_hint: str = (
        "You are a precise software patcher. Patch ONLY the failing file to fix the described error; "
        "do not remove working functionality. Return the FULL corrected file content; no diff; no explanations."
    ),
    model: str = None,
) -> str:
    """
    Ask OpenAI for a patch for a specific file; return full corrected file text.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing; cannot perform self-repair")

    client = OpenAI(api_key=OPENAI_API_KEY)
    model = model or os.environ.get("CORTEX_REPAIR_MODEL", "gpt-4o-mini")

    # Limit related context to keep prompt size sane
    related_blob = ""
    if related_files:
        chunks = []
        for p, code in related_files.items():
            chunks.append(f"### Related file: {p}\n{code}")
        related_blob = "\n\n".join(chunks)

    prompt = f"""
I have a failing Python file that needs to be repaired.

Failing file path:
{failing_file_path}

Current failing file code:
{failing_file_code}

Error log (pytest/runtime traceback):
{error_log}

{('Additional related files and their contents:\n' + related_blob) if related_blob else ''}

Instructions:
- Fix ONLY {failing_file_path}.
- Maintain existing APIs and imports unless the error shows they must change.
- Keep working functions intact.
- Return ONLY the FULL corrected file content (no backticks, no diff, no commentary).
"""

    resp = client.responses.create(
        model=model,
        instructions=system_hint,
        input=prompt,
        store=False,
    )
    out_text = getattr(resp, "output_text", None) or ""
    return out_text.strip()


# ---------------------------
# Atomic writes
# ---------------------------

def write_file_atomic(path: str, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp, str(p))


# ---------------------------
# Public: attempt_self_repair
# ---------------------------

def attempt_self_repair(error: Dict[str, Any]) -> Dict[str, Any]:
    """
    Top-level self-repair:
    - Parse error
    - Identify failing file
    - Collect related files
    - Ask for a patch
    - Write, re-test, and return result
    """
    # Collect context
    error_log = error.get("message") or error.get("traceback") or ""
    # Try a quick pytest to get more detailed traceback if not provided
    if not error_log:
        ok, out = run_pytest()
        if not ok:
            error_log = out

    target = guess_failing_file(error_log) or ""
    if not target:
        # could not identify; try common files if import error
        if _IMPORT_ERR_RE.search(error_log or ""):
            # choose the most likely importing file
            for p in ("executor/connectors/openai_client.py",):
                if Path(p).exists():
                    target = p
                    break

    if not target:
        return {"status": "error", "reason": "no_target_file", "details": error_log}

    try:
        failing_code = Path(target).read_text(encoding="utf-8")
    except Exception as e:
        return {"status": "error", "reason": "read_failed", "file": target, "err": str(e)}

    related = gather_related_context(error_log)

    # Ask for patch
    try:
        patched = request_general_patch(
            failing_file_path=target,
            failing_file_code=failing_code,
            error_log=error_log,
            related_files=related,
        )
    except OpenAIError as e:
        return {"status": "error", "reason": "patch_api_error", "err": str(e), "file": target}
    except Exception as e:
        return {"status": "error", "reason": "patch_other_error", "err": str(e), "file": target}

    if not patched.strip():
        return {"status": "error", "reason": "empty_patch", "file": target}

    # Write patch
    try:
        write_file_atomic(target, patched)
    except Exception as e:
        return {"status": "error", "reason": "write_failed", "file": target, "err": str(e)}

    # Re-run tests
    ok, out = run_pytest()
    return {
        "status": "ok" if ok else "error",
        "file": target,
        "pytest_output": out,
    }
