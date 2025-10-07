from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class SelfHealerConfig:
    """Configuration for the self-healing supervisor."""
    repo_root: Path = Path(os.getenv("CORTEX_REPO_ROOT", ".")).resolve()
    junit_path: Path = Path(os.getenv("CORTEX_JUNIT_XML", ".executor/junit-selfhealer.xml"))
    max_cycles: int = int(os.getenv("CORTEX_HEALER_MAX_CYCLES", 5))
    max_prompts_per_cycle: int = int(os.getenv("CORTEX_HEALER_MAX_PROMPTS", 3))
    stop_on_no_progress: bool = True
    enable_git_commit: bool = bool(int(os.getenv("CORTEX_HEALER_GIT_COMMIT", "1")))
    git_commit_message: str = os.getenv("CORTEX_HEALER_COMMIT_MSG", "self-healer: automated patch")
    pytest_args: tuple[str, ...] = tuple(
        (os.getenv("CORTEX_PYTEST_ARGS") or "-q").split()
    )


CFG = SelfHealerConfig()