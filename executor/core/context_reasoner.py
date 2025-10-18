"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.20.3 — improved date capture, title-first deadline matching,
robust "when is X due", typo normalization, and all 2.20 features preserved.
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

# ----------------- Regex -----------------

# ✅ improved version — fully captures "October 1st", "1 October", etc.
RX_DEADLINE = re.compile(
    r"(?i)\b(?:by|before|on|due|until)\s+((?:next\s+)?"
    r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?)"
    r"(?:\s+\d{4})?)"
)

# create/update WITH inline deadline: "I want/need to build/create/finish X by Y"
RX_CREATE_WITH_DEADLINE = re.compile(
    r"(?i)\bi\s+(?:want|need|plan|would\s+like|intend|have|had|needed)\s+to\s+"
    r"(?:build|create|make|develop|finish|complete|do|work\s+on)\s+"
    r"(?P<title>.+?)\s+(?:by|before|on|due|until)\s+(?P<deadline>.+)$"
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

# "When is my X due?" / "When is X due?"
RX_WHEN_IS_X_DUE = re.compile(
    r"(?i)\bwhen\s+(?:is|'s)\s+(?:my\s+)?(?P<title>.+?)\s+due\??$"
)

# ----------------- Helpers -----------------
def _resolve_pronouns(text: str, session_id: Optional[str]) -> str:
    if RX_PRONOUN.search(text or ""):
        topic = get_topic(session_id)
        if topic:
            return RX_PRONOUN.sub(topic, text)
    return text

def _normalize_typos(q: str) -> str:
    # Common slip: "girls" -> "goals" in "overdue girls"
    return re.sub(r"(?i)\bgirls\b", "goals", q)

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
    # strip trailing inline deadline clause if present: "... by NEXT FRIDAY"
    return re.sub(r"(?i)\s+(?:by|before|on|due|until)\s+.+$", "", title).strip(" .!?")

# ----------------- Core -----------------
def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        tone = get_tone(session_id) if session_id else "neutral"
    except Exception:
        tone = "neutral"

    q = _normalize_typos(_resolve_pronouns((query or "").strip(), session_id))

    # --- List open goals ---
    if RX_LIST_GOALS.search(q):
        opens = get_open_goals(session_id or "default")
        if not opens:
            return {"intent":"goal.list", "reply": style_response("You have no open goals right now.", tone)}
        return {"intent":"goal.list", "reply": style_response(f"Here are your open goals: {_list_to_sentence(opens)}.", tone)}

    # --- Safe clear all open goals ---
    if RX_CLEAR_GOALS.search(q):
        n = count_open_goals(session_id or "default")
        if n == 0:
            return {"intent":"goal.clear_all", "reply": style_response("You have no open goals to clear.", tone)}
        set_pending(session_id or "default", {"action":"clear_goals","count":n,"ts":int(time.time())})
        return {"intent":"goal.clear_all.confirm",
                "reply": style_response(f"You have {n} open goals. Are you sure you want to clear them all?", tone)}

    # --- Confirmation follow-up ---
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

    # --- Create/update WITH inline deadline ---
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

    # --- "When is my X due?" / "When is X due?"
    m_when = RX_WHEN_IS_X_DUE.search(q)
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

    # --- Goal creation, resume, complete, or update ---
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"].strip(" .!?")
        gid = create_goal(session_id or "default", title=title, topic=" ".join(title.lower().split()[:3]))
        return {"intent":"goal.create","reply": style_response(f"Created goal “{title}”.", tone), "goal_id":gid, "topic":title}

    if intent.get("intent") == "goal.confirm_deliverable" or RX_CONFIRM_MODULE.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"], note="deliverable=app_module")
            return {"intent":"goal.confirm_deliverable",
                    "reply": style_response(f"Got it — we’ll scope “{recent['title']}” as an app module and hand it to Prime. Want to brainstorm features?", tone)}

    if intent.get("intent") == "goal.keep_working" or RX_RESUME.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            touch_goal(recent["id"])
            resume = build_resume_prompt(session_id or "default") or f"Let’s continue “{recent['title']}”."
            return {"intent":"goal.resume","reply": style_response(resume, tone)}

    if intent.get("intent") == "goal.complete" or RX_COMPLETE.search(q):
        recent = get_most_recent_open(session_id or "default")
        if recent:
            close_goal(recent["id"], note="Auto-closed via completion cue")
            return {"intent":"goal.close","reply": style_response(f"Nice work — I’ve marked “{recent['title']}” as complete.", tone)}

    m_dead = RX_DEADLINE.search(q)
    if m_dead:
        deadline_str = m_dead.group(1).strip()
        tmatch = re.search(r"(?i)(?:finish|complete|do|work\s+on|build|create|make|develop)\s+(?P<title>.+?)\s+(?:by|before|on|due|until)\s+", q)
        if tmatch:
            clean_title = _clean_title_for_deadline_phrase(tmatch.group("title").strip())
            found = find_goal_by_title(session_id or "default", clean_title)
            if found:
                set_deadline(found["id"], deadline_str)
                touch_goal(found["id"])
                return {"intent":"goal.deadline",
                        "reply": style_response(f"Noted — “{found['title']}” is due {deadline_str}. I’ll keep an eye on that.", tone),
                        "goal_id": found["id"], "deadline": deadline_str}
        recent = get_most_recent_open(session_id or "default")
        if recent:
            set_deadline(recent["id"], deadline_str)
            return {"intent":"goal.deadline",
                    "reply": style_response(f"Noted — “{recent['title']}” is due {deadline_str}. I’ll keep an eye on that.", tone),
                    "goal_id": recent["id"], "deadline": deadline_str}

    # --- Due/Overdue queries ---
    if RX_DUE_TODAY.search(q):
        items = due_within_days(session_id or "default", 0)
        msg = "Nothing due today." if not items else f"Due today: {_list_to_sentence(items)}."
        return {"intent":"goal.due_soon","reply": style_response(msg, tone)}
    if RX_DUE_TOMORROW.search(q):
        items = due_within_days(session_id or "default", 1)
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

    # --- Linkback smalltalk inference ---
    if intent.get("intent") == "smalltalk" and len(q.split()) <= 3:
        turns = get_recent_turns(session_id or "default", limit=6)
        joined = " ".join([(t.get("text") or "").lower() for t in turns])
        if any(k in joined for k in ("food","pizza","recipe","restaurant","chili","sushi")) and q:
            return {"intent":"preference.statement","domain":"food","key":q.strip(),"polarity":+1}

    if intent.get("reply"):
        intent["reply"] = style_response(intent["reply"], tone)
    return intent

def build_context_block(query: str, session_id: Optional[str]=None) -> str:
    topic = get_topic(session_id)
    tone = get_tone(session_id) if session_id else "neutral"
    return f"Active tone: {tone}\nCurrent topic: {topic or 'general'}\nCurrent query: {query.strip()}"