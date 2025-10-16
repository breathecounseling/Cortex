"""
executor/core/semantic_parser.py
--------------------------------
Phase 2.10: Semantic parser for Echo
- Converts free-form user text into structured intents (supports multi-intent)
- Safe deterministic heuristics + GPT-5 hook (optional) for richer parsing
- Avoids procedural content; returns compact JSON dictionary per intent

Intent objects (list[dict]):
{
  "intent": "fact.update" | "fact.query" | "location.update" | "location.query"
            | "preference.statement" | "smalltalk" | "reflective.question",
  "domain": "color" | "food" | "location" | "movie" | "music" | "project" | None,
  "key":    str | None,
  "value":  str | None,
  "polarity": +1 | -1 | None,    # for preferences
  "scope":  "home" | "current" | "trip" | None,  # for location.update/query
  "tone":   "positive" | "neutral" | "negative" | "reflective" | None,
  "confidence": float,
  "intimacy": int  # 0..3 (0 basic; 3 deep/therapeutic)
}
"""

from __future__ import annotations
import re
from typing import List, Dict, Any

from executor.utils import memory_graph as gmem
from executor.utils.sanitizer import sanitize_value


# --------- Helper regexes (lightweight, safe) ---------

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


def parse_message(text: str, intimacy_level: int = 0) -> List[Dict[str, Any]]:
    """
    Deterministic, safe parser for free-form user text.
    Returns possibly multiple intents per message.
    Later we can add a GPT-5 call here to enrich parsing; the interface stays the same.
    """
    intents: List[Dict[str, Any]] = []
    if not text or not text.strip():
        return [{"intent": "smalltalk", "domain": None, "key": None, "value": None,
                 "polarity": None, "scope": None, "tone": "neutral", "confidence": 0.3,
                 "intimacy": 0}]

    t = text.strip()

    # --- Canonical questions
    m = RX_WHATS_MY.search(t)
    if m:
        key = m.group("key").strip()
        return [_mk("fact.query", gmem.detect_domain_from_key(key), key, None, 0.85)]

    if RX_WHERE_AM_I_GOING.search(t):
        return [_mk("location.query", "location", "trip", None, 0.9, scope="trip")]

    if RX_WHERE_AM_I.search(t):
        return [_mk("location.query", "location", "current", None, 0.9, scope="current")]

    if RX_WHERE_DO_I_LIVE.search(t):
        return [_mk("location.query", "location", "home", None, 0.9, scope="home")]

    # --- Location updates
    m = RX_LIVE_IN.search(t)
    if m:
        city = m.group("city").strip()
        return [_mk("location.update", "location", "home", city, 0.95, scope="home")]

    m = RX_IM_IN.search(t)
    if m:
        city = m.group("city").strip()
        return [_mk("location.update", "location", "current", city, 0.95, scope="current")]

    m = RX_TRIP_TO.search(t)
    if m:
        city = m.group("city").strip()
        return [_mk("location.update", "location", "trip", city, 0.95, scope="trip")]

    # --- Explicit fact updates
    m = RX_CHANGE_MY.search(t)
    if m:
        key = m.group("key").strip()
        val = m.group("val").strip()
        return [_mk("fact.update", gmem.detect_domain_from_key(key), key, val, 0.92)]

    m = RX_MY_FAVORITE.search(t)
    if m:
        key = m.group("key").strip()
        val = m.group("val").strip()
        return [_mk("fact.update", gmem.detect_domain_from_key(key), key, val, 0.92)]

    # --- Negation (reasoner will convert to delete/replace)
    if RX_NEGATION.search(t):
        val = RX_NEGATION.search(t).group("val").strip()
        # attach to last fact later via reasoner; keep as update for pipeline
        return [_mk("fact.update", None, None, f"not {val}", 0.5)]

    # --- Preferences (likes / dislikes)
    m = RX_I_LIKE.search(t)
    if m:
        item = m.group("item").strip()
        dom = gmem.detect_domain_from_key(item)
        return [_mk("preference.statement", dom, item, None, 0.9, polarity=+1,
                    tone="positive", intimacy=min(1, intimacy_level))]

    m = RX_I_DISLIKE.search(t)
    if m:
        item = m.group("item").strip()
        dom = gmem.detect_domain_from_key(item)
        return [_mk("preference.statement", dom, item, None, 0.9, polarity=-1,
                    tone="negative", intimacy=min(1, intimacy_level))]

    # --- Topic intro (handled in reasoner but label here if spotted)
    if re.search(r"(?i)\b(let'?s\s+talk\s+about|switch\s+to|change\s+topic\s+to)\b", t):
        # reasoner will set topic; keep smalltalk intent
        return [_mk("smalltalk", None, None, None, 0.5, tone="neutral")]

    # --- Default smalltalk / unknown
    return [_mk("smalltalk", None, None, None, 0.4, tone="neutral")]