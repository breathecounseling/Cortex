"""
executor/core/daemons.py
------------------------
Phase 2.17 — Background temporal watcher for goals and deadlines.
Checks for inactivity and due dates, then logs or queues nudges.
"""

from __future__ import annotations
import threading, time
from executor.utils.goals import list_sessions, stale_open_goals, due_soon_goals

CHECK_INTERVAL_S = 300       # run every 5 minutes
STALE_THRESHOLD_S = 1800     # 30 minutes inactivity
DUE_SOON_DAYS = 1            # upcoming within 1 day

def goal_watcher(interval_s: int = CHECK_INTERVAL_S) -> None:
    """Checks for stale or due-soon goals and logs notifications."""
    while True:
        try:
            sessions = list_sessions()
            if not sessions:
                time.sleep(interval_s)
                continue
            for sid in sessions:
                stale = stale_open_goals(sid, older_than_s=STALE_THRESHOLD_S)
                due = due_soon_goals(sid, within_days=DUE_SOON_DAYS)
                for g in stale:
                    print(f"[Daemon:Nudge] '{g['title']}' inactive for a while (session={sid}).")
                for g in due:
                    print(f"[Daemon:Deadline] '{g['title']}' due soon ({g['deadline']}) (session={sid}).")
        except Exception as e:
            print("[DaemonError]", e)
        time.sleep(interval_s)

def start_daemons() -> None:
    """Start background daemons for goal and deadline monitoring."""
    t = threading.Thread(target=goal_watcher, daemon=True)
    t.start()
    print("[Daemon] GoalWatcher started.")