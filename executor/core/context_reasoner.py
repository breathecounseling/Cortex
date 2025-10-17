"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.15 — Goal switching, deadlines, resume, and drift nudges.
"""

from __future__ import annotations
import re, time
from typing import Dict, Any, Optional

from executor.utils.session_context import get_topic, set_topic, get_tone
from executor.utils.personality_adapter import style_response
from executor.utils.goals import (
    create_goal, close_goal, get_most_recent_open, mark_topic_active,
    find_goal_by_title, set_deadline, update_goal, touch_goal
)
from executor.utils.goal_resume import build_resume_prompt

NUDGE_SILENCE_S = 15
def _now() -> int: return int(time.time())

# --- deadline detector (simple, robust) ---
RX_DEADLINE = re.compile(
    r"(?i)\b(?:by|before|on|due|until)\s+((?:next\s+)?(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year|\d{1,2}(?:st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{1,4})?)\b"
)

def _should_nudge(goal: Dict[str,Any], query: str) -> bool:
    q = (query or "").lower()
    if goal.get("topic") and goal["topic"].lower() in q: return False
    if goal.get("title") and goal["title"].lower() in q: return False
    return (_now() - int(goal["last_active"])) >= NUDGE_SILENCE_S

def reason_about_context(intent: Dict[str,Any], query: str,
                         session_id: Optional[str]=None) -> Dict[str,Any]:
    tone = get_tone(session_id) if session_id else "neutral"
    q = (query or "").strip()

    # --- Goal creation (from parser) ---
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"]
        topic = " ".join([w for w in re.sub(r"[^a-z0-9\s]","",title.lower()).split()[:3]])
        gid = create_goal(session_id or "default", title=title, topic=topic)
        set_topic(session_id, topic)
        reply = style_response(f"Created goal “{title}”. I’ll track progress and remind you if we drift.", tone)
        return {"intent":"goal.create","reply":reply,"goal_id":gid,"topic":topic}

    # --- Goal close (from parser) ---
    if intent.get("intent") == "goal.close":
        recent = get_most_recent_open(session_id or "default")
        if recent:
            close_goal(recent["id"], note="Closed by user")
            reply = style_response(f"Great job — I’ve marked “{recent['title']}” as complete.", tone)
        else:
            reply = style_response("I don’t see any open goal to close.", tone)
        return {"intent":"goal.close","reply":reply}

    # --- Goal switch (natural language) ---
    m_switch = re.search(r"(?i)\b(focus on|switch to|work on|prioritize)\s+(?P<goal>.+)$", q)
    if m_switch:
        target = m_switch.group("goal").strip(" .!?")
        candidate = find_goal_by_title(session_id or "default", target)
        if candidate:
            # pause current recent if different
            recent = get_most_recent_open(session_id or "default")
            if recent and recent["id"] != candidate["id"]:
                update_goal(recent["id"], status="paused")
            # activate target
            update_goal(candidate["id"], status="open")
            touch_goal(candidate["id"])
            set_topic(session_id, candidate.get("topic") or candidate["title"])
            reply = style_response(
                f"Got it — focusing on “{candidate['title']}”. I’ve paused other work for now.",
                tone
            )
            return {"intent":"goal.switch","reply":reply,"goal_id":candidate["id"]}
        else:
            reply = style_response(f"I don’t see a goal matching “{target}”. Want me to create it?", tone)
            return {"intent":"goal.switch","reply":reply}

    # --- Deadline extraction and assignment ---
    m_dead = RX_DEADLINE.search(q)
    if m_dead:
        deadline_str = m_dead.group(1).strip()
        recent = get_most_recent_open(session_id or "default")
        if recent:
            set_deadline(recent["id"], deadline_str)
            reply = style_response(
                f"Noted — “{recent['title']}” is due {deadline_str}. I’ll keep an eye on that.",
                tone
            )
            return {"intent":"goal.deadline","reply":reply,"goal_id":recent["id"],"deadline":deadline_str}

    # --- Resume detection (user asks to continue) ---
    if re.search(r"(?i)\b(resume|continue|pick\s+up|back\s+to)\b", q):
        resume = build_resume_prompt(session_id or "default")
        if resume:
            return {"intent":"goal.resume","reply":resume}

    # --- Drift nudge when stale ---
    recent = get_most_recent_open(session_id or "default")
    if recent:
        current_topic = get_topic(session_id)
        if current_topic:
            mark_topic_active(session_id or "default", current_topic)
        if _should_nudge(recent, q):
            title = recent["title"]
            nudge = style_response(
                f"Quick check: we still have “{title}” open. Pick it back up or switch to something else?",
                tone
            )
            return {"intent":"nudge","reply":nudge}

    # passthrough
    return intent

def build_context_block(query: str, session_id: Optional[str]=None) -> str:
    topic = get_topic(session_id)
    tone = get_tone(session_id) if session_id else "neutral"
    return f"Active tone: {tone}\nCurrent topic: {topic or 'general'}\nCurrent query: {query.strip()}"