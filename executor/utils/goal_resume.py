"""
executor/utils/goal_resume.py
-----------------------------
Phase 2.18 — Tone-aware resume prompt builder
"""

from __future__ import annotations
from typing import Optional
from executor.utils.goals import get_most_recent_open
from executor.utils.session_context import get_tone
from executor.utils.personality_adapter import style_response

def build_resume_prompt(session_id: str) -> Optional[str]:
    goal = get_most_recent_open(session_id)
    if not goal: return None
    tone = get_tone(session_id)
    title = goal["title"]
    base = f"Let’s pick up where we left off with “{title}”."
    hint = ""
    if goal.get("progress") and goal["progress"] > 0:
        hint = f" You were about {goal['progress']}% done last time."
    if goal.get("deadline"):
        hint += f" It’s due {goal['deadline']}."
    return style_response(base + hint, tone)