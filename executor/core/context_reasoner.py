"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.18c — pronoun-to-topic resolution, keep_working, confirm deliverable,
auto-complete, resume, deadlines, drift nudges, and tone styling.
"""

from __future__ import annotations
import re, time
from typing import Dict, Any, Optional

from executor.utils.session_context import get_topic, set_topic, get_tone
from executor.utils.personality_adapter import style_response
from executor.utils.goals import (
    create_goal, close_goal, get_most_recent_open, mark_topic_active,
    find_goal_by_title, set_deadline, update_goal, touch_goal, get_open_goals
)
from executor.utils.goal_resume import build_resume_prompt
from executor.utils.turn_memory import get_recent_turns

NUDGE_SILENCE_S = 15 * 60
def _now() -> int: return int(time.time())

RX_DEADLINE = re.compile(
    r"(?i)\b(?:by|before|on|due|until)\s+((?:next\s+)?(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year|\d{1,2}(?:st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{1,4})?)\b"
)
RX_PRONOUN = re.compile(r"(?i)\b(it|that|this|the\s+project)\b")
RX_RESUME  = re.compile(r"(?i)\b(keep\s+working|resume|continue|pick\s+up)\b")
RX_COMPLETE= re.compile(r"(?i)\b(done|finished|complete|wrapped\s*up|that'?s\s*it|we'?re\s*good)\b")
RX_CONFIRM_MODULE = re.compile(r"(?i)\b(full\s+module|as\s+a\s+module|make\s+it\s+a\s+module|build\s+a\s+module)\b")

def _should_nudge(goal: Dict[str, Any], query: str) -> bool:
    q = (query or "").lower()
    if RX_RESUME.search(q): return False    # user is explicitly resuming
    if "switch" in q or "pause" in q: return False
    if goal.get("topic") and goal["topic"].lower() in q: return False
    if goal.get("title") and goal["title"].lower() in q: return False
    return (_now() - int(goal["last_active"])) >= NUDGE_SILENCE_S

def _resolve_pronouns(text: str, session_id: Optional[str]) -> str:
    if RX_PRONOUN.search(text or ""):
        topic = get_topic(session_id)
        if topic:
            return RX_PRONOUN.sub(topic, text)
    return text

def _infer_deliverable_from_context(session_id: str, title: str) -> str | None:
    t = (title or "").lower()
    if any(k in t for k in ("tracker","dashboard","module","app","ui","interface")):
        return "app_module"
    opens = get_open_goals(session_id or "default")
    joined = " ".join([g["title"].lower() for g in opens])
    if any(k in t for k in ("projection","forecast","analysis","analytics","report","budget")) or \
       any(k in joined for k in ("analysis","report")):
        return "spreadsheet"
    return None

def _smart_options(session_id: str, title: str, explicit: Optional[str]) -> str:
    deliverable = explicit or _infer_deliverable_from_context(session_id, title)
    if deliverable == "app_module":
        reason = "it gives you a reusable interface and can include live charts and timers"
        return f"Should I pass this to Prime for an app module? ({reason}) Or start with a quick spreadsheet first?"
    if deliverable == "spreadsheet":
        reason = "it’s the fastest way to get working numbers you can iterate on"
        return f"A spreadsheet via Phalanx might be best since {reason}. Or would you rather start a small app module with Prime?"
    return "Should this be an app module (Prime), a spreadsheet/report (Phalanx), or something else?"

def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        tone = get_tone(session_id) if session_id else "neutral"
    except Exception:
        tone = "neutral"

    q = _resolve_pronouns((query or "").strip(), session_id)

    # 1) Goal create
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"].strip(" .!?")
        topic = " ".join([w for w in re.sub(r"[^a-z0-9\s]", "", title.lower()).split()[:3]])
        gid = create_goal(session_id or "default", title=title, topic=topic)
        set_topic(session_id, topic)
        suggestion = _smart_options(session_id or "default", title, intent.get("deliverable"))
        reply = style_response(f"Created goal “{title}”. {suggestion}", tone)
        return {"intent":"goal.create","reply":reply,"goal_id":gid,"topic":topic}

    # 2) Goal confirm deliverable (module)
    if intent.get("intent") == "goal.confirm_deliverable" or RX_CONFIRM_MODULE.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"], note="deliverable=app_module")
            reply = style_response(
                f"Got it — we’ll scope “{recent['title']}” as an app module and hand it to Prime. "
                "Do you want to brainstorm features first?",
                tone
            )
            return {"intent":"goal.confirm_deliverable","reply":reply}

    # 3) Keep working / Resume
    if intent.get("intent") == "goal.keep_working" or RX_RESUME.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"])
            resume = build_resume_prompt(session_id or "default") or f"Let’s continue “{recent['title']}”."
            reply = style_response(resume, tone)
            return {"intent":"goal.resume","reply":reply}

    # 4) Mark complete
    if intent.get("intent") == "goal.complete" or RX_COMPLETE.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            close_goal(recent["id"], note="Auto-closed via completion cue")
            reply = style_response(f"Nice work — I’ve marked “{recent['title']}” as complete.", tone)
            return {"intent":"goal.close","reply":reply}

    # 5) Deadline
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

    # 6) Resume keyword (fallback)
    if re.search(r"(?i)\b(back\s+to)\b", q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"])
            resume = build_resume_prompt(session_id or "default") or f"Let’s continue “{recent['title']}”."
            reply = style_response(resume, tone)
            return {"intent":"goal.resume","reply":reply}

    # 7) Drift nudge
    recent = get_most_recent_open(session_id or "default")
    if recent:
        current_topic = get_topic(session_id)
        if current_topic:
            mark_topic_active(session_id or "default", current_topic)
        if _should_nudge(recent, q):
            nudge = style_response(
                f"Quick check: we still have “{recent['title']}” open. Pick it back up, switch focus, or pause it?",
                tone
            )
            return {"intent":"nudge","reply":nudge}

    # style passthrough
    if intent.get("reply"):
        intent["reply"] = style_response(intent["reply"], tone)
    return intent

def build_context_block(query: str, session_id: Optional[str] = None) -> str:
    topic = get_topic(session_id)
    try:
        tone = get_tone(session_id) if session_id else "neutral"
    except Exception:
        tone = "neutral"
    return f"Active tone: {tone}\nCurrent topic: {topic or 'general'}\nCurrent query: {query.strip()}"