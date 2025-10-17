"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.13 — Goal tracking & drift awareness (with tone persistence)
"""

from __future__ import annotations
import re, time
from typing import Dict, Any, Optional

from executor.utils.session_context import get_topic, set_topic, get_tone
from executor.utils.personality_adapter import style_response
from executor.utils.goals import (
    create_goal, close_goal, get_most_recent_open, mark_topic_active
)

NUDGE_SILENCE_S = 15 * 60
def _now() -> int: return int(time.time())

def _should_nudge(goal: Dict, query: str) -> bool:
    q = (query or "").lower()
    if goal["topic"] and goal["topic"].lower() in q: return False
    if goal["title"] and goal["title"].lower() in q: return False
    return (_now() - int(goal["last_active"])) >= NUDGE_SILENCE_S

def reason_about_context(intent: Dict[str,Any], query: str,
                         session_id: Optional[str]=None) -> Dict[str,Any]:
    tone = get_tone(session_id) if session_id else "neutral"
    q = (query or "").strip()

    # --- Goal create ---
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"]
        topic = " ".join([w for w in re.sub(r"[^a-z0-9\s]","",title.lower()).split()[:3]])
        gid = create_goal(session_id or "default", title=title, topic=topic)
        set_topic(session_id, topic)
        reply = style_response(
            f"Created goal “{title}”. I’ll track progress and remind you if we drift.",
            tone)
        return {"intent":"goal.create","reply":reply,"goal_id":gid,"topic":topic}

    # --- Goal close ---
    if intent.get("intent") == "goal.close":
        recent = get_most_recent_open(session_id or "default")
        if recent:
            close_goal(recent["id"], note="Closed by user")
            reply = style_response(f"Great job — I’ve marked “{recent['title']}” as complete.", tone)
        else:
            reply = style_response("I don’t see any open goal to close.", tone)
        return {"intent":"goal.close","reply":reply}

    # --- Drift nudge ---
    recent = get_most_recent_open(session_id or "default")
    if recent:
        current_topic = get_topic(session_id)
        if current_topic:
            mark_topic_active(session_id or "default", current_topic)
        if _should_nudge(recent, q):
            title = recent["title"]
            nudge = style_response(
                f"Quick check: we still have “{title}” open. Pick it back up or pause it?",
                tone)
            return {"intent":"nudge","reply":nudge}

    return intent

def build_context_block(query: str, session_id: Optional[str]=None) -> str:
    topic = get_topic(session_id)
    tone = get_tone(session_id) if session_id else "neutral"
    return f"Active tone: {tone}\nCurrent topic: {topic or 'general'}\nCurrent query: {query.strip()}"