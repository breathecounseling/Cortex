"""
executor/utils/goal_resume.py
-----------------------------
Phase 2.13b — Goal Resume Snapshot Helper

Provides a conversational summary of recent turns related to the active goal.

Used when resuming after a drift nudge:
- recalls the last N turns tied to the goal's topic
- generates a short natural-language summary for Echo to reorient itself

Dependencies:
  - executor/utils/goals.py
  - executor/utils/turn_memory.py
"""

from __future__ import annotations
import re, time
from typing import List, Dict, Optional
from executor.utils.turn_memory import get_recent_turns
from executor.utils.goals import get_most_recent_open

def summarize_goal_context(session_id: str, limit: int = 10) -> Optional[Dict[str, str]]:
    """
    Fetches the last N turns related to the most recent open goal.
    Returns a dict with `title`, `summary`, and `excerpt` for reorientation.
    """
    goal = get_most_recent_open(session_id)
    if not goal:
        print("[GoalResume] No open goal found.")
        return None

    topic = (goal.get("topic") or "").lower()
    title = goal.get("title", "Unnamed goal")

    turns = get_recent_turns(session_id, limit=limit)
    if not turns:
        print("[GoalResume] No turn history.")
        return {"title": title, "summary": "", "excerpt": ""}

    # Filter turns that reference the goal topic
    related = []
    for t in turns:
        text = t.get("content", "").lower()
        if topic and topic in text:
            related.append(t)
    if not related:
        related = turns[-3:]  # fallback: last few turns

    # Generate a brief natural summary
    summary_lines = []
    for t in related:
        role = t.get("role", "")
        content = re.sub(r"[\r\n]+", " ", t.get("content", "")).strip()
        content = content[:180] + ("..." if len(content) > 180 else "")
        if role == "user":
            summary_lines.append(f"User said: {content}")
        else:
            summary_lines.append(f"Echo replied: {content}")

    excerpt = "\n".join(summary_lines[-5:])
    summary = f"Recent discussion on “{title}”:\n{excerpt}"

    print(f"[GoalResume] Built summary for {title}")
    return {
        "title": title,
        "summary": summary,
        "excerpt": excerpt
    }


def build_resume_prompt(session_id: str) -> Optional[str]:
    """
    Returns a conversation-ready message for Echo to say when resuming a goal.
    """
    snap = summarize_goal_context(session_id)
    if not snap:
        return None
    title = snap["title"]
    excerpt = snap["excerpt"]

    prompt = (
        f"Let's get back to your goal: “{title}”. "
        "Here’s a quick recap of where we left off:\n"
        f"{excerpt}\n\n"
        "Where would you like to pick up from here?"
    )
    return prompt