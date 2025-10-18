"""
executor/core/semantic_parser.py
--------------------------------
Phase 2.16 — richer intent parsing with deliverable detection.

Parses multi-clause user input into intents:
- goal.create (with subtype & deliverable)
- goal.close
- relation / preference / fact parsing (existing)
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


def _mk(intent: str, domain: str | None, key: str | None, value: str | None,
        confidence: float, **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "intent": intent,
        "domain": domain,
        "key": gmem.canonicalize_key(key) if key else None,
        "value": sanitize_value(value) if value else value,
        "confidence": float(confidence),
    }
    if extra:
        out.update(extra)
    return out


# ---------- Helper regexes ----------
RX_WHATS_MY = re.compile(r"(?i)\b(what('?s| is)\s+my)\s+(?P<key>.+?)\??$")
RX_GOAL_CREATE = re.compile(
    r"(?i)\b(?:i\s+(?:want|need|plan|would\s+like)\s+to|help\s+me|let'?s)\s+"
    r"(?P<verb>make|build|create|develop|finish|complete|set\s+up)\s+"
    r"(?P<title>[a-z0-9][\w\s\-\&]+)$"
)
RX_GOAL_CLOSE = re.compile(
    r"(?i)\b(mark|set)\s+(?:this|that|the\s+goal)\s+(?:as\s+)?(done|finished|complete|closed)\b"
)

# deliverable hints (non-exhaustive, safe heuristics)
_RX_APP = re.compile(r"(?i)\b(app|application|module|dashboard|web\s*app|ui|interface)\b")
_RX_SHEET = re.compile(r"(?i)\b(spreadsheet|sheet|excel|csv|table|report|projection|forecast|analysis|analytics)\b")
_RX_DOC = re.compile(r"(?i)\b(document|doc|proposal|plan|playbook|brief|outline)\b")


def _infer_deliverable(text: str) -> str | None:
    """Lightweight heuristic for deliverable inference from the user's words."""
    if _RX_APP.search(text):   return "app_module"
    if _RX_SHEET.search(text): return "spreadsheet"
    if _RX_DOC.search(text):   return "document"
    # opportunistic nouns
    if "tracker" in text.lower(): return "app_module"
    if "projection" in text.lower() or "analysis" in text.lower(): return "spreadsheet"
    return None


# ---------- Main clause parser ----------
def _parse_single_clause(t: str, intimacy_level: int) -> List[Dict[str, Any]]:
    intents: List[Dict[str, Any]] = []
    tt = (t or "").strip()
    if not tt:
        return intents

    # Questions like "what's my X"
    m = RX_WHATS_MY.search(tt)
    if m:
        key = m.group("key").strip()
        intents.append(_mk("fact.query", gmem.detect_domain_from_key(key), key, None, 0.85))
        return intents

    # Goal create ("I want to make/build/create/develop ...")
    m = RX_GOAL_CREATE.search(tt)
    if m:
        verb = m.group("verb").lower()
        raw_title = m.group("title").strip().strip(".!?")
        # strip trivial suffix like "module", "app", etc. from title only if they are trailing adjectives
        title = re.sub(r"\b(app|module|dashboard|application|spreadsheet|sheet)\b$", "", raw_title, flags=re.I).strip()
        subtype = "build" if verb in ("make", "build", "create", "develop", "set up") else "finish"
        deliverable = _infer_deliverable(tt)  # app_module | spreadsheet | document | None

        intents.append(_mk("goal.create", None, "goal", title, 0.95,
                           subtype=subtype, deliverable=deliverable))
        return intents

    # Goal close ("mark this goal done")
    if RX_GOAL_CLOSE.search(tt):
        intents.append(_mk("goal.close", None, "goal", "closed", 0.9))
        return intents

    # Fallback smalltalk
    intents.append(_mk("smalltalk", None, None, None, 0.4))
    return intents


# ---------- Public API ----------
def parse_message(text: str, intimacy_level: int = 0) -> List[Dict[str, Any]]:
    """Split into clauses, parse each, combine intents."""
    if not text or not text.strip():
        return [_mk("smalltalk", None, None, None, 0.3)]
    intents: List[Dict[str, Any]] = []
    clauses = [c.strip(" ,;.") for c in _CLAUSE_SPLIT_RX.split(text) if c and c.strip()]
    print(f"[ClauseSplit] {clauses}")
    for clause in clauses:
        intents.extend(_parse_single_clause(clause, intimacy_level))
    return intents