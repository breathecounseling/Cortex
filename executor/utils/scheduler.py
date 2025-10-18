"""
executor/utils/scheduler.py
---------------------------
Phase 2.20 — Debounced nudges + due-soon reminders; returns message dicts for polling.
"""

from __future__ import annotations
import time
from typing import List, Dict, Any

from executor.utils.goals import list_sessions, stale_open_goals, due_soon_goals
from executor.utils.session_context import get_reminder_interval

REMINDER_STALE_SECS_DEFAULT = 15 * 60   # Default: 15 minutes
DUE_SOON_DAYS = 3
CHECK_INTERVAL_S = 60  # used by daemon; public API doesn't sleep

# Debounce memory (in-process)
_last_nudge_ts: dict[tuple[str, int], float] = {}  # (session_id, goal_id) -> ts


def _debounced(session_id: str, goal_id: int, cooldown_s: int = 300) -> bool:
    """Return True if we should send a nudge (i.e., not within cooldown)."""
    key = (session_id, int(goal_id))
    now = time.time()
    last = _last_nudge_ts.get(key, 0)
    if now - last >= cooldown_s:
        _last_nudge_ts[key] = now
        return True
    return False


def check_session(session_id: str) -> List[Dict[str, Any]]:
    """Run all reminder checks for a session."""
    msgs: List[Dict[str, Any]] = []
    interval = get_reminder_interval(session_id) or REMINDER_STALE_SECS_DEFAULT

    # 1) Stale goals → debounced nudge
    for g in stale_open_goals(session_id, older_than_s=int(interval)):
        try:
            gid = int(g.get("id", 0))
            title = g.get("title", "an unnamed goal")
            if not gid:
                continue
            if _debounced(session_id, gid, cooldown_s=300):
                msgs.append({
                    "type": "nudge",
                    "session_id": session_id,
                    "text": f"Quick check: we still have “{title}” open. Pick it back up or pause it?",
                    "goal_id": gid
                })
        except Exception as e:
            print(f"[Scheduler:NudgeError] {e}")
            continue

    # 2) Due soon → reminder (debounced)
    for g in due_soon_goals(session_id, within_days=DUE_SOON_DAYS):
        try:
            gid = int(g.get("id", 0))
            title = g.get("title", "an unnamed goal")
            deadline = g.get("deadline", "unspecified")
            if not gid:
                continue
            if _debounced(session_id, gid, cooldown_s=3600):
                msgs.append({
                    "type": "deadline",
                    "session_id": session_id,
                    "text": f"Reminder: “{title}” is due soon ({deadline}). Want to review or adjust?",
                    "goal_id": gid
                })
        except Exception as e:
            print(f"[Scheduler:DeadlineError] {e}")
            continue

    return msgs


def check_all_sessions() -> List[Dict[str, Any]]:
    """Run scheduler checks across all active sessions."""
    out: List[Dict[str, Any]] = []
    for sid in list_sessions():
        try:
            out.extend(check_session(sid))
        except Exception as e:
            print(f"[Scheduler:SessionError] {sid}: {e}")
            continue
    return out