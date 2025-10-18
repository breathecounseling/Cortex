"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.20 — safe clear/list goals, confirmations, tone/topic scoping, linkback preserved.
"""

from __future__ import annotations
import re, time
from typing import Dict, Any, Optional

from executor.utils.session_context import (
    get_topic, set_topic, get_tone, get_reminder_interval,
    set_pending, get_pending, clear_pending
)
from executor.utils.personality_adapter import style_response
from executor.utils.goals import (
    create_goal, close_goal, get_most_recent_open, mark_topic_active,
    find_goal_by_title, set_deadline, update_goal, touch_goal, get_open_goals,
    count_open_goals, clear_all_goals
)
from executor.utils.goal_resume import build_resume_prompt
from executor.utils.turn_memory import get_recent_turns

NUDGE_SILENCE_DEFAULT = 15 * 60
def _now() -> int: return int(time.time())

RX_DEADLINE = re.compile(
    r"(?i)\b(?:by|before|on|due|until)\s+((?:next\s+)?(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year|\d{1,2}(?:st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{1,4})?)\b"
)
RX_PRONOUN = re.compile(r"(?i)\b(it|that|this|the\s+project)\b")
RX_RESUME  = re.compile(r"(?i)\b(keep\s+working|resume|continue|pick\s+up)\b")
RX_COMPLETE= re.compile(r"(?i)\b(done|finished|complete|wrapped\s*up|that'?s\s*it|we'?re\s*good)\b")
RX_CONFIRM_MODULE = re.compile(r"(?i)\b(full\s+module|as\s+a\s+module|make\s+it\s+a\s+module|build\s+a\s+module)\b")

# list/clear synonyms
RX_LIST_GOALS  = re.compile(r"(?i)\b(list|show|what\s+are|tell\s+me)\s+(?:my\s+)?(?:current\s+)?(?:open\s+)?goals\b")
RX_CLEAR_GOALS = re.compile(r"(?i)\b(clear|erase|forget|close|delete)\s+all\s+(?:open\s+)?goals\b")
RX_YES         = re.compile(r"(?i)\b(yes|yep|yeah|confirm|do\s+it|sure)\b")
RX_NO          = re.compile(r"(?i)\b(no|nope|cancel|keep)\b")

def _resolve_pronouns(text: str, session_id: Optional[str]) -> str:
    if RX_PRONOUN.search(text or ""):
        topic = get_topic(session_id)
        if topic:
            return RX_PRONOUN.sub(topic, text)
    return text

def _recent_domain_guess(session_id: str) -> Optional[str]:
    turns = get_recent_turns(session_id or "default", limit=6)
    for t in reversed(turns):
        s = (t.get("text") or "").lower()
        if any(k in s for k in ("food","pizza","recipe","restaurant","chili","sushi")): return "food"
        if any(k in s for k in ("color","palette","hue","shade")): return "color"
        if any(k in s for k in ("layout","ui","interface","design")): return "ui"
    return None

def _should_nudge(goal: Dict[str, Any], query: str, session_id: Optional[str]) -> bool:
    q = (query or "").lower()
    if RX_RESUME.search(q) or "switch" in q or "pause" in q:
        return False
    if goal.get("topic") and goal["topic"].lower() in q:
        return False
    if goal.get("title") and goal["title"].lower() in q:
        return False
    interval = get_reminder_interval(session_id) if session_id else NUDGE_SILENCE_DEFAULT
    interval = interval or NUDGE_SILENCE_DEFAULT
    return (int(time.time()) - int(goal["last_active"])) >= int(interval)

def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    try: tone = get_tone(session_id) if session_id else "neutral"
    except Exception: tone = "neutral"

    q = _resolve_pronouns((query or "").strip(), session_id)

    # --- List open goals ---
    if RX_LIST_GOALS.search(q):
        opens = get_open_goals(session_id or "default")
        if not opens:
            return {"intent":"goal.list", "reply": style_response("You have no open goals right now.", tone)}
        titles = "; ".join([g["title"] for g in opens[:10]])
        more = "" if len(opens) <= 10 else f" (+{len(opens)-10} more)"
        return {"intent":"goal.list", "reply": style_response(f"Here are your open goals: {titles}{more}.", tone)}

    # --- Safe clear all open goals (confirmation) ---
    if RX_CLEAR_GOALS.search(q):
        n = count_open_goals(session_id or "default")
        if n == 0:
            return {"intent":"goal.clear_all", "reply": style_response("You have no open goals to clear.", tone)}
        set_pending(session_id or "default", {"action":"clear_goals","count":n,"ts":int(time.time())})
        return {"intent":"goal.clear_all.confirm",
                "reply": style_response(f"You have {n} open goals. Are you sure you want to clear them all?", tone)}

    # --- Confirmation follow-up (yes/no) ---
    pending = get_pending(session_id or "default")
    if pending and pending.get("action") == "clear_goals":
        if RX_YES.search(q):
            cleared = clear_all_goals(session_id or "default")
            clear_pending(session_id or "default")
            return {"intent":"goal.clear_all", "reply": style_response(f"Done — cleared {cleared} open goals.", tone)}
        if RX_NO.search(q):
            clear_pending(session_id or "default")
            return {"intent":"goal.clear_all", "reply": style_response("Okay — I’ll keep them as is.", tone)}
        # If neither yes nor no, repeat the prompt gently
        return {"intent":"goal.clear_all.confirm",
                "reply": style_response("Just to confirm — do you want me to clear all open goals?", tone)}

    # --- Goal creation ---
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"].strip(" .!?")
        topic = " ".join([w for w in re.sub(r"[^a-z0-9\s]", "", title.lower()).split()[:3]])
        gid = create_goal(session_id or "default", title=title, topic=topic)
        set_topic(session_id, topic)
        # intelligent prompt left to 2.19's reasoner flow—reply will be formed in main if needed
        return {"intent":"goal.create","reply": style_response(f"Created goal “{title}”.", tone), "goal_id":gid,"topic":topic}

    # --- Confirm deliverable (module) ---
    if intent.get("intent") == "goal.confirm_deliverable" or RX_CONFIRM_MODULE.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"], note="deliverable=app_module")
            return {"intent":"goal.confirm_deliverable",
                    "reply": style_response(f"Got it — we’ll scope “{recent['title']}” as an app module and hand it to Prime. Want to brainstorm features?", tone)}

    # --- Keep working / resume ---
    if intent.get("intent") == "goal.keep_working" or RX_RESUME.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"])
            resume = build_resume_prompt(session_id or "default") or f"Let’s continue “{recent['title']}”."
            return {"intent":"goal.resume","reply": style_response(resume, tone)}

    # --- Complete cue ---
    if intent.get("intent") == "goal.complete" or RX_COMPLETE.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            close_goal(recent["id"], note="Auto-closed via completion cue")
            return {"intent":"goal.close","reply": style_response(f"Nice work — I’ve marked “{recent['title']}” as complete.", tone)}

    # --- Deadline assignment ---
    m_dead = RX_DEADLINE.search(q)
    if m_dead:
        deadline_str = m_dead.group(1).strip()
        recent = get_most_recent_open(session_id or "default")
        if recent:
            set_deadline(recent["id"], deadline_str)
            return {"intent":"goal.deadline",
                    "reply": style_response(f"Noted — “{recent['title']}” is due {deadline_str}. I’ll keep an eye on that.", tone),
                    "goal_id": recent["id"], "deadline": deadline_str}

    # --- Linkback: one/two-word items become preferences if recent domain inferred ---
    if intent.get("intent") == "smalltalk" and len(q.split()) <= 3:
        turns = get_recent_turns(session_id or "default", limit=6)
        joined = " ".join([(t.get("text") or "").lower() for t in turns])
        inferred = "food" if any(k in joined for k in ("food","pizza","recipe","restaurant","chili","sushi")) else None
        if inferred and q:
            return {"intent":"preference.statement","domain":inferred,"key":q.strip(), "polarity": +1}

    # --- Drift nudge (respect per-session interval) ---
    recent = get_most_recent_open(session_id or "default")
    if recent:
        current_topic = get_topic(session_id)
        if current_topic:
            mark_topic_active(session_id or "default", current_topic)
        if _should_nudge(recent, q, session_id):
            return {"intent":"nudge",
                    "reply": style_response(f"Quick check: we still have “{recent['title']}” open. Pick it back up, switch focus, or pause it?", tone)}

    # style passthrough
    if intent.get("reply"):
        intent["reply"] = style_response(intent["reply"], tone)
    return intent