"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.21 — due-soon & overdue queries + existing 2.20 features.
"""

from __future__ import annotations
import re, time
from typing import Dict, Any, Optional

from executor.utils.session_context import (
    get_topic, get_tone, get_reminder_interval,
    set_pending, get_pending, clear_pending
)
from executor.utils.personality_adapter import style_response
from executor.utils.goals import (
    create_goal, close_goal, get_most_recent_open,
    find_goal_by_title, set_deadline, update_goal, touch_goal,
    get_open_goals, count_open_goals, clear_all_goals,
    due_soon_goals, overdue_goals, due_within_days
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

# due-soon / overdue queries
RX_DUE_SOON    = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+soon|due\s+soon|what\s+deadlines\s+are\s+coming\s+up)\b")
RX_DUE_TODAY   = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+today|due\s+today|today'?s\s+deadlines?)\b")
RX_DUE_TOMORROW= re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+tomorrow|due\s+tomorrow|tomorrow'?s\s+deadlines?)\b")
RX_DUE_WEEK    = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+this\s+week|due\s+this\s+week)\b")
RX_OVERDUE     = re.compile(r"(?i)\b(overdue|past\s+due|what'?s\s+late|late\s+tasks?)\b")

def _resolve_pronouns(text: str, session_id: Optional[str]) -> str:
    if RX_PRONOUN.search(text or ""):
        topic = get_topic(session_id)
        if topic:
            return RX_PRONOUN.sub(topic, text)
    return text

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

def _list_to_sentence(goals: list[Dict]) -> str:
    if not goals: return ""
    titles = [g["title"] + (f" (due {g.get('deadline')})" if g.get("deadline") else "") for g in goals[:10]]
    more = f" (+{len(goals)-10} more)" if len(goals) > 10 else ""
    return "; ".join(titles) + more

def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        tone = get_tone(session_id) if session_id else "neutral"
    except Exception:
        tone = "neutral"

    q = _resolve_pronouns((query or "").strip(), session_id)

    # --- List open goals ---
    if RX_LIST_GOALS.search(q):
        opens = get_open_goals(session_id or "default")
        if not opens:
            return {"intent":"goal.list", "reply": style_response("You have no open goals right now.", tone)}
        return {"intent":"goal.list", "reply": style_response(f"Here are your open goals: {_list_to_sentence(opens)}.", tone)}

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
        if re.search(r"(?i)\b(yes|yep|yeah|confirm|do\s+it|sure)\b", q):
            cleared = clear_all_goals(session_id or "default")
            clear_pending(session_id or "default")
            return {"intent":"goal.clear_all", "reply": style_response(f"Done — cleared {cleared} open goals.", tone)}
        if re.search(r"(?i)\b(no|nope|cancel|keep)\b", q):
            clear_pending(session_id or "default")
            return {"intent":"goal.clear_all", "reply": style_response("Okay — I’ll keep them as is.", tone)}
        return {"intent":"goal.clear_all.confirm",
                "reply": style_response("Just to confirm — do you want me to clear all open goals?", tone)}

    # --- Goal creation ---
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"].strip(" .!?")
        topic = " ".join([w for w in re.sub(r"[^a-z0-9\s]", "", title.lower()).split()[:3]])
        gid = create_goal(session_id or "default", title=title, topic=topic)
        return {"intent":"goal.create", "reply": style_response(f"Created goal “{title}”.", tone), "goal_id":gid, "topic":topic}

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

    # --- Due-soon / Overdue queries ---
    if RX_DUE_TODAY.search(q):
        items = due_within_days(session_id or "default", 0)
        msg = "Nothing due today." if not items else f"Due today: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_DUE_TOMORROW.search(q):
        items = due_within_days(session_id or "default", 1)
        # Filter out strictly today to keep "tomorrow" precise
        import datetime
        today = datetime.date.today()
        items = [g for g in items if (_parse_deadline_safe(g.get('deadline')) or today) and
                 ((_parse_deadline_safe(g.get('deadline')).date() - today).days == 1)]
        msg = "Nothing due tomorrow." if not items else f"Due tomorrow: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_DUE_WEEK.search(q) or RX_DUE_SOON.search(q):
        items = due_within_days(session_id or "default", 7 if RX_DUE_WEEK.search(q) else 3)
        msg = "Nothing coming due soon." if not items else f"Coming up: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_OVERDUE.search(q):
        items = overdue_goals(session_id or "default")
        msg = "No overdue items." if not items else f"Overdue: {_list_to_sentence(items)}."
        return {"intent":"goal.overdue","reply": style_response(msg, tone)}

    # --- Drift nudge ---
    recent = get_most_recent_open(session_id or "default")
    if recent and _should_nudge(recent, q, session_id):
        return {"intent":"nudge",
                "reply": style_response(f"Quick check: we still have “{recent['title']}” open. Pick it back up, switch focus, or pause it?", tone)}

    # --- Linkback (smalltalk → preference.statement) ---
    if intent.get("intent") == "smalltalk" and len(q.split()) <= 3:
        turns = get_recent_turns(session_id or "default", limit=6)
        joined = " ".join([(t.get("text") or "").lower() for t in turns])
        if any(k in joined for k in ("food","pizza","recipe","restaurant","chili","sushi")) and q:
            return {"intent":"preference.statement","domain":"food","key":q.strip(),"polarity":+1}

    if intent.get("reply"):
        intent["reply"] = style_response(intent["reply"], tone)
    return intent

# helper for "tomorrow" filter
def _parse_deadline_safe(d: Optional[str]):
    if not d: return None
    try:
        import dateutil.parser as dp
        return dp.parse(d, fuzzy=True)
    except Exception:
        return None

def build_context_block(query: str, session_id: Optional[str]=None) -> str:
    topic = get_topic(session_id)
    tone = get_tone(session_id) if session_id else "neutral"
    return f"Active tone: {tone}\nCurrent topic: {topic or 'general'}\nCurrent query: {query.strip()}"