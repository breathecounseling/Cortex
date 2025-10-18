"""
executor/core/semantic_parser.py
--------------------------------
Phase 2.18b — Goal intents: create/confirm/keep/complete, with pronoun handling.
"""

from __future__ import annotations
import re
from typing import List, Dict, Any

from executor.utils import memory_graph as gmem
from executor.utils.sanitizer import sanitize_value

# ---------- Clause splitter ----------
_CLAUSE_SPLIT_RX = re.compile(
    r"\s*(?:,|;|\bbut\b|\band then\b|\bthen\b|\bhowever\b|\band\s+(?:my|i'?m|i\s+am)\b)\s*",
    re.I,
)

def _mk(intent: str, domain=None, key=None, value=None,
        confidence: float = 0.9, **extra) -> Dict[str, Any]:
    out = {
        "intent": intent, "domain": domain, "key": key,
        "value": sanitize_value(value) if value else value,
        "confidence": confidence,
    }
    out.update(extra)
    return out

# ---------- Patterns ----------
RX_WHATS_MY   = re.compile(r"(?i)\bwhat('?s| is)\s+my\s+(?P<key>.+?)\??$")
RX_GOAL_CREATE= re.compile(r"(?i)\bi\s+(?:want|need|plan|would\s+like)\s+to\s+(?P<verb>build|make|create|develop|design|set\s+up)\s+(?P<title>.+)$")
RX_GOAL_CONFIRM_MODULE = re.compile(r"(?i)\b(full\s+module|as\s+a\s+module|make\s+it\s+a\s+module|build\s+a\s+module)\b")
RX_GOAL_KEEP  = re.compile(r"(?i)\b(keep\s+working|resume|continue|pick\s+up)\b")
RX_GOAL_COMPLETE = re.compile(r"(?i)\b(done|finished|complete|wrapped\s*up|that'?s\s*it|we'?re\s*good)\b")

RX_I_LIKE    = re.compile(r"(?i)\bi\s+(?:really\s+)?(?:like|love|enjoy|am\s+into)\s+(?P<item>.+)$")
RX_I_DISLIKE = re.compile(r"(?i)\bi\s+(?:don'?t\s+like|dislike|hate|can'?t\s+stand)\s+(?P<item>.+)$")

def _parse_single_clause(s: str) -> List[Dict[str, Any]]:
    s = s.strip()
    intents: List[Dict[str, Any]] = []
    if not s:
        return intents

    # Goal lifecycle
    m = RX_GOAL_CREATE.search(s)
    if m:
        title = m.group("title").strip(" .!?")
        verb  = m.group("verb").lower()
        intents.append(_mk("goal.create", "goal", "title", title, 0.95,
                           subtype="build" if verb in ("build","make","create","develop","design","set up") else "finish"))
        return intents

    if RX_GOAL_CONFIRM_MODULE.search(s):
        intents.append(_mk("goal.confirm_deliverable", "goal", "deliverable", "app_module", 0.9))
        return intents

    if RX_GOAL_KEEP.search(s):
        intents.append(_mk("goal.keep_working", "goal", None, None, 0.9))
        return intents

    if RX_GOAL_COMPLETE.search(s):
        intents.append(_mk("goal.complete", "goal", None, None, 0.95))
        return intents

    # Preferences
    for rx, pol in ((RX_I_LIKE, +1), (RX_I_DISLIKE, -1)):
        m = rx.search(s)
        if m:
            item = m.group("item").strip()
            intents.append(_mk("preference.statement",
                               gmem.detect_domain_from_key(item),
                               item, None, 0.9, polarity=pol))
            return intents

    # Facts
    m = RX_WHATS_MY.search(s)
    if m:
        key = m.group("key").strip()
        intents.append(_mk("fact.query", gmem.detect_domain_from_key(key), key, None, 0.85))
        return intents

    intents.append(_mk("smalltalk", None, None, None, 0.3))
    return intents

def parse_message(text: str, intimacy_level: int = 0) -> List[Dict[str, Any]]:
    clauses = [c.strip(" ,;.") for c in _CLAUSE_SPLIT_RX.split(text or "") if c.strip()]
    intents: List[Dict[str, Any]] = []
    print(f"[ClauseSplit] {clauses}")
    for c in clauses:
        intents.extend(_parse_single_clause(c))
    return intents