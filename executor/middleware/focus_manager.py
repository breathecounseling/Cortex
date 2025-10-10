from __future__ import annotations
import re, time
from typing import Literal, Tuple
from executor.utils.plugin_memory import for_mode

BUSINESS = re.compile(r"\b(pnl|profit|revenue|expense|balance\s*sheet|kpi|invoice|billing)\b", re.I)
TRAVEL   = re.compile(r"\b(itinerary|hotel|drive|route|flight|vacation|trip|attraction|coffee)\b", re.I)
BUILD    = re.compile(r"\b(build|blueprint|contractor|permit|foundation|materials|estimate)\b", re.I)

Mode = Literal["business","travel","build","general"]

def detect_mode(text: str) -> Mode:
    if BUSINESS.search(text): return "business"
    if TRAVEL.search(text):   return "travel"
    if BUILD.search(text):    return "build"
    return "general"

def switch_if_needed(text: str, current_mode: Mode | None) -> Tuple[Mode, str]:
    nm = detect_mode(text or "")
    pm = for_mode(nm)
    summary = pm.summarize(limit=5)
    st = pm.load_state(); st["last_switch_ts"] = int(time.time()); pm.save_state(st)
    return nm, summary