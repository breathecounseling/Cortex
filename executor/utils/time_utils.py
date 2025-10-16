"""
executor/utils/time_utils.py
----------------------------
Basic time helpers (epoch seconds, deltas, humanization).
"""

from __future__ import annotations
import time

def now_ts() -> int:
    return int(time.time())

def days_since(ts: int) -> int:
    if not ts:
        return 10**6
    return int((time.time() - ts) // 86400)

def within_last(ts: int, days: int) -> bool:
    if not ts:
        return False
    return (time.time() - ts) <= days * 86400

def humanize_delta(ts: int) -> str:
    if not ts:
        return "unknown"
    seconds = int(time.time() - ts)
    if seconds < 60: return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60: return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24: return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"