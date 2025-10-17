"""
executor/utils/scheduler.py
---------------------------
Phase 2.15 — Temporal awareness loop (goal nudges + NBA).

Usage patterns:
  - Background thread (start_scheduler) for dev
  - On-demand via /check_reminders endpoint in main.py (production-safe)
"""

from __future__ import annotations
import time, threading
from typing import List, Dict, Any
from executor.utils.goals import list_sessions, stale_open_goals, due_soon_goals
from executor.core.inference_engine import suggest_next_goal

REMINDER_STALE_SECS = 15 * 60   # 15m default; set lower for testing (e.g., 10)
DUE_SOON_DAYS = 3

def check_session(session_id: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []

    # 1) Stale goals → gentle drift nudge
    stale = stale_open_goals(session_id, older_than_s=REMINDER_STALE_SECS)
    for g in stale:
        messages.append({"type": "nudge",
                         "session_id": session_id,
                         "text": f"Quick check: we still have “{g['title']}” open. Pick it back up or pause it?"})

    # 2) Due soon goals → friendly reminder
    due = due_soon_goals(session_id, within_days=DUE_SOON_DAYS)
    for g in due:
        messages.append({"type": "deadline",
                         "session_id": session_id,
                         "text": f"Reminder: “{g['title']}” is due soon. Want to make progress now?"})

    # 3) Next Best Action suggestion (at most 1)
    nba = suggest_next_goal(session_id)
    if nba:
        messages.append({"type": "suggestion",
                         "session_id": session_id,
                         "text": nba["reply"]})

    return messages

def check_all_sessions() -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []
    for sid in list_sessions():
        msgs.extend(check_session(sid))
    return msgs

# Optional background loop for dev/local
_running = False
def start_scheduler(interval_s: int = 600):
    global _running
    if _running: return
    _running = True
    def _loop():
        while _running:
            try:
                msgs = check_all_sessions()
                for m in msgs:
                    print(f"[Scheduler] {m['type'].upper()} → {m['session_id']}: {m['text']}")
            except Exception as e:
                print("[SchedulerError]", e)
            time.sleep(interval_s)
    threading.Thread(target=_loop, daemon=True).start()

def stop_scheduler():
    global _running
    _running = False