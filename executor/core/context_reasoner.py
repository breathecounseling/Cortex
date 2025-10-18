"""
executor/core/context_reasoner.py
---------------------------------
Phase 2.16 — Intelligent project clarification & delegation options,
goal switching, deadlines, resume, drift nudges, tone styling, and temporal recall.
"""

from __future__ import annotations
import re, time
from typing import Dict, Any, Optional

from executor.utils.session_context import get_topic, set_topic, get_tone
from executor.utils.personality_adapter import style_response
from executor.utils.preference_graph import get_preferences
from executor.utils.goals import (
    create_goal, close_goal, get_most_recent_open, mark_topic_active,
    find_goal_by_title, set_deadline, update_goal, touch_goal, get_open_goals
)
from executor.utils.goal_resume import build_resume_prompt
from executor.utils.turn_memory import get_recent_turns

# --- config ---
NUDGE_SILENCE_S = 15 * 60  # set to 10 for fast testing
def _now() -> int: return int(time.time())

# --- simple deadline detector ---
RX_DEADLINE = re.compile(
    r"(?i)\b(?:by|before|on|due|until)\s+((?:next\s+)?(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year|\d{1,2}(?:st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{1,4})?)\b"
)


def _should_nudge(goal: Dict[str, Any], query: str) -> bool:
    q = (query or "").lower()
    if goal.get("topic") and goal["topic"].lower() in q:
        return False
    if goal.get("title") and goal["title"].lower() in q:
        return False
    return (_now() - int(goal["last_active"])) >= NUDGE_SILENCE_S


def _infer_deliverable_from_context(session_id: str, title: str) -> str | None:
    """
    If user didn't specify deliverable, infer one based on keywords and recent patterns:
    - If title mentions tracker/dashboard/app -> 'app_module'
    - If finance/analytics verbs OR user has 'analytics' preferences -> 'spreadsheet'
    """
    t = title.lower()
    if any(k in t for k in ("tracker", "dashboard", "app", "module", "ui", "interface")):
        return "app_module"
    # check open goals to bias toward current domain
    opens = get_open_goals(session_id or "default")
    joined = " ".join([g["title"].lower() for g in opens])
    if "analysis" in t or "projection" in t or "forecast" in t or "budget" in t:
        return "spreadsheet"
    if "analysis" in joined or "report" in joined:
        return "spreadsheet"
    # check preferences
    try:
        ui_likes = [p["item"] for p in get_preferences("ui", min_strength=0.0) if p["polarity"] > 0]  # type: ignore
        if ui_likes:
            return "app_module"
    except Exception:
        pass
    return None


def _build_smart_options(session_id: str, title: str, explicit: str | None) -> str:
    """
    Builds a concise, non-overwhelming suggestion with 1–2 options max, and a reason.
    """
    deliverable = explicit or _infer_deliverable_from_context(session_id, title)
    # default reasons
    if deliverable == "app_module":
        reason = "it gives you a reusable interface and can include live charts and timers"
        return f"Awesome — should I pass this to Prime for an app module? ({reason}) " \
               f"Or would you prefer to start with a simple spreadsheet first?"
    if deliverable == "spreadsheet":
        reason = "it’s the fastest way to get working numbers you can iterate on"
        return f"Great — a spreadsheet via Phalanx might be best since {reason}. " \
               f"Or would you rather start a small app module with Prime?"
    if deliverable == "document":
        reason = "you can outline the structure and requirements in one place"
        return f"We can draft a project document first (outline + requirements), or jump straight to Prime for an app module."
    # ambiguous → keep it light
    return "Should this be an app module (hand off to Prime), a spreadsheet/report (via Phalanx), or something else?"


def reason_about_context(intent: Dict[str, Any], query: str,
                         session_id: Optional[str] = None) -> Dict[str, Any]:
    # tone guard
    try:
        tone = get_tone(session_id) if session_id else "neutral"
    except Exception:
        tone = "neutral"

    q = (query or "").strip()

    # --- Goal creation ---
    if intent.get("intent") == "goal.create" and intent.get("value"):
        title = intent["value"]
        subtype = intent.get("subtype")  # "build"|"finish"
        explicit_deliv = intent.get("deliverable")  # may be None/app_module/spreadsheet/document

        topic = " ".join([w for w in re.sub(r"[^a-z0-9\s]", "", title.lower()).split()[:3]])
        gid = create_goal(session_id or "default", title=title, topic=topic)
        set_topic(session_id, topic)

        # Intelligent, non-boilerplate clarification
        suggestion = _build_smart_options(session_id or "default", title, explicit_deliv)
        reply = style_response(f"Created goal “{title}”. {suggestion}", tone)
        return {"intent": "goal.create", "reply": reply, "goal_id": gid, "topic": topic}

    # --- Goal close ---
    if intent.get("intent") == "goal.close":
        recent = get_most_recent_open(session_id or "default")
        if recent:
            close_goal(recent["id"], note="Closed by user")
            reply = style_response(f"Great job — I’ve marked “{recent['title']}” as complete.", tone)
        else:
            reply = style_response("I don’t see any open goal to close.", tone)
        return {"intent": "goal.close", "reply": reply}

    # --- Goal switch ---
    m_switch = re.search(r"(?i)\b(focus on|switch to|work on|prioritize)\s+(?P<goal>.+)$", q)
    if m_switch:
        target = m_switch.group("goal").strip(" .!?")
        candidate = find_goal_by_title(session_id or "default", target)
        if candidate:
            recent = get_most_recent_open(session_id or "default")
            if recent and recent["id"] != candidate["id"]:
                update_goal(recent["id"], status="paused")
            update_goal(candidate["id"], status="open")
            touch_goal(candidate["id"])
            set_topic(session_id, candidate.get("topic") or candidate["title"])
            reply = style_response(
                f"Got it — focusing on “{candidate['title']}”. I’ve paused other work for now.",
                tone
            )
            return {"intent": "goal.switch", "reply": reply, "goal_id": candidate["id"]}
        else:
            reply = style_response(f"I don’t see a goal matching “{target}”. Want me to create it?", tone)
            return {"intent": "goal.switch", "reply": reply}

    # --- Deadline assignment ---
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
            return {"intent": "goal.deadline", "reply": reply, "goal_id": recent["id"], "deadline": deadline_str}

    # --- Resume detection ---
    if re.search(r"(?i)\b(resume|continue|pick\s+up|back\s+to)\b", q):
        resume = build_resume_prompt(session_id or "default")
        if resume:
            return {"intent": "goal.resume", "reply": resume}

    # --- Temporal recall ---
    if intent.get("intent") == "temporal.recall":
        turns = get_recent_turns(session_id or "default", limit=5)
        # turn_memory rows may use 'text' or 'content' depending on your implementation
        snippet = []
        for t in turns:
            msg = t.get("text") or t.get("content") or ""
            role = t.get("role", "user")
            msg = re.sub(r"[\r\n]+", " ", msg).strip()
            snippet.append(f"{role}: {msg[:160]}{'...' if len(msg) > 160 else ''}")
        summary = "; ".join(snippet) or "No prior messages found."
        reply = style_response(f"Here’s what we discussed recently: {summary}", tone)
        return {"intent": "temporal.recall", "reply": reply}

    # --- Drift nudge (stale) ---
    recent = get_most_recent_open(session_id or "default")
    if recent:
        current_topic = get_topic(session_id)
        if current_topic:
            mark_topic_active(session_id or "default", current_topic)
        if _should_nudge(recent, q):
            title = recent["title"]
            nudge = style_response(
                f"Quick check: we still have “{title}” open. Pick it back up, switch focus, or pause it?",
                tone
            )
            return {"intent": "nudge", "reply": nudge}

    # --- style passthrough if reply exists ---
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