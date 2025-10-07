# executor/plugins/self_repair.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List
import os

@dataclass
class FileEdit:
    path: str
    content: str
    kind: str  # "code"|"test"|"doc"

"""
Self-repair module.
Provides hooks for automated patch attempts.
"""

def attempt_self_repair(error: dict) -> dict:
    """
    Placeholder self-repair implementation.
    Real logic would analyze the error and try a patch.
    For now, just return a no-op error result so tests can monkeypatch this.
    """
    return {"status": "error", "details": {"msg": "self_repair not implemented"}}

def apply_file_edits(edits: List[FileEdit], worktree: str) -> None:
    for e in edits:
        abs_path = os.path.join(worktree, e.path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(e.content)
