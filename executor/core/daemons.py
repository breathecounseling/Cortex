"""
executor/core/daemons.py
------------------------
Phase 2.20 — Background temporal watcher wrapping scheduler checks.
"""

from __future__ import annotations
import threading, time
from executor.utils.scheduler import check_all_sessions, CHECK_INTERVAL_S

def goal_watcher(interval_s: int = CHECK_INTERVAL_S) -> None:
    while True:
        try:
            msgs = check_all_sessions()
            for m in msgs:
                print(f"[Daemon:{m['type'].upper()}] {m['session_id']}: {m['text']}")
        except Exception as e:
            print("[DaemonError]", e)
        time.sleep(interval_s)

def start_daemons() -> None:
    t = threading.Thread(target=goal_watcher, daemon=True)
    t.start()
    print("[Daemon] GoalWatcher started.")