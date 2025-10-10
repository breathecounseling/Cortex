from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict
import subprocess
import shlex
import os

from executor.audit.logger import get_logger
from executor.self_healer.config import CFG
from executor.self_healer.parsers import parse_junit, parse_patches
from executor.self_healer.prompts import build_messages
from executor.utils.patcher_utils import write_patch
from executor.utils.memory import record_repair
from executor.connectors.openai_client import OpenAIClient

# ---------------------------------------------------------------------------
# Directive enforcement import
# ---------------------------------------------------------------------------
try:
    from executor.self_healer.check_directive import verify_all
except Exception as e:
    # Safe fallback if check_directive not yet present
    def verify_all() -> bool:
        print(f"[Supervisor] Warning: check_directive import failed ({e})")
        return False
# ---------------------------------------------------------------------------

logger = get_logger(__name__)


def _run_pytest_junit(junit_xml: Path, *extra_args: str) -> int:
    """Run pytest with JUnit XML output inside the configured repo root."""
    junit_xml.parent.mkdir(parents=True, exist_ok=True)
    args = ["pytest", f"--junitxml={junit_xml.as_posix()}", *CFG.pytest_args, *extra_args]
    cmd = " ".join(shlex.quote(a) for a in args)
    logger.info("Running tests", extra={"cmd": cmd})

    # Hermetic environment for the subprocess; run in the target repo root.
    env = os.environ.copy()
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=CFG.repo_root,
        env=env,
    )
    logger.debug(proc.stdout[-8000:])
    return proc.returncode


def _cluster_failures(summary) -> List[List[Dict[str, str]]]:
    """Group failures/errors by file for targeted prompts."""
    all_items = [*map(lambda f: f.__dict__, summary.failures + summary.errors)]
    clusters: Dict[str, List[Dict[str, str]]] = {}
    for item in all_items:
        key = item.get("file") or "<unknown>"
        clusters.setdefault(key, []).append(item)
    return list(clusters.values())


def _repo_outline(root: Path) -> str:
    """Generate a concise repo outline for LLM context."""
    lines: List[str] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if any(rel.startswith(x) for x in (".venv/", ".git/")):
            continue
        lines.append(rel)
    return "\n".join(lines)


def _git_commit(paths: List[Path], message: str) -> None:
    """Optionally commit applied patches."""
    try:
        subprocess.run(["git", "add", *[p.as_posix() for p in paths]], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
    except Exception as e:
        logger.warning(f"git commit failed: {e}")


@dataclass
class CycleResult:
    green: bool
    applied_files: List[str]
    failures_before: int
    failures_after: int


def run_self_healer(*pytest_extra: str) -> CycleResult:
    """Perform a single self-healing cycle."""
    junit_xml = (CFG.repo_root / CFG.junit_path).resolve()

    rc = _run_pytest_junit(junit_xml, *pytest_extra)
    summary = parse_junit(junit_xml)
    if rc == 0 and summary.failures_count == 0 and summary.errors_count == 0:
        logger.info("Test suite already green")
        return CycleResult(True, [], 0, 0)

    clusters = _cluster_failures(summary)
    outline = _repo_outline(CFG.repo_root)

    client = OpenAIClient()
    applied: List[Path] = []

    prompts_used = 0
    for cluster in clusters:
        if prompts_used >= CFG.max_prompts_per_cycle:
            break
        messages = build_messages(cluster, outline)
        reply = client.chat(messages, temperature=0)
        patches = parse_patches(reply)
        if not patches:
            logger.warning("No patches produced for cluster")
            continue
        for p in patches:
            target = (CFG.repo_root / p.path).resolve()
            write_patch(target, p.content, summary=f"auto patch for {p.path}")
            applied.append(target)
        prompts_used += 1

    if CFG.enable_git_commit and applied:
        _git_commit(applied, CFG.git_commit_message)

    rc2 = _run_pytest_junit(junit_xml, *pytest_extra)
    summary2 = parse_junit(junit_xml)

    record_repair(
        file="supervisor",
        error=f"failures_before={summary.failures_count}, after={summary2.failures_count}",
        fix_summary=f"applied {len(applied)} patches",
        success=summary2.failures_count == 0 and summary2.errors_count == 0,
    )

    return CycleResult(
        green=(rc2 == 0 and summary2.failures_count == 0 and summary2.errors_count == 0),
        applied_files=[p.as_posix() for p in applied],
        failures_before=summary.failures_count + summary.errors_count,
        failures_after=summary2.failures_count + summary2.errors_count,
    )


def main() -> int:
    """Run preflight verification, then healing cycles until tests pass."""
    logger.info("Self-healer supervisor starting directive verification.")
    try:
        if verify_all():
            logger.info("Directive verification passed — test suite already green.")
            return 0
    except Exception as e:
        logger.warning(f"Pre-healer verification error: {e}")

    # Proceed with normal healing if verification failed
    cycles = 0
    last_failures = None
    while cycles < CFG.max_cycles:
        res = run_self_healer()
        if res.green:
            logger.info("Suite is green — exiting")
            return 0
        if CFG.stop_on_no_progress:
            now = res.failures_after
            if last_failures is not None and now >= last_failures:
                logger.info(f"No progress after cycle {cycles}, stopping.")
                return 2
            last_failures = now
        cycles += 1
    logger.info("Reached max cycles without full success.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())