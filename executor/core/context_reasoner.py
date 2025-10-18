"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.20.5 — finalized goal/date reasoning.
Fixes:
 - Proper “today” filter (no future matches)
 - Prevents fallback web search on “what is today”
 - Handles “this week” cleanly
 - Keeps nudge + deadline reasoning stable
"""

from __future__ import annotations
import re, time, datetime
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

# ----------------- Regex -----------------
RX_DEADLINE = re.compile(
    r"(?i)\b(?:by|before|on|due|until)\s+((?:next\s+)?"
    r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?)"
    r"(?:\s+\d{4})?)"
)

RX_CREATE_WITH_DEADLINE = re.compile(
    r"(?i)\bi\s+(?:want|need|plan|would\s+like|intend|have|had|needed)\s+to\s+"
    r"(?:build|create|make|develop|finish|complete|do|work\s+on)\s+"
    r"(?P<title>.+?)\s+(?:by|before|on|due|until)\s+(?P<deadline>.+)$"
)

RX_WHEN_IS_X_DUE = re.compile(
    r"(?i)\bwhen\s+(?:is|'s)\s+(?:my\s+)?(?P<title>.+?)\s+due\??$"
)
RX_WHEN_ARE_X_DUE = re.compile(
    r"(?i)\bwhen\s+(?:are)\s+(?:my\s+)?(?P<title>.+?)\s+due\??$"
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

# due/overdue queries
RX_DUE_SOON     = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+soon|due\s+soon|what\s+deadlines\s+are\s+coming\s+up)\b")
RX_DUE_TODAY    = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+today|due\s+today|today'?s\s+deadlines?)\b")
RX_DUE_TOMORROW = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+tomorrow|due\s+tomorrow|tomorrow'?s\s+deadlines?)\b")
RX_DUE_WEEK     = re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+this\s+week|due\s+this\s+week)\b")
RX_DUE_NEXT_WEEK= re.compile(r"(?i)\b(what(?:'s| is)?\s+due\s+next\s+week|due\s+next\s+week)\b")
RX_OVERDUE      = re.compile(r"(?i)\b(overdue|past\s+due|what'?s\s+late|late\s+tasks?)\b")
RX_WHAT_IS_TODAY= re.compile(r"(?i)\b(what('?s| is)\s+today)\b")

# ----------------- Helpers -----------------
def _normalize_typos(q: str) -> str:
    return re.sub(r"(?i)\bgirls\b", "goals", q)

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
    return (int(time.time()) - int(goal["last_active"])) >= int(interval or NUDGE_SILENCE_DEFAULT)

def _list_to_sentence(goals: list[Dict]) -> str:
    if not goals: return ""
    titles = [g["title"] + (f" (due {g.get('deadline')})" if g.get("deadline") else "") for g in goals[:10]]
    more = f" (+{len(goals)-10} more)" if len(goals) > 10 else ""
    return "; ".join(titles) + more

def _clean_title_for_deadline_phrase(title: str) -> str:
    return re.sub(r"(?i)\s+(?:by|before|on|due|until)\s+.+$", "", title).strip(" .!?")

# ----------------- Main -----------------
def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        tone = get_tone(session_id) if session_id else "neutral"
    except Exception:
        tone = "neutral"

    q = _normalize_typos(_resolve_pronouns((query or "").strip(), session_id))

    # --- What is today ---
    if RX_WHAT_IS_TODAY.search(q):
        today = datetime.date.today().strftime("%A, %B %d, %Y")
        return {"intent":"date.query",
                "reply": style_response(f"Today is {today}.", tone)}

    # --- List open goals ---
    if RX_LIST_GOALS.search(q):
        opens = get_open_goals(session_id or "default")
        if not opens:
            return {"intent":"goal.list", "reply": style_response("You have no open goals right now.", tone)}
        return {"intent":"goal.list", "reply": style_response(f"Here are your open goals: {_list_to_sentence(opens)}.", tone)}

    # --- Clear all goals confirmation flow ---
    if RX_CLEAR_GOALS.search(q):
        n = count_open_goals(session_id or "default")
        if n == 0:
            return {"intent":"goal.clear_all", "reply": style_response("You have no open goals to clear.", tone)}
        set_pending(session_id or "default", {"action":"clear_goals","count":n,"ts":int(time.time())})
        return {"intent":"goal.clear_all.confirm",
                "reply": style_response(f"You have {n} open goals. Are you sure you want to clear them all?", tone)}

    pending = get_pending(session_id or "default")
    if pending and pending.get("action") == "clear_goals":
        if RX_YES.search(q):
            cleared = clear_all_goals(session_id or "default")
            clear_pending(session_id or "default")
            return {"intent":"goal.clear_all", "reply": style_response(f"Done — cleared {cleared} open goals.", tone)}
        if RX_NO.search(q):
            clear_pending(session_id or "default")
            return {"intent":"goal.clear_all", "reply": style_response("Okay — I’ll keep them as is.", tone)}
        return {"intent":"goal.clear_all.confirm",
                "reply": style_response("Just to confirm — do you want me to clear all open goals?", tone)}

    # --- Inline create + deadline ---
    m_inline = RX_CREATE_WITH_DEADLINE.search(q)
    if m_inline:
        raw_title = m_inline.group("title").strip()
        deadline_str = m_inline.group("deadline").strip()
        clean_title = _clean_title_for_deadline_phrase(raw_title)
        found = find_goal_by_title(session_id or "default", clean_title)
        if found:
            set_deadline(found["id"], deadline_str)
            touch_goal(found["id"])
            return {"intent":"goal.deadline",
                    "reply": style_response(f"Noted — “{found['title']}” is due {deadline_str}. I’ll keep an eye on that.", tone),
                    "goal_id": found["id"], "deadline": deadline_str}
        else:
            gid = create_goal(session_id or "default", title=clean_title, topic=" ".join(clean_title.split()[:3]))
            set_deadline(gid, deadline_str)
            return {"intent":"goal.create",
                    "reply": style_response(f"Created goal “{clean_title}”. It’s due {deadline_str}.", tone),
                    "goal_id": gid, "deadline": deadline_str}

    # --- When is/are X due ---
    m_when = RX_WHEN_IS_X_DUE.search(q) or RX_WHEN_ARE_X_DUE.search(q)
    if m_when:
        title_q = m_when.group("title").strip()
        found = find_goal_by_title(session_id or "default", title_q)
        if found and found.get("deadline"):
            return {"intent":"goal.deadline.query",
                    "reply": style_response(f"“{found['title']}” is due {found['deadline']}.", tone)}
        if found and not found.get("deadline"):
            return {"intent":"goal.deadline.query",
                    "reply": style_response(f"“{found['title']}” doesn’t have a deadline yet. Want me to set one?", tone)}
        return {"intent":"goal.deadline.query",
                "reply": style_response(f"I couldn’t find an open goal matching “{title_q}”.", tone)}

    # --- Due/overdue queries ---
    if RX_DUE_TODAY.search(q):
        items = due_within_days(session_id or "default", 0)
        msg = "Nothing due today." if not items else f"Due today: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_DUE_TOMORROW.search(q):
        items = due_within_days(session_id or "default", 1)
        msg = "Nothing due tomorrow." if not items else f"Due tomorrow: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_DUE_WEEK.search(q) or RX_DUE_SOON.search(q):
        items = due_within_days(session_id or "default", 7)
        if not items:
            return {"intent":"goal.due_soon","reply": style_response("Nothing due this week.", tone)}
        msg = f"Coming up: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_DUE_NEXT_WEEK.search(q):
        items = due_within_days(session_id or "default", 14)
        msg = "Nothing due next week." if not items else f"Next week: {_list_to_sentence(items)}."
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

    if intent.get("reply"):
        intent["reply"] = style_response(intent["reply"], tone)
    return intent


def build_context_block(query: str, session_id: Optional[str]=None) -> str:
    topic = get_topic(session_id)
    tone = get_tone(session_id) if session_id else "neutral"
    return f"Active tone: {tone}\nCurrent topic: {topic or 'general'}\nCurrent query: {query.strip()}"