"""
executor/core/semantic_parser.py
--------------------------------
Phase 2.11.1 — deterministic semantic parser (with tracing)

- Clause splitting for multi-intent messages
- Explicit regex coverage for queries, fact updates, preferences
- Improved trip detection ("heading to X", "going to X")
- Lightweight tracing you can enable with SEM_TRACE = True
"""

from __future__ import annotations
import re
from typing import List, Dict, Any

from executor.utils import memory_graph as gmem
from executor.utils.sanitizer import sanitize_value


# ============================================================
# Tracing (set to True to see detailed parser logs)
# ============================================================
SEM_TRACE = False

def trace(*args):
    if SEM_TRACE:
        try:
            print("[SemanticTrace]", *args)
        except Exception:
            pass


# ============================================================
# Clause splitter
# ============================================================
_CLAUSE_SPLIT_RX = re.compile(
    r"\s*(?:,|;|\bbut\b|\band then\b|\bthen\b|\bhowever\b|\band\s+(?:my|i'?m|i\s+am)\b)\s*",
    re.I,
)


# ============================================================
# Helper regexes
# ============================================================

# Canonical "what's my X"
RX_WHATS_MY = re.compile(r"(?i)\b(what('?s| is)\s+my)\s+(?P<key>.+?)\??$")

# Location questions
RX_WHERE_AM_I       = re.compile(r"(?i)\bwhere\s+am\s+i(\s+now)?\??$")
RX_WHERE_DO_I_LIVE  = re.compile(r"(?i)\bwhere\s+do\s+i\s+live\??$")
RX_WHERE_AM_I_GOING = re.compile(r"(?i)\b(where\s+am\s+i\s+going|trip\s+destination|where\s+is\s+my\s+trip)\??$")

# Location updates
RX_LIVE_IN = re.compile(r"(?i)\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>.+)$")
RX_IM_IN   = re.compile(r"(?i)\b(i'?m|i\s+am)\s+(?:currently\s+)?(?:in|at|staying\s+in|visiting)\s+(?P<city>.+)$")
RX_TRIP_TO = re.compile(
    r"(?i)\b(?:(?:i'?m\s+)?(?:going|heading)\s+to|trip\s+to|plan\s+(?:a\s+)?trip\s+to)\s+(?P<city>[\w\s,]+)$"
)

# Fact updates
RX_MY_FAVORITE = re.compile(r"(?i)\b(?:my|your|our|the)?\s*favorite\s+(?P<key>[\w\s]+?)\s+(?:is|=|'s)\s+(?P<val>.+)$")
RX_CHANGE_MY   = re.compile(r"(?i)\bchange\s+my\s+(?P<key>.+?)\s+to\s+(?P<val>.+)$")

# Preferences / sentiments
RX_I_LIKE    = re.compile(r"(?i)\b(i\s+(?:really\s+)?(?:like|love|adore|enjoy|am\s+into)\s+)(?P<item>.+)$")
RX_I_DISLIKE = re.compile(r"(?i)\b(i\s+(?:don'?t\s+like|dislike|hate|can'?t\s+stand)\s+)(?P<item>.+)$")

# Negation & reflective
RX_NEGATION    = re.compile(r"(?i)^(?:no[, ]*|actually[, ]*)?\s*not\s+(?P<val>.+)$")
RX_REFLECTIVE  = re.compile(r"(?i)\b(why|how\s+come|what\s+makes|what\s+causes)\b.*\b(i|me|my)\b")


# ============================================================
# Intent factory
# ============================================================
def _mk(intent: str, domain: str | None, key: str | None, value: str | None,
        confidence: float, scope: str | None = None,
        polarity: int | None = None, tone: str | None = None,
        intimacy: int = 0) -> Dict[str, Any]:
    return {
        "intent": intent,
        "domain": domain,
        "key": gmem.canonicalize_key(key) if key else None,
        "value": sanitize_value(value) if value else None,
        "confidence": float(confidence),
        "scope": scope,
        "polarity": polarity,
        "tone": tone,
        "intimacy": int(intimacy),
    }


# ============================================================
# Single clause parsing
# ============================================================
def _parse_single_clause(t: str, intimacy_level: int) -> List[Dict[str, Any]]:
    intents: List[Dict[str, Any]] = []
    tt = (t or "").strip()
    if not tt:
        return intents

    # Reflective
    if RX_REFLECTIVE.search(tt):
        trace("reflective.question:", tt)
        intents.append(_mk("reflective.question", None, None, None, 0.9, tone="reflective", intimacy=2))

    # Canonical questions
    m = RX_WHATS_MY.search(tt)
    if m:
        key = m.group("key").strip()
        dom = gmem.detect_domain_from_key(key)
        trace("fact.query:", key, "→", dom)
        intents.append(_mk("fact.query", dom, key, None, 0.85))

    if RX_WHERE_AM_I_GOING.search(tt):
        trace("location.query: trip")
        intents.append(_mk("location.query", "location", "trip", None, 0.9, scope="trip"))

    if RX_WHERE_AM_I.search(tt):
        trace("location.query: current")
        intents.append(_mk("location.query", "location", "current", None, 0.9, scope="current"))

    if RX_WHERE_DO_I_LIVE.search(tt):
        trace("location.query: home")
        intents.append(_mk("location.query", "location", "home", None, 0.9, scope="home"))

    # Location updates
    m = RX_LIVE_IN.search(tt)
    if m:
        city = m.group("city").strip()
        trace("location.update: home →", city)
        intents.append(_mk("location.update", "location", "home", city, 0.95, scope="home"))

    m = RX_IM_IN.search(tt)
    if m:
        city = m.group("city").strip()
        trace("location.update: current →", city)
        intents.append(_mk("location.update", "location", "current", city, 0.95, scope="current"))

    m = RX_TRIP_TO.search(tt)
    if m:
        city = m.group("city").strip()
        trace("location.update: trip →", city)
        intents.append(_mk("location.update", "location", "trip", city, 0.95, scope="trip"))

    # Explicit fact updates
    m = RX_CHANGE_MY.search(tt)
    if m:
        key = m.group("key").strip()
        val = m.group("val").strip()
        dom = gmem.detect_domain_from_key(key)
        trace("fact.update:", key, "=", val, "→", dom)
        intents.append(_mk("fact.update", dom, key, val, 0.92))

    m = RX_MY_FAVORITE.search(tt)
    if m:
        raw_key = m.group("key").strip()
        key = f"favorite {raw_key}" if not raw_key.lower().startswith("favorite") else raw_key
        val = m.group("val").strip()
        dom = gmem.detect_domain_from_key(key)
        trace("fact.update (favorite):", key, "=", val, "→", dom)
        intents.append(_mk("fact.update", dom, key, val, 0.92))

    # Negation (handled in reasoner, we just flag)
    m = RX_NEGATION.search(tt)
    if m:
        val = m.group("val").strip()
        trace("negation:", val)
        intents.append(_mk("fact.update", None, None, f"not {val}", 0.5))

    # Preferences: positive
    m = RX_I_LIKE.search(tt)
    if m:
        item = m.group("item").strip().rstrip(".!?")
        dom = gmem.detect_domain_from_key(item)
        trace("preference.statement (+):", item, "→", dom)
        intents.append(_mk("preference.statement", dom, item, None, 0.9,
                           polarity=+1, tone="positive", intimacy=min(1, intimacy_level)))

    # Preferences: negative
    m = RX_I_DISLIKE.search(tt)
    if m:
        item = m.group("item").strip().rstrip(".!?")
        dom = gmem.detect_domain_from_key(item)
        trace("preference.statement (-):", item, "→", dom)
        intents.append(_mk("preference.statement", dom, item, None, 0.9,
                           polarity=-1, tone="negative", intimacy=min(1, intimacy_level)))

    # Topic intro
    if re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b", tt):
        trace("topic.intro:", tt)
        intents.append(_mk("smalltalk", None, None, None, 0.5, tone="neutral"))

    if not intents:
        trace("smalltalk:", tt)
        intents.append(_mk("smalltalk", None, None, None, 0.4, tone="neutral"))
    return intents


# ============================================================
# Public API
# ============================================================
def parse_message(text: str, intimacy_level: int = 0) -> List[Dict[str, Any]]:
    """
    Split message into clauses, parse each, and combine intents.
    """
    if not text or not text.strip():
        return [_mk("smalltalk", None, None, None, 0.3, tone="neutral")]

    clauses = [c.strip(" ,;.") for c in _CLAUSE_SPLIT_RX.split(text) if c and c.strip()]
    print(f"[ClauseSplit] {clauses}")  # keep this light; helps QA
    intents: List[Dict[str, Any]] = []
    for clause in clauses:
        intents.extend(_parse_single_clause(clause, intimacy_level))
    return intents