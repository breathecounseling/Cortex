"""
executor/core/semantic_parser.py
--------------------------------
Phase 2.10a.3: Semantic parser for Echo

- Pre-splits multi-clause messages (handles "X, but Y", "and my …")
- Normalizes clauses before parsing
- Accumulates multiple intents per message
- Detects reflective / therapy-adjacent questions (consent gate)
- Safe deterministic regex + sanitizer; GPT-backed enrichment can plug in later.
"""

from __future__ import annotations
import re
from typing import List, Dict, Any

from executor.utils import memory_graph as gmem
from executor.utils.sanitizer import sanitize_value


# ---------- Clause splitter (pre-parse) ----------
# Added "and my" / "and i'm" / "and i am" boundaries for multi-intent sentences.
_CLAUSE_SPLIT_RX = re.compile(
    r"\s*(?:,|;|\bbut\b|\band then\b|\bthen\b|\bhowever\b|\band\s+(?:my|i'?m|i\s+am)\b)\s*",
    re.I,
)


# ---------- Helper regexes ----------
RX_WHATS_MY = re.compile(r"(?i)\b(what('?s| is)\s+my)\s+(?P<key>.+?)\??$")
RX_WHERE_AM_I = re.compile(r"(?i)\bwhere\s+am\s+i(\s+now)?\??$")
RX_WHERE_DO_I_LIVE = re.compile(r"(?i)\bwhere\s+do\s+i\s+live\??$")
RX_WHERE_AM_I_GOING = re.compile(r"(?i)\b(where\s+am\s+i\s+going|trip\s+destination|where\s+is\s+my\s+trip)\??$")

# location updates
RX_LIVE_IN = re.compile(r"(?i)\b(i\s+live\s+in|my\s+home\s+is\s+in)\s+(?P<city>.+)$")
RX_IM_IN = re.compile(r"(?i)\b(i'?m|i\s+am)\s+(?:currently\s+)?(?:in|at|staying\s+in|visiting)\s+(?P<city>.+)$")
RX_TRIP_TO = re.compile(r"(?i)\b(i'?m\s+(?:going|heading)\s+to|trip\s+to|i'?m\s+planning\s+(?:a\s+)?trip\s+to)\s+(?P<city>.+)$")

# fact updates
RX_MY_FAVORITE = re.compile(r"(?i)\bmy\s+(?P<key>.+?)\s+(?:is|=|'s)\s+(?P<val>.+)$")
RX_CHANGE_MY = re.compile(r"(?i)\bchange\s+my\s+(?P<key>.+?)\s+to\s+(?P<val>.+)$")

# preferences / sentiments
RX_I_LIKE = re.compile(r"(?i)\b(i\s+(?:really\s+)?(?:like|love|enjoy|am\s+into)\s+)(?P<item>.+)$")
RX_I_DISLIKE = re.compile(r"(?i)\b(i\s+(?:don'?t\s+like|dislike|hate|can'?t\s+stand)\s+)(?P<item>.+)$")

# negation for follow-up handling (kept in reasoner)
RX_NEGATION = re.compile(r"(?i)^(?:no[, ]*|actually[, ]*)?\s*not\s+(?P<val>.+)$")

# reflective questions (to hit consent gate)
RX_REFLECTIVE = re.compile(r"(?i)\b(why|how\s+come|what\s+makes|what\s+causes)\b.*\b(i|me|my)\b")


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


def _parse_single_clause(t: str, intimacy_level: int) -> List[Dict[str, Any]]:
    """Parse a single clause; may return multiple intents for that clause."""
    intents: List[Dict[str, Any]] = []
    tt = t.strip()
    if not tt:
        return intents

    # Reflective / therapy-adjacent (hits consent gate)
    if RX_REFLECTIVE.search(tt):
        intents.append(_mk("reflective.question", None, None, None, 0.9, tone="reflective", intimacy=2))

    # Canonical questions
    m = RX_WHATS_MY.search(tt)
    if m:
        key = m.group("key").strip()
        intents.append(_mk("fact.query", gmem.detect_domain_from_key(key), key, None, 0.85))

    if RX_WHERE_AM_I_GOING.search(tt):
        intents.append(_mk("location.query", "location", "trip", None, 0.9, scope="trip"))

    if RX_WHERE_AM_I.search(tt):
        intents.append(_mk("location.query", "location", "current", None, 0.9, scope="current"))

    if RX_WHERE_DO_I_LIVE.search(tt):
        intents.append(_mk("location.query", "location", "home", None, 0.9, scope="home"))

    # Location updates
    m = RX_LIVE_IN.search(tt)
    if m:
        intents.append(_mk("location.update", "location", "home", m.group("city").strip(), 0.95, scope="home"))

    m = RX_IM_IN.search(tt)
    if m:
        intents.append(_mk("location.update", "location", "current", m.group("city").strip(), 0.95, scope="current"))

    m = RX_TRIP_TO.search(tt)
    if m:
        intents.append(_mk("location.update", "location", "trip", m.group("city").strip(), 0.95, scope="trip"))

    # Explicit fact updates
    m = RX_CHANGE_MY.search(tt)
    if m:
        key = m.group("key").strip()
        val = m.group("val").strip()
        intents.append(_mk("fact.update", gmem.detect_domain_from_key(key), key, val, 0.92))

    m = RX_MY_FAVORITE.search(tt)
    if m:
        key = m.group("key").strip()
        val = m.group("val").strip()
        intents.append(_mk("fact.update", gmem.detect_domain_from_key(key), key, val, 0.92))

    # Negation (reasoner will convert to delete/replace)
    m = RX_NEGATION.search(tt)
    if m:
        val = m.group("val").strip()
        intents.append(_mk("fact.update", None, None, f"not {val}", 0.5))

    # Preferences (likes / dislikes)
    m = RX_I_LIKE.search(tt)
    if m:
        item = m.group("item").strip()
        dom = gmem.detect_domain_from_key(item)
        intents.append(_mk("preference.statement", dom, item, None, 0.9, polarity=+1,
                           tone="positive", intimacy=min(1, intimacy_level)))

    m = RX_I_DISLIKE.search(tt)
    if m:
        item = m.group("item").strip()
        dom = gmem.detect_domain_from_key(item)
        intents.append(_mk("preference.statement", dom, item, None, 0.9, polarity=-1,
                           tone="negative", intimacy=min(1, intimacy_level)))

    # Topic intro
    if re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b", tt):
        intents.append(_mk("smalltalk", None, None, None, 0.5, tone="neutral"))

    if not intents:
        intents.append(_mk("smalltalk", None, None, None, 0.4, tone="neutral"))

    return intents


def parse_message(text: str, intimacy_level: int = 0) -> List[Dict[str, Any]]:
    """
    Deterministic parser that:
      - splits into clauses first
      - trims punctuation and spaces
      - parses each clause independently
      - concatenates all detected intents in order
    """
    if not text or not text.strip():
        return [_mk("smalltalk", None, None, None, 0.3, tone="neutral")]
    intents: List[Dict[str, Any]] = []
    # Normalize clauses before parsing (fix for leading/trailing punctuation)
    clauses = [c.strip(" ,;.") for c in _CLAUSE_SPLIT_RX.split(text) if c and c.strip()]
    print(f"[ClauseSplit] {clauses}")  # optional debug; comment out in production
    for clause in clauses:
        intents.extend(_parse_single_clause(clause, intimacy_level))
    return intents