# executor/plugins/patcher_utils.py
from __future__ import annotations
import subprocess
import tempfile
from dataclasses import dataclass

@dataclass
class TestResult:
    success: bool
    report: str

class WorkingDir:
    def __init__(self, ci: bool = False):
        self.path = tempfile.mkdtemp(prefix="executor_edit_")
        self._ci = ci

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Keep artifacts for inspection; caller can clean up if desired.
        pass

    def commit_and_merge(self, message: str) -> bool:
        # Stub: wire into your real VCS if needed
        return True

def run_tests(*, workdir: str, select: list[str] | None = None) -> TestResult:
    cmd = ["pytest", "-q"]
    if select:
        cmd.extend(select)
    try:
        out = subprocess.check_output(cmd, cwd=workdir, stderr=subprocess.STDOUT, text=True)
        return TestResult(True, out)
    except subprocess.CalledProcessError as e:
        return TestResult(False, e.output)