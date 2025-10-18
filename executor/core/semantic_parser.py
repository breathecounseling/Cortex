"""
executor/core/semantic_parser.py
--------------------------------
Phase 2.18 — Pronoun + Completion-aware intent parsing
"""

from __future__ import annotations
import re
from typing import List, Dict, Any
from executor.utils import memory_graph as gmem
from executor.utils.sanitizer import sanitize_value

# Clause splitter
_CLAUSE_SPLIT_RX = re.compile(
    r"\s*(?:,|;|\bbut\b|\band then\b|\bthen\b|\bhowever\b|\band\s+(?:my|i'?m|i\s+am)\b)\s*",
    re.I,
)

# Location & fact regexes
RX_WHATS_MY = re.compile(r"(?i)\bwhat('?s| is)\s+my\s+(?P<key>.+?)\??$")
RX_LIVE_IN  = re.compile(r"(?i)\bi\s+live\s+in\s+(?P<city>.+)$")
RX_IM_IN    = re.compile(r"(?i)\bi'?m\s+(?:in|at|staying\s+in)\s+(?P<city>.+)$")
RX_TRIP_TO  = re.compile(r"(?i)\b(?:going|heading|trip)\s+to\s+(?P<city>.+)$")

# Preferences
RX_I_LIKE    = re.compile(r"(?i)\bi\s+(?:really\s+)?(?:like|love|enjoy|am\s+into)\s+(?P<item>.+)$")
RX_I_DISLIKE = re.compile(r"(?i)\bi\s+(?:don'?t\s+like|dislike|hate|can'?t\s+stand)\s+(?P<item>.+)$")

# Goal creation & pronoun linkage
RX_GOAL_CREATE  = re.compile(r"(?i)\bi\s+(?:want|need|plan|hope|would\s+like)\s+to\s+(?P<action>build|make|create|develop|design)\s+(?P<thing>.+)$")
RX_PRONOUN_GOAL = re.compile(r"(?i)\b(?:it|that|this|the\s+project)\b")

# Completion / done detection
RX_DONE = re.compile(r"(?i)\b(?:done|finished|complete|wrapped\s+up|that'?s\s+it|we'?re\s+good)\b")

def _mk(intent: str, domain=None, key=None, value=None,
        confidence: float = 0.9, scope=None,
        polarity=None, tone=None, intimacy=0):
    return {
        "intent": intent, "domain": domain, "key": key,
        "value": value, "confidence": confidence,
        "scope": scope, "polarity": polarity,
        "tone": tone, "intimacy": intimacy
    }

def _parse_single_clause(t: str, intimacy_level: int) -> List[Dict[str, Any]]:
    intents: List[Dict[str, Any]] = []
    s = t.strip()

    # Goal create
    m = RX_GOAL_CREATE.search(s)
    if m:
        title = f"{m.group('action')} {m.group('thing')}".strip()
        intents.append(_mk("goal.create", "goal", "title", title, 0.95))
        return intents

    # Pronoun continuation (“it”, “that”) → goal.resume
    if RX_PRONOUN_GOAL.search(s) and re.search(r"\bwork|continue|resume|finish|complete\b", s, re.I):
        intents.append(_mk("goal.resume", "goal", None, None, 0.8))
        return intents

    # Completion markers
    if RX_DONE.search(s):
        intents.append(_mk("goal.complete", "goal", None, None, 0.9))
        return intents

    # Likes / dislikes
    for rx, pol in ((RX_I_LIKE, +1), (RX_I_DISLIKE, -1)):
        m = rx.search(s)
        if m:
            item = m.group("item").strip()
            intents.append(_mk("preference.statement",
                               gmem.detect_domain_from_key(item),
                               item, None, 0.9,
                               polarity=pol))
            return intents

    # Location facts
    for rx, key, scope in ((RX_LIVE_IN, "home", "home"), (RX_IM_IN, "current", "current"), (RX_TRIP_TO, "trip", "trip")):
        m = rx.search(s)
        if m:
            intents.append(_mk("location.update", "location", key, m.group("city").strip(), 0.95, scope=scope))
            return intents

    # What’s my …
    m = RX_WHATS_MY.search(s)
    if m:
        key = m.group("key").strip()
        intents.append(_mk("fact.query", gmem.detect_domain_from_key(key), key, None, 0.85))
        return intents

    # Default
    intents.append(_mk("smalltalk", None, None, None, 0.3))
    return intents

def parse_message(text: str, intimacy_level: int = 0) -> List[Dict[str, Any]]:
    clauses = [c.strip(" ,;.") for c in _CLAUSE_SPLIT_RX.split(text) if c.strip()]
    intents: List[Dict[str, Any]] = []
    for c in clauses:
        intents.extend(_parse_single_clause(c, intimacy_level))
    return intents